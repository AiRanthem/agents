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
	"log"
	"net"
	"net/http"
	"os"
	"strconv"
	"time"

	"github.com/openkruise/agents/pkg/sandboxroute/refresh"
)

func runEcho(ctx context.Context) error {
	body := os.Getenv("RESPONSE_BODY")
	if body == "" {
		return fmt.Errorf("RESPONSE_BODY is required")
	}
	admin := &adminState{}
	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/plain")
		_, _ = w.Write([]byte(body))
	})
	server := &http.Server{Addr: echoAddr, Handler: mux, ReadHeaderTimeout: 5 * time.Second}
	go func() {
		<-ctx.Done()
		_ = server.Close()
	}()
	serve(ctx.Done(), adminAddr, admin.handler())
	serve(ctx.Done(), probeAddr, probeHandler())
	log.Printf("echo listening on %s", echoAddr)
	if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		return err
	}
	return nil
}

func runTLSRefresh(ctx context.Context) error {
	admin := &adminState{}
	plaintext := os.Getenv("PLAINTEXT") == "true"
	ln, err := net.Listen("tcp", ":"+strconv.Itoa(refresh.DefaultPort))
	if err != nil {
		return err
	}
	counted := &countingListener{Listener: ln, admin: admin}
	var serveLn net.Listener = counted
	if !plaintext {
		tlsLn, err := newNegativeTLSListener(counted, admin)
		if err != nil {
			return err
		}
		serveLn = tlsLn
	}
	mux := http.NewServeMux()
	mux.HandleFunc(refresh.Path, func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		admin.refreshHits.Add(1)
		w.WriteHeader(http.StatusNoContent)
	})
	server := &http.Server{Handler: mux, ReadHeaderTimeout: 5 * time.Second}
	go func() {
		<-ctx.Done()
		_ = server.Close()
	}()
	serve(ctx.Done(), adminAddr, admin.handler())
	serve(ctx.Done(), probeAddr, probeHandler())
	log.Printf("tls-refresh listening on %s plaintext=%t", serveLn.Addr(), plaintext)
	if err := server.Serve(serveLn); err != nil && err != http.ErrServerClosed {
		return err
	}
	return nil
}

func newNegativeTLSListener(inner net.Listener, admin *adminState) (net.Listener, error) {
	certFile := os.Getenv("TLS_CERT_FILE")
	keyFile := os.Getenv("TLS_KEY_FILE")
	if certFile == "" || keyFile == "" {
		return nil, fmt.Errorf("TLS_CERT_FILE and TLS_KEY_FILE are required")
	}
	cert, err := tls.LoadX509KeyPair(certFile, keyFile)
	if err != nil {
		return nil, err
	}
	cfg := &tls.Config{
		MinVersion:   tls.VersionTLS12,
		Certificates: []tls.Certificate{cert},
		ClientAuth:   tls.RequestClientCert,
	}
	if caFile := os.Getenv("TLS_CA_FILE"); caFile != "" {
		pem, err := readCertFile(caFile)
		if err != nil {
			return nil, err
		}
		pool := x509.NewCertPool()
		if !pool.AppendCertsFromPEM(pem) {
			return nil, fmt.Errorf("parse TLS_CA_FILE")
		}
		cfg.ClientCAs = pool
	}
	return &tlsAttemptListener{Listener: inner, cfg: cfg, admin: admin}, nil
}

type tlsAttemptListener struct {
	net.Listener
	cfg   *tls.Config
	admin *adminState
}

func (l *tlsAttemptListener) Accept() (net.Conn, error) {
	for {
		raw, err := l.Listener.Accept()
		if err != nil {
			return nil, err
		}
		if l.admin != nil {
			l.admin.tlsAttempts.Add(1)
		}
		conn := tls.Server(raw, l.cfg)
		if err := conn.Handshake(); err != nil {
			// Failed handshakes are the expected negative-test traffic here.
			// Returning the error would make http.Server.Serve exit, killing
			// the listener that later cases still need.
			log.Printf("tls-refresh handshake failed: %v", err)
			_ = raw.Close()
			continue
		}
		return conn, nil
	}
}
