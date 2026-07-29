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

package proxy

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/prometheus/client_golang/prometheus/testutil"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/health/grpc_health_v1"
	"google.golang.org/grpc/status"
	"k8s.io/apimachinery/pkg/types"

	"github.com/openkruise/agents/api/v1alpha1"
	"github.com/openkruise/agents/pkg/sandbox-manager/config"
	"github.com/openkruise/agents/pkg/sandboxroute"
	"github.com/openkruise/agents/pkg/sandboxroute/refresh"
)

func TestHealthServer_Check(t *testing.T) {
	hs := &healthServer{}
	resp, err := hs.Check(context.Background(), &grpc_health_v1.HealthCheckRequest{})
	require.NoError(t, err)
	assert.Equal(t, grpc_health_v1.HealthCheckResponse_SERVING, resp.Status)
}

func TestHealthServer_List(t *testing.T) {
	hs := &healthServer{}
	resp, err := hs.List(context.Background(), &grpc_health_v1.HealthListRequest{})
	require.NoError(t, err)
	require.Contains(t, resp.Statuses, "envoy-ext-proc")
	assert.Equal(t, grpc_health_v1.HealthCheckResponse_SERVING, resp.Statuses["envoy-ext-proc"].Status)
}

func TestHealthServer_Watch(t *testing.T) {
	hs := &healthServer{}
	err := hs.Watch(&grpc_health_v1.HealthCheckRequest{}, nil)
	require.Error(t, err)
	st, ok := status.FromError(err)
	require.True(t, ok)
	assert.Equal(t, codes.Unimplemented, st.Code())
}

func TestNewServeMuxRefreshWritesStoreAndUpdatesRouteCount(t *testing.T) {
	server := NewServer(config.SandboxManagerOptions{})
	routeCount.Set(0)
	route := sandboxroute.Route{
		ID:              "short-a",
		Namespace:       "ns",
		Name:            "a",
		UID:             types.UID("uid-a"),
		ResourceVersion: "1",
		State:           v1alpha1.SandboxStatePaused,
		IP:              "10.0.0.1",
	}
	body, err := json.Marshal(route)
	require.NoError(t, err)

	request := httptest.NewRequest(http.MethodPost, refresh.Path, bytes.NewReader(body))
	response := httptest.NewRecorder()
	server.newServeMux().ServeHTTP(response, request)

	assert.Equal(t, http.StatusNoContent, response.Code)
	stored, present := server.LoadRoute(route.ID)
	require.True(t, present)
	assert.Equal(t, route, stored)
	assert.Equal(t, float64(1), testutil.ToFloat64(routeCount))
}

func TestNewServeMuxInvalidRefreshDoesNotUpdateRouteCount(t *testing.T) {
	server := NewServer(config.SandboxManagerOptions{})
	routeCount.Set(7)
	route := sandboxroute.Route{
		ID:              "short-a",
		Namespace:       "ns",
		UID:             types.UID("uid-a"),
		ResourceVersion: "1",
		State:           v1alpha1.SandboxStateRunning,
	}
	body, err := json.Marshal(route)
	require.NoError(t, err)

	request := httptest.NewRequest(http.MethodPost, refresh.Path, bytes.NewReader(body))
	response := httptest.NewRecorder()
	server.newServeMux().ServeHTTP(response, request)

	assert.Equal(t, http.StatusBadRequest, response.Code)
	assert.Equal(t, float64(7), testutil.ToFloat64(routeCount))
}
