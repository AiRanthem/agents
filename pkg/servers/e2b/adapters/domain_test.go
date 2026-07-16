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

package adapters

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

type getDomainTestCase struct {
	name        string
	authority   string
	expect      string
	expectError string
}

type getSandboxAddressTestCase struct {
	name      string
	domain    string
	sandboxID string
	port      int32
	expect    string
}

func TestE2BAdapters_GetDomain(t *testing.T) {
	nativeTests := []getDomainTestCase{
		{
			name:      "strips api prefix and preserves port",
			authority: "api.example.com:8443",
			expect:    "example.com:8443",
		},
		{
			name:      "strips api prefix without port",
			authority: "api.example.com",
			expect:    "example.com",
		},
		{
			name:      "normalizes uppercase api prefix",
			authority: "API.example.com",
			expect:    "example.com",
		},
		{
			name:      "normalizes uppercase api prefix with port",
			authority: "API.example.com:8443",
			expect:    "example.com:8443",
		},
		{
			name:      "preserves host without api prefix",
			authority: "example.com",
			expect:    "example.com",
		},
		{
			name:      "removes trailing dot",
			authority: "api.example.com.",
			expect:    "example.com",
		},
		{
			name:      "removes trailing dot and preserves port",
			authority: "api.example.com.:8443",
			expect:    "example.com:8443",
		},
		{
			name:      "preserves raw ipv6",
			authority: "2001:db8::1",
			expect:    "2001:db8::1",
		},
		{
			name:      "preserves bracketed ipv6 without port",
			authority: "[::1]",
			expect:    "[::1]",
		},
		{
			name:      "preserves bracketed ipv6 with port",
			authority: "[::1]:8443",
			expect:    "[::1]:8443",
		},
		{
			name:      "preserves localhost with port",
			authority: "localhost:7788",
			expect:    "localhost:7788",
		},
		{
			name:      "does not strip apiserver prefix",
			authority: "apiserver.example.com",
			expect:    "apiserver.example.com",
		},
		{
			name:        "empty host is rejected",
			expectError: "cannot resolve sandbox domain: empty host",
		},
		{
			name:        "api dot is rejected",
			authority:   "api.",
			expectError: "cannot resolve sandbox domain: empty host",
		},
		{
			name:        "api dot with port is rejected",
			authority:   "api.:8443",
			expectError: "cannot resolve sandbox domain: empty host",
		},
		{
			name:      "preserves ipv4",
			authority: "127.0.0.1:8443",
			expect:    "127.0.0.1:8443",
		},
		{
			name:      "preserves permissive host and port",
			authority: "api.bad_host.example.com:https",
			expect:    "bad_host.example.com:https",
		},
	}

	customizedTests := []getDomainTestCase{
		{
			name:      "preserves host",
			authority: "gateway.example.com",
			expect:    "gateway.example.com",
		},
		{
			name:      "preserves host and port",
			authority: "gateway.example.com:8443",
			expect:    "gateway.example.com:8443",
		},
		{
			name:      "preserves api prefix",
			authority: "api.gateway.example.com",
			expect:    "api.gateway.example.com",
		},
		{
			name:      "preserves case",
			authority: "Gateway.example.com",
			expect:    "Gateway.example.com",
		},
		{
			name:      "removes trailing dot",
			authority: "gateway.example.com.",
			expect:    "gateway.example.com",
		},
		{
			name:      "preserves case and port while removing trailing dot",
			authority: "Gateway.example.com.:8443",
			expect:    "Gateway.example.com:8443",
		},
		{
			name:      "preserves ipv4 with port",
			authority: "192.0.2.1:8443",
			expect:    "192.0.2.1:8443",
		},
		{
			name:      "brackets raw ipv6",
			authority: "2001:db8::1",
			expect:    "[2001:db8::1]",
		},
		{
			name:      "preserves bracketed ipv6",
			authority: "[2001:db8::1]",
			expect:    "[2001:db8::1]",
		},
		{
			name:      "accepts bracketed ipv6 with port",
			authority: "[2001:db8::1]:8443",
			expect:    "[2001:db8::1]:8443",
		},
		{
			name:        "empty host is rejected",
			expectError: "cannot resolve sandbox domain: empty host",
		},
		{
			name:        "empty host with port is rejected",
			authority:   ":8443",
			expectError: "cannot resolve sandbox domain: empty host",
		},
		{
			name:      "preserves permissive host and port",
			authority: "bad_host.example.com:https",
			expect:    "bad_host.example.com:https",
		},
	}

	tests := []struct {
		name      string
		getDomain func(string) (string, error)
		cases     []getDomainTestCase
	}{
		{
			name:      "native",
			getDomain: (&NativeE2BAdapter{}).GetDomain,
			cases:     nativeTests,
		},
		{
			name:      "customized",
			getDomain: (&CustomizedE2BAdapter{}).GetDomain,
			cases:     customizedTests,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			for _, tc := range tt.cases {
				t.Run(tc.name, func(t *testing.T) {
					got, err := tt.getDomain(tc.authority)
					if tc.expectError != "" {
						require.Error(t, err)
						assert.Contains(t, err.Error(), tc.expectError)
						return
					}
					require.NoError(t, err)
					assert.Equal(t, tc.expect, got)
				})
			}
		})
	}
}

