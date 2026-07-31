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

package runtime

import (
	"context"
	"encoding/pem"
	"net"
	"net/http"
	"net/http/httptest"
	"strconv"
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/util/wait"

	agentsv1alpha1 "github.com/openkruise/agents/api/v1alpha1"
)

// sandboxWithPodIP returns a sandbox whose Pod IP is set (but with no runtime
// URL annotation), so TLS-mode addressing must derive the dial target from the
// Pod IP while addressing the request by the certificate authority hostname.
func sandboxWithPodIP(ip string) *agentsv1alpha1.Sandbox {
	return &agentsv1alpha1.Sandbox{
		ObjectMeta: metav1.ObjectMeta{Name: "tls-sandbox", Namespace: "default"},
		Status: agentsv1alpha1.SandboxStatus{
			PodInfo: agentsv1alpha1.PodInfo{PodIP: ip},
		},
	}
}

// TestTLSMode_ResolvesAuthorityButDialsPodIP verifies the curl --resolve
// behaviour: the request is addressed to the certificate authority hostname
// (which has no DNS record) while the TCP connection is pinned to the sandbox
// Pod IP, and TLS verification still succeeds against the server certificate.
func TestTLSMode_ResolvesAuthorityButDialsPodIP(t *testing.T) {
	var gotHost string
	mux := http.NewServeMux()
	mux.HandleFunc("/v1/storage/mounts", func(w http.ResponseWriter, r *http.Request) {
		gotHost = r.Host
		writeMountResponse(t, w, http.StatusOK, CreateMountResponse{Success: true, MountPath: "/m"})
	})
	server := httptest.NewTLSServer(mux)
	t.Cleanup(server.Close)

	// The httptest server certificate is issued for "example.com" (and the
	// loopback IPs); use it as both the trust anchor and the authority so the
	// handshake validates when we pin the dial to 127.0.0.1.
	caPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: server.Certificate().Raw})

	host, portStr, err := net.SplitHostPort(server.Listener.Addr().String())
	require.NoError(t, err)
	port, err := strconv.Atoi(portStr)
	require.NoError(t, err)

	rt := NewRuntime(
		sandboxWithPodIP(host), // Pod IP == loopback the test server listens on
		WithRetry(wait.Backoff{Steps: 1}),
		WithTLS(TLSBundle{CABundle: caPEM}),
		WithAuthority("example.com"),
		WithTLSPort(port),
	)

	resp, err := rt.Storage().Mount(context.Background(), testMountRequest("oss"))
	require.NoError(t, err)
	assert.True(t, resp.Success)
	// The Host header must carry the authority, not the dialed IP, proving the
	// request was addressed by domain even though the connection went to the IP.
	assert.Contains(t, gotHost, "example.com")
}

// TestTLSMode_OneShotTransportDoesNotLeakConnections verifies that the
// per-attempt pinned transport disables keep-alives: each call opens exactly
// one connection and the server observes it closed after the response, so the
// transport discarded after the attempt never strands an idle TLS connection.
func TestTLSMode_OneShotTransportDoesNotLeakConnections(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/v1/storage/mounts", func(w http.ResponseWriter, r *http.Request) {
		writeMountResponse(t, w, http.StatusOK, CreateMountResponse{Success: true, MountPath: "/m"})
	})
	server := httptest.NewUnstartedServer(mux)
	var mu sync.Mutex
	opened, closed := 0, 0
	server.Config.ConnState = func(_ net.Conn, state http.ConnState) {
		mu.Lock()
		defer mu.Unlock()
		switch state {
		case http.StateNew:
			opened++
		case http.StateClosed:
			closed++
		}
	}
	server.StartTLS()
	t.Cleanup(server.Close)

	caPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: server.Certificate().Raw})
	host, portStr, err := net.SplitHostPort(server.Listener.Addr().String())
	require.NoError(t, err)
	port, err := strconv.Atoi(portStr)
	require.NoError(t, err)

	rt := NewRuntime(
		sandboxWithPodIP(host),
		WithRetry(wait.Backoff{Steps: 1}),
		WithTLS(TLSBundle{CABundle: caPEM}),
		WithAuthority("example.com"),
		WithTLSPort(port),
	)

	for i := 0; i < 2; i++ {
		_, err := rt.Storage().Mount(context.Background(), testMountRequest("oss"))
		require.NoError(t, err)
	}

	// Keep-alives are disabled, so every call must open its own connection and
	// the server must observe each of them closed shortly after the response
	// instead of lingering as an idle kept-alive connection.
	require.Eventually(t, func() bool {
		mu.Lock()
		defer mu.Unlock()
		return opened == 2 && closed == 2
	}, 3*time.Second, 20*time.Millisecond)
}

