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

package admin

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/http"
	"sync/atomic"
	"time"

	"github.com/prometheus/client_golang/prometheus/promhttp"
	"k8s.io/klog/v2"
	"sigs.k8s.io/controller-runtime/pkg/metrics"

	"github.com/openkruise/agents/pkg/utils/network"
)

const DefaultPort = 8081

// ReadyCheck reports whether one enabled component is ready.
type ReadyCheck func() bool

type Server struct {
	httpServer *http.Server
	live       atomic.Bool
	ready      []ReadyCheck
}

type Options struct {
	BindAddress string
	Port        int
	Ready       []ReadyCheck
}

func New(opts Options) *Server {
	s := &Server{ready: opts.Ready}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /livez", s.handleLivez)
	mux.HandleFunc("GET /readyz", s.handleReadyz)
	mux.Handle("GET /metrics", promhttp.HandlerFor(metrics.Registry, promhttp.HandlerOpts{}))
	s.httpServer = &http.Server{
		Addr:              network.ListenAddress(opts.BindAddress, opts.Port),
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
	}
	s.live.Store(true)
	return s
}

func (s *Server) Start() error {
	listener, err := net.Listen("tcp", s.httpServer.Addr)
	if err != nil {
		return fmt.Errorf("listen for admin API on %s: %w", s.httpServer.Addr, err)
	}
	go func() {
		klog.InfoS("Starting admin server", "address", listener.Addr().String())
		if err := s.httpServer.Serve(listener); err != nil && !errors.Is(err, http.ErrServerClosed) && !errors.Is(err, net.ErrClosed) {
			klog.ErrorS(err, "admin HTTP server failed")
		}
	}()
	return nil
}

func (s *Server) Shutdown(ctx context.Context) error {
	s.live.Store(false)
	if s.httpServer == nil {
		return nil
	}
	return s.httpServer.Shutdown(ctx)
}

func (s *Server) handleLivez(w http.ResponseWriter, _ *http.Request) {
	if !s.live.Load() {
		http.Error(w, "shutting down", http.StatusServiceUnavailable)
		return
	}
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte("ok"))
}

func (s *Server) handleReadyz(w http.ResponseWriter, _ *http.Request) {
	if !s.live.Load() {
		http.Error(w, "shutting down", http.StatusServiceUnavailable)
		return
	}
	for _, check := range s.ready {
		if check != nil && !check() {
			http.Error(w, "not ready", http.StatusServiceUnavailable)
			return
		}
	}
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte("ok"))
}