func TestE2BAdapters_GetSandboxAddress(t *testing.T) {
	nativeTests := []getSandboxAddressTestCase{
		{
			name:      "formats resolved domain as subdomain address",
			domain:    "example.com",
			sandboxID: "sid",
			port:      9222,
			expect:    "9222-sid.example.com",
		},
		{
			name:      "preserves resolved domain as-is",
			domain:    "API.Static.example.com.",
			sandboxID: "sid",
			port:      9222,
			expect:    "9222-sid.API.Static.example.com.",
		},
	}

	customizedTests := []getSandboxAddressTestCase{
		{
			name:      "formats resolved domain as path address",
			domain:    "gateway.example.com",
			sandboxID: "sid",
			port:      9222,
			expect:    "gateway.example.com/kruise/sid/9222",
		},
		{
			name:      "preserves resolved domain as-is",
			domain:    "Gateway.example.com.",
			sandboxID: "sid",
			port:      9222,
			expect:    "Gateway.example.com./kruise/sid/9222",
		},
	}

	tests := []struct {
		name              string
		getSandboxAddress func(string, string, int32) string
		cases             []getSandboxAddressTestCase
	}{
		{
			name:              "native",
			getSandboxAddress: (&NativeE2BAdapter{}).GetSandboxAddress,
			cases:             nativeTests,
		},
		{
			name:              "customized",
			getSandboxAddress: (&CustomizedE2BAdapter{}).GetSandboxAddress,
			cases:             customizedTests,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			for _, tc := range tt.cases {
				t.Run(tc.name, func(t *testing.T) {
					got := tt.getSandboxAddress(tc.domain, tc.sandboxID, tc.port)
					assert.Equal(t, tc.expect, got)
				})
			}
		})
	}
}

func TestE2BAdapter_DomainDispatch(t *testing.T) {
	tests := []struct {
		name          string
		authority     string
		path          string
		expectDomain  string
		expectAddress string
	}{
		{
			name:          "native path selects native domain and address",
			authority:     "API.example.com.",
			path:          "/sandboxes/sid/connect",
			expectDomain:  "example.com",
			expectAddress: "9222-sid.example.com",
		},
		{
			name:          "customized path selects customized domain and address",
			authority:     "API.example.com.",
			path:          "/kruise/api/sandboxes/sid/connect",
			expectDomain:  "API.example.com",
			expectAddress: "API.example.com/kruise/sid/9222",
		},
	}

	adapter := NewE2BAdapter(8080)
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			domain, err := adapter.GetDomain(tt.authority, tt.path)
			require.NoError(t, err)
			assert.Equal(t, tt.expectDomain, domain)
			assert.Equal(t, tt.expectAddress, adapter.GetSandboxAddress(domain, tt.path, "sid", 9222))
		})
	}
}