// TestTLSMode_InvalidCAIsPermanentError verifies that an unusable CA bundle is
// reported as a permanent error on the first call instead of being retried.
func TestTLSMode_InvalidCAIsPermanentError(t *testing.T) {
	rt := NewRuntime(
		sandboxWithPodIP("10.0.0.1"),
		WithRetry(fastBackoff),
		WithTLS(TLSBundle{CABundle: []byte("not a pem")}),
	)
	_, err := rt.Storage().Mount(context.Background(), testMountRequest("oss"))
	require.Error(t, err)
	assert.Contains(t, err.Error(), "invalid runtime TLS configuration")
}

// TestBuildClientTLSConfig covers the bundle validation branches.
func TestBuildClientTLSConfig(t *testing.T) {
	// Reuse a valid CA PEM from a throwaway TLS server certificate.
	server := httptest.NewTLSServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	t.Cleanup(server.Close)
	validCA := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: server.Certificate().Raw})

	tests := []struct {
		name    string
		bundle  TLSBundle
		wantErr bool
	}{
		{name: "missing CA", bundle: TLSBundle{}, wantErr: true},
		{name: "invalid CA", bundle: TLSBundle{CABundle: []byte("garbage")}, wantErr: true},
		{name: "valid CA only", bundle: TLSBundle{CABundle: validCA}, wantErr: false},
		{name: "invalid client cert", bundle: TLSBundle{CABundle: validCA, ClientCertPEM: []byte("x"), ClientKeyPEM: []byte("y")}, wantErr: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cfg, err := buildClientTLSConfig(tt.bundle, "example.com")
			if tt.wantErr {
				require.Error(t, err)
				return
			}
			require.NoError(t, err)
			require.NotNil(t, cfg)
			assert.Equal(t, "example.com", cfg.ServerName)
			assert.NotNil(t, cfg.RootCAs)
		})
	}
}

// TestTransportOptionsFor covers the dual-switch decision matrix: the sandbox
// capability annotation AND the caller-side TLS bundle must both be present
// for the TLS options to be produced.
func TestTransportOptionsFor(t *testing.T) {
	bundle := &TLSBundle{CABundle: []byte("pem")}
	sandboxWithTLSPort := func(port string) *agentsv1alpha1.Sandbox {
		sbx := sandboxWithPodIP("10.0.0.1")
		sbx.Annotations = map[string]string{agentsv1alpha1.AnnotationRuntimeTLSPort: port}
		return sbx
	}

	tests := []struct {
		name        string
		sbx         *agentsv1alpha1.Sandbox
		bundle      *TLSBundle
		wantTLS     bool
		wantTLSPort int
		wantErr     bool
	}{
		{name: "nil sandbox", sbx: nil, bundle: bundle},
		{name: "no annotation stays HTTP", sbx: sandboxWithPodIP("10.0.0.1"), bundle: bundle},
		{name: "annotation without bundle stays HTTP", sbx: sandboxWithTLSPort("49984"), bundle: nil},
		{name: "annotation with bundle enables TLS", sbx: sandboxWithTLSPort("49984"), bundle: bundle, wantTLS: true, wantTLSPort: 49984},
		{name: "annotation with custom port", sbx: sandboxWithTLSPort("50000"), bundle: bundle, wantTLS: true, wantTLSPort: 50000},
		{name: "non-numeric annotation is an error", sbx: sandboxWithTLSPort("not-a-port"), bundle: bundle, wantErr: true},
		{name: "out-of-range annotation is an error", sbx: sandboxWithTLSPort("70000"), bundle: nil, wantErr: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			opts, err := TransportOptionsFor(tt.sbx, tt.bundle)
			if tt.wantErr {
				require.Error(t, err)
				assert.Nil(t, opts)
				return
			}
			require.NoError(t, err)
			if !tt.wantTLS {
				assert.Nil(t, opts)
				return
			}
			// Apply the options through the regular constructor and inspect the
			// resulting client to prove TLS mode and port took effect.
			rc, ok := NewRuntime(tt.sbx, opts...).(*runtimeClient)
			require.True(t, ok)
			assert.True(t, rc.tlsEnabled)
			assert.Equal(t, tt.wantTLSPort, rc.tlsPort)
		})
	}
}
