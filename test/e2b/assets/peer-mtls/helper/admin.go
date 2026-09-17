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
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log"
	"net"
	"net/http"
	"sync"
	"sync/atomic"
	"time"

	"github.com/openkruise/agents/pkg/peers"
	"github.com/openkruise/agents/pkg/sandboxroute"
)

type eventRecord struct {
	TLSVersion            string `json:"tlsVersion"`
	ClientCertFingerprint string `json:"clientCertFingerprint"`
	RouteID               string `json:"routeID"`
}

type sendRequest struct {
	PeerIPs  []string           `json:"peerIPs"`
	Identity string             `json:"identity"`
	Route    sandboxroute.Route `json:"route"`
}

type sendResponse struct {
	OK            bool   `json:"ok"`
	Error         string `json:"error,omitempty"`
	TLSConfigured bool   `json:"tlsConfigured"`
}

type memberView struct {
	IP   string `json:"ip"`
	Name string `json:"name"`
}

type statsView struct {
	Accepts     int64 `json:"accepts"`
	TLSAttempts int64 `json:"tlsAttempts"`
	RefreshHits int64 `json:"refreshHits"`
}

type adminState struct {
	mu      sync.Mutex
	events  []eventRecord
	members func() []peers.Peer
	send    func(sendRequest) sendResponse

	accepts     atomic.Int64
	tlsAttempts atomic.Int64
	refreshHits atomic.Int64
}

func (a *adminState) record(routeID string, state *tls.ConnectionState) {
	fp := ""
	ver := ""
	if state != nil {
		ver = tlsVersionName(state.Version)
		if len(state.PeerCertificates) > 0 {
			fp = certFingerprint(state.PeerCertificates[0])
		}
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	a.events = append(a.events, eventRecord{
		TLSVersion:            ver,
		ClientCertFingerprint: fp,
		RouteID:               routeID,
	})
}

func (a *adminState) snapshot() []eventRecord {
	a.mu.Lock()
	defer a.mu.Unlock()
	out := make([]eventRecord, len(a.events))
	copy(out, a.events)
	return out
}

func (a *adminState) resetEvents() {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.events = nil
}

func (a *adminState) handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	})
	mux.HandleFunc("GET /events", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, a.snapshot())
	})
	mux.HandleFunc("POST /events/reset", func(w http.ResponseWriter, _ *http.Request) {
		a.resetEvents()
		w.WriteHeader(http.StatusNoContent)
	})
	mux.HandleFunc("GET /members", func(w http.ResponseWriter, _ *http.Request) {
		var list []memberView
		if a.members != nil {
			for _, p := range a.members() {
				list = append(list, memberView{IP: p.IP, Name: p.Name})
			}
		}
		if list == nil {
			list = []memberView{}
		}
		writeJSON(w, list)
	})
	mux.HandleFunc("POST /send", func(w http.ResponseWriter, r *http.Request) {
		if a.send == nil {
			writeJSONStatus(w, http.StatusNotImplemented, sendResponse{Error: "send is not enabled"})
			return
		}
		var req sendRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeJSONStatus(w, http.StatusBadRequest, sendResponse{Error: "invalid send payload"})
			return
		}
		writeJSON(w, a.send(req))
	})
	mux.HandleFunc("GET /stats", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, statsView{
			Accepts:     a.accepts.Load(),
			TLSAttempts: a.tlsAttempts.Load(),
			RefreshHits: a.refreshHits.Load(),
		})
	})
	mux.HandleFunc("POST /stats/reset", func(w http.ResponseWriter, _ *http.Request) {
		a.accepts.Store(0)
		a.tlsAttempts.Store(0)
		a.refreshHits.Store(0)
		w.WriteHeader(http.StatusNoContent)
	})
	return mux
}

func probeHandler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	})
	return mux
}

func serve(ctxDone <-chan struct{}, addr string, handler http.Handler) {
	server := &http.Server{Addr: addr, Handler: handler, ReadHeaderTimeout: 5 * time.Second}
	go func() {
		<-ctxDone
		_ = server.Close()
	}()
	go func() {
		log.Printf("listening on %s", addr)
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Printf("server %s: %v", addr, err)
		}
	}()
}

func writeJSON(w http.ResponseWriter, v any) {
	writeJSONStatus(w, http.StatusOK, v)
}

func writeJSONStatus(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func certFingerprint(cert *x509.Certificate) string {
	if cert == nil {
		return ""
	}
	sum := sha256.Sum256(cert.Raw)
	return hex.EncodeToString(sum[:])
}

func tlsVersionName(v uint16) string {
	switch v {
	case tls.VersionTLS12:
		return "TLS1.2"
	case tls.VersionTLS13:
		return "TLS1.3"
	default:
		return fmt.Sprintf("0x%x", v)
	}
}

type countingListener struct {
	net.Listener
	admin *adminState
}

func (l *countingListener) Accept() (net.Conn, error) {
	c, err := l.Listener.Accept()
	if err == nil && l.admin != nil {
		l.admin.accepts.Add(1)
	}
	return c, err
}
