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
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestValidateE2BTimeoutFlags(t *testing.T) {
	cases := []struct {
		name        string
		maxTimeout  int
		expectError string
	}{
		{name: "ok-default", maxTimeout: 2592000, expectError: ""},
		{name: "ok-small", maxTimeout: 60, expectError: ""},
		{name: "zero", maxTimeout: 0, expectError: "--e2b-max-timeout must be greater than 0"},
		{name: "negative", maxTimeout: -1, expectError: "--e2b-max-timeout must be greater than 0"},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			err := validateE2BTimeoutFlags(tc.maxTimeout)
			if tc.expectError == "" {
				require.NoError(t, err)
			} else {
				require.Error(t, err)
				assert.Contains(t, err.Error(), tc.expectError)
			}
		})
	}
}

func TestValidateMetricsPort(t *testing.T) {
	cases := []struct {
		name               string
		metricsPort        int
		adminPort          int
		memberlistBindPort int
		expectError        string
	}{
		{name: "unset-uses-admin", adminPort: 8081, memberlistBindPort: 7946},
		{name: "equal-admin", metricsPort: 8081, adminPort: 8081, memberlistBindPort: 7946},
		{name: "differs-from-admin", metricsPort: 9090, adminPort: 8081, memberlistBindPort: 7946, expectError: "must equal --admin-port"},
		{name: "negative", metricsPort: -1, adminPort: 8081, memberlistBindPort: 7946, expectError: "valid TCP port"},
		{name: "too-large", metricsPort: 65536, adminPort: 8081, memberlistBindPort: 7946, expectError: "valid TCP port"},
		{name: "matches-memberlist", metricsPort: 7946, adminPort: 7946, memberlistBindPort: 7946, expectError: "must differ from --memberlist-bind-port"},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			err := validateMetricsPort(tc.metricsPort, tc.adminPort, tc.memberlistBindPort)
			if tc.expectError == "" {
				require.NoError(t, err)
				return
			}
			require.Error(t, err)
			assert.Contains(t, err.Error(), tc.expectError)
		})
	}
}
