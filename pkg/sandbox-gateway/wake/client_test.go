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

package wake

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestConnectClient_Connect(t *testing.T) {
	tests := []struct {
		name         string
		status       int
		expectStatus int
	}{
		{name: "ok", status: http.StatusOK, expectStatus: http.StatusOK},
		{name: "created", status: http.StatusCreated, expectStatus: http.StatusCreated},
		{name: "conflict", status: http.StatusConflict, expectStatus: http.StatusConflict},
		{name: "bad request", status: http.StatusBadRequest, expectStatus: http.StatusBadRequest},
		{name: "unauthorized", status: http.StatusUnauthorized, expectStatus: http.StatusUnauthorized},
		{name: "forbidden", status: http.StatusForbidden, expectStatus: http.StatusForbidden},
		{name: "not found", status: http.StatusNotFound, expectStatus: http.StatusNotFound},
		{name: "server error", status: http.StatusInternalServerError, expectStatus: http.StatusInternalServerError},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var gotPath, gotKey, gotHost string
			var gotBody struct {
				Timeout int `json:"timeout"`
			}
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				gotPath = r.URL.Path
				gotKey = r.Header.Get(apiKeyHeader)
				gotHost = r.Host
				require.NoError(t, json.NewDecoder(r.Body).Decode(&gotBody))
				w.WriteHeader(tt.status)
			}))
			defer server.Close()
			client, err := NewConnectClient(server.URL, "system-key", nil)
			require.NoError(t, err)

			status, err := client.Connect(context.Background(), "default--sandbox", 300)

			require.NoError(t, err)
			assert.Equal(t, tt.expectStatus, status)
			assert.Equal(t, "/sandboxes/default--sandbox/connect", gotPath)
			assert.Equal(t, "system-key", gotKey)
			assert.Equal(t, "api."+server.Listener.Addr().String(), gotHost)
			assert.Equal(t, 300, gotBody.Timeout)
		})
	}
}

func TestManagerAPIAuthority(t *testing.T) {
	tests := []struct {
		name   string
		host   string
		expect string
	}{
		{name: "service host", host: "sandbox-manager.sandbox-system.svc:7788", expect: "api.sandbox-manager.sandbox-system.svc:7788"},
		{name: "already api host", host: "api.sandbox-manager.sandbox-system.svc:7788", expect: "api.sandbox-manager.sandbox-system.svc:7788"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.expect, managerAPIAuthority(tt.host))
		})
	}
}

func TestConnectClient_TimeoutConfiguration(t *testing.T) {
	client, err := NewConnectClient("http://example.com", "key", nil)
	require.NoError(t, err)
	assert.Zero(t, client.httpClient.Timeout)

	injected := &http.Client{Timeout: time.Second}
	client, err = NewConnectClient("http://example.com", "key", injected)
	require.NoError(t, err)
	assert.Same(t, injected, client.httpClient)
}

func TestConnectClient_TransportError(t *testing.T) {
	client, err := NewConnectClient("http://127.0.0.1:1", "key", nil)
	require.NoError(t, err)

	status, err := client.Connect(context.Background(), "sandbox", 1)

	assert.Zero(t, status)
	assert.Error(t, err)
}

func TestNewConnectClient_InvalidBaseURL(t *testing.T) {
	tests := []struct {
		name    string
		baseURL string
	}{
		{name: "missing host", baseURL: "http://"},
		{name: "relative", baseURL: "/manager"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			_, err := NewConnectClient(tt.baseURL, "key", nil)
			assert.Error(t, err)
		})
	}
}
