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
	"crypto/x509"
	"fmt"
	"os"
	"time"

	"github.com/openkruise/agents/pkg/proxy"
)

func sendWithOutbound(outbound *proxy.PeerOutbound, tlsConfigured bool, req sendRequest) sendResponse {
	if outbound == nil {
		return sendResponse{Error: "peer outbound client is not configured", TLSConfigured: tlsConfigured}
	}
	if len(req.PeerIPs) == 0 {
		return sendResponse{Error: "peerIPs must not be empty", TLSConfigured: tlsConfigured}
	}
	outbound.CloseIdleConnections()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	err := proxy.SyncRouteWithPeers(ctx, newStaticPeers(req.PeerIPs), req.Route, outbound)
	if err != nil {
		return sendResponse{Error: err.Error(), TLSConfigured: tlsConfigured}
	}
	return sendResponse{OK: true, TLSConfigured: tlsConfigured}
}

func explicitClientTLS(certFile, keyFile, caFile string) (*tls.Config, error) {
	cert, err := tls.LoadX509KeyPair(certFile, keyFile)
	if err != nil {
		return nil, fmt.Errorf("load explicit client certificate: %w", err)
	}
	caPEM, err := os.ReadFile(caFile) // #nosec G304 -- test fixture certificate path from env
	if err != nil {
		return nil, fmt.Errorf("read explicit server CA: %w", err)
	}
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(caPEM) {
		return nil, fmt.Errorf("parse explicit server CA")
	}
	return &tls.Config{
		MinVersion:   tls.VersionTLS12,
		RootCAs:      pool,
		ServerName:   serverName,
		Certificates: []tls.Certificate{cert},
		GetClientCertificate: func(*tls.CertificateRequestInfo) (*tls.Certificate, error) {
			return &cert, nil
		},
	}, nil
}
