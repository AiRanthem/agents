/*
Copyright 2026.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package main

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"strconv"
	"time"

	"k8s.io/client-go/kubernetes/scheme"
	"k8s.io/client-go/rest"
	ctrlclient "sigs.k8s.io/controller-runtime/pkg/client"

	"github.com/openkruise/agents/pkg/peers"
	"github.com/openkruise/agents/pkg/peersecurity"
	"github.com/openkruise/agents/pkg/proxy"
	"github.com/openkruise/agents/pkg/sandboxroute"
	"github.com/openkruise/agents/pkg/sandboxroute/refresh"
	"github.com/openkruise/agents/pkg/utils"
)

func runWitness(ctx context.Context) error {
	k8s, err := inClusterClient()
	if err != nil {
		return err
	}
	inputs, err := peersecurityInputsFromEnv()
	if err != nil {
		return err
	}
	loadCtx, cancel := context.WithTimeout(ctx, peersecurity.LoadTimeout)
	_, serverTLS, clientTLS, err := peersecurity.Load(loadCtx, k8s, inputs)
	cancel()
	if err != nil {
		return fmt.Errorf("load peer security: %w", err)
	}
	if serverTLS == nil || clientTLS == nil {
		return fmt.Errorf("witness requires peer TLS server and client secrets")
	}

	outbound := proxy.NewPeerOutbound(clientTLS)
	explicit := map[string]*proxy.PeerOutbound{"helper": outbound}
	if cfg, err := loadOptionalExplicit("untrusted"); err != nil {
		return err
	} else if cfg != nil {
		explicit["untrusted"] = proxy.NewPeerOutbound(cfg)
	}
	if cfg, err := loadOptionalExplicit("server-as-client"); err != nil {
		return err
	} else if cfg != nil {
		explicit["server-as-client"] = proxy.NewPeerOutbound(cfg)
	}

	nodeName := os.Getenv("HOSTNAME")
	if nodeName == "" {
		nodeName = os.Getenv("POD_NAME")
	}
	if nodeName == "" {
		return fmt.Errorf("HOSTNAME or POD_NAME is required")
	}
	namespace := os.Getenv("PEER_NAMESPACE")
	selector := os.Getenv("PEER_LABEL_SELECTOR")
	pm := peers.NewMemberlistPeers(k8s, nodePrefix+nodeName, namespace, selector)

	admin := &adminState{
		members: pm.GetAllMembers,
		send: func(req sendRequest) sendResponse {
			identity := req.Identity
			if identity == "" {
				identity = "helper"
			}
			chosen, ok := explicit[identity]
			if !ok {
				return sendResponse{Error: "unknown identity " + identity, TLSConfigured: true}
			}
			return sendWithOutbound(chosen, true, req)
		},
	}

	cfg := serverTLS.Clone()
	cfg.ClientAuth = tls.RequireAndVerifyClientCert
	peerLn, err := net.Listen("tcp", ":"+strconv.Itoa(refresh.DefaultPort))
	if err != nil {
		return err
	}
	tlsLn := tls.NewListener(&countingListener{Listener: peerLn, admin: admin}, cfg)

	mux := http.NewServeMux()
	mux.HandleFunc(http.MethodPost+" "+refresh.Path, func(w http.ResponseWriter, r *http.Request) {
		if r.TLS == nil || len(r.TLS.VerifiedChains) == 0 {
			http.Error(w, "client certificate required", http.StatusForbidden)
			return
		}
		var route sandboxroute.Route
		if err := json.NewDecoder(r.Body).Decode(&route); err != nil {
			http.Error(w, "invalid route refresh payload", http.StatusBadRequest)
			return
		}
		admin.record(route.ID, r.TLS)
		admin.refreshHits.Add(1)
		w.WriteHeader(http.StatusNoContent)
	})
	peerServer := &http.Server{Handler: mux, ReadHeaderTimeout: 5 * time.Second}
	go func() {
		log.Printf("witness peer TLS listening on %s", tlsLn.Addr())
		if err := peerServer.Serve(tlsLn); err != nil && err != http.ErrServerClosed {
			log.Printf("witness peer server: %v", err)
		}
	}()
	go func() {
		<-ctx.Done()
		_ = peerServer.Close()
	}()

	bindPort := 7946
	if v := os.Getenv("MEMBERLIST_BIND_PORT"); v != "" {
		if p, err := strconv.Atoi(v); err == nil && p > 0 {
			bindPort = p
		}
	}
	if err := pm.Start(ctx, "", bindPort); err != nil {
		return fmt.Errorf("start memberlist: %w", err)
	}
	defer func() { _ = pm.Stop(context.Background()) }()

	serve(ctx.Done(), adminAddr, admin.handler())
	serve(ctx.Done(), probeAddr, probeHandler())
	<-ctx.Done()
	outbound.CloseIdleConnections()
	return nil
}

func inClusterClient() (ctrlclient.Client, error) {
	cfg, err := rest.InClusterConfig()
	if err != nil {
		return nil, fmt.Errorf("in-cluster config: %w", err)
	}
	return ctrlclient.New(cfg, ctrlclient.Options{Scheme: scheme.Scheme})
}

func peersecurityInputsFromEnv() (peersecurity.Inputs, error) {
	serverRef, err := utils.ParseSecretRef(os.Getenv("PEER_TLS_SERVER_SECRET"))
	if err != nil {
		return peersecurity.Inputs{}, fmt.Errorf("PEER_TLS_SERVER_SECRET: %w", err)
	}
	clientRef, err := utils.ParseSecretRef(os.Getenv("PEER_TLS_CLIENT_SECRET"))
	if err != nil {
		return peersecurity.Inputs{}, fmt.Errorf("PEER_TLS_CLIENT_SECRET: %w", err)
	}
	in := peersecurity.Inputs{
		TLSServerSecret: serverRef,
		TLSClientSecret: clientRef,
	}
	in.ApplyDefaults()
	if err := in.Validate(); err != nil {
		return peersecurity.Inputs{}, err
	}
	return in, nil
}

func loadOptionalExplicit(identity string) (*tls.Config, error) {
	var certFile, keyFile string
	switch identity {
	case "untrusted":
		certFile = os.Getenv("EXPLICIT_UNTRUSTED_CERT")
		keyFile = os.Getenv("EXPLICIT_UNTRUSTED_KEY")
	case "server-as-client":
		certFile = os.Getenv("EXPLICIT_SERVER_AS_CLIENT_CERT")
		keyFile = os.Getenv("EXPLICIT_SERVER_AS_CLIENT_KEY")
	default:
		return nil, fmt.Errorf("unknown explicit identity %q", identity)
	}
	if certFile == "" || keyFile == "" {
		return nil, nil
	}
	caFile := os.Getenv("EXPLICIT_SERVER_CA")
	if caFile == "" {
		return nil, fmt.Errorf("EXPLICIT_SERVER_CA is required for identity %s", identity)
	}
	return explicitClientTLS(certFile, keyFile, caFile)
}
