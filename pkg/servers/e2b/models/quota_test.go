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

package models

import (
	"encoding/json"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestNormalizeQuotaSpec(t *testing.T) {
	count := func(value int64) *int64 {
		return &value
	}

	tests := []struct {
		name        string
		spec        *QuotaSpec
		expectLimit *int64
		expectError string
	}{
		{
			name: "nil quota is unlimited",
		},
		{
			name: "empty quota is unlimited",
			spec: &QuotaSpec{},
		},
		{
			name: "nil sandbox count is unlimited",
			spec: &QuotaSpec{
				Limits: []QuotaLimit{
					{
						Dimension: DimSandboxCount,
					},
				},
			},
		},
		{
			name: "duplicate nil sandbox count limits are dropped",
			spec: &QuotaSpec{
				Limits: []QuotaLimit{
					{
						Dimension: DimSandboxCount,
					},
					{
						Dimension: DimSandboxCount,
					},
				},
			},
		},
		{
			name: "zero sandbox count is hard zero",
			spec: &QuotaSpec{
				Limits: []QuotaLimit{
					{
						Dimension: DimSandboxCount,
						Limit:     count(0),
					},
				},
			},
			expectLimit: count(0),
		},
		{
			name: "positive sandbox count is limited",
			spec: &QuotaSpec{
				Limits: []QuotaLimit{
					{
						Dimension: DimSandboxCount,
						Limit:     count(7),
					},
				},
			},
			expectLimit: count(7),
		},
		{
			name: "negative sandbox count is rejected",
			spec: &QuotaSpec{
				Limits: []QuotaLimit{
					{
						Dimension: DimSandboxCount,
						Limit:     count(-1),
					},
				},
			},
			expectError: "negative",
		},
		{
			name: "duplicate sandbox count is rejected",
			spec: &QuotaSpec{
				Limits: []QuotaLimit{
					{
						Dimension: DimSandboxCount,
						Limit:     count(1),
					},
					{
						Dimension: DimSandboxCount,
						Limit:     count(2),
					},
				},
			},
			expectError: "duplicate",
		},
		{
			name: "unsupported dimension is rejected",
			spec: &QuotaSpec{
				Limits: []QuotaLimit{
					{
						Dimension: QuotaDimension("sandbox.memory"),
						Limit:     count(1),
					},
				},
			},
			expectError: "unsupported",
		},
		{
			name: "non-empty scope is rejected",
			spec: &QuotaSpec{
				Limits: []QuotaLimit{
					{
						Dimension: DimSandboxCount,
						Scope: QuotaScope{
							Template: "python",
						},
						Limit: count(1),
					},
				},
			},
			expectError: "scope",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			spec, err := NormalizeQuotaSpec(tt.spec)
			if tt.expectError != "" {
				require.Error(t, err)
				assert.Contains(t, err.Error(), tt.expectError)
				return
			}

			require.NoError(t, err)
			if tt.expectLimit == nil {
				assert.Nil(t, spec)
				return
			}

			require.NotNil(t, spec)
			require.True(t, spec.IsLimited())
			limit, ok := spec.SandboxCountLimit()
			require.True(t, ok)
			assert.Equal(t, *tt.expectLimit, limit)
		})
	}
}

func TestAPIKeyQuotaJSONToQuotaSpec(t *testing.T) {
	tests := []struct {
		name        string
		payload     string
		expectLimit *int64
		expectError string
	}{
		{
			name:    "absent quota is unlimited",
			payload: `{"name":"key"}`,
		},
		{
			name:    "null quota is unlimited",
			payload: `{"name":"key","quota":null}`,
		},
		{
			name:    "empty quota is unlimited",
			payload: `{"name":"key","quota":{}}`,
		},
		{
			name:    "null sandbox quota is unlimited",
			payload: `{"name":"key","quota":{"sandbox":null}}`,
		},
		{
			name:    "null sandbox count is unlimited",
			payload: `{"name":"key","quota":{"sandbox":{"count":null}}}`,
		},
		{
			name:        "nested sandbox count is limited",
			payload:     `{"name":"key","quota":{"sandbox":{"count":3}}}`,
			expectLimit: ptrInt64ForQuotaTest(3),
		},
		{
			name:        "nested sandbox count zero is hard zero",
			payload:     `{"name":"key","quota":{"sandbox":{"count":0}}}`,
			expectLimit: ptrInt64ForQuotaTest(0),
		},
		{
			name:        "nested sandbox count negative is rejected",
			payload:     `{"name":"key","quota":{"sandbox":{"count":-1}}}`,
			expectError: "negative",
		},
		{
			name:        "unsupported future top-level dimension is rejected",
			payload:     `{"name":"key","quota":{"cpu":{"count":1}}}`,
			expectError: "unsupported",
		},
		{
			name:        "unsupported nested sandbox field is rejected",
			payload:     `{"name":"key","quota":{"sandbox":{"memory":1024}}}`,
			expectError: "unsupported",
		},
		{
			name:        "internal limits shape is rejected",
			payload:     `{"name":"key","quota":{"limits":[{"dimension":"sandbox.count","limit":1}]}}`,
			expectError: "unsupported",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var key NewTeamAPIKey
			err := json.Unmarshal([]byte(tt.payload), &key)
			if err == nil && key.Quota != nil {
				_, err = key.Quota.ToQuotaSpec()
			}

			if tt.expectError != "" {
				require.Error(t, err)
				assert.Contains(t, err.Error(), tt.expectError)
				return
			}

			require.NoError(t, err)
			var spec *QuotaSpec
			if key.Quota != nil {
				spec, err = key.Quota.ToQuotaSpec()
				require.NoError(t, err)
			}
			if tt.expectLimit == nil {
				assert.Nil(t, spec)
				return
			}

			require.NotNil(t, spec)
			limit, ok := spec.SandboxCountLimit()
			require.True(t, ok)
			assert.Equal(t, *tt.expectLimit, limit)
		})
	}
}

func TestAPIKeyQuotaFromSpecJSON(t *testing.T) {
	tests := []struct {
		name        string
		key         CreatedTeamAPIKey
		expectCount *int64
	}{
		{
			name: "limited quota marshals nested sandbox count",
			key: CreatedTeamAPIKey{
				Name:      "key",
				Quota:     APIKeyQuotaFromSpec(&QuotaSpec{Limits: []QuotaLimit{{Dimension: DimSandboxCount, Limit: ptrInt64ForQuotaTest(5)}}}),
				QuotaSpec: &QuotaSpec{Limits: []QuotaLimit{{Dimension: DimSandboxCount, Limit: ptrInt64ForQuotaTest(5)}}},
			},
			expectCount: ptrInt64ForQuotaTest(5),
		},
		{
			name: "unlimited quota is omitted",
			key: CreatedTeamAPIKey{
				Name:      "key",
				Quota:     APIKeyQuotaFromSpec(nil),
				QuotaSpec: nil,
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			payload, err := json.Marshal(tt.key)
			require.NoError(t, err)

			jsonPayload := string(payload)
			assert.NotContains(t, jsonPayload, "limits")
			assert.NotContains(t, jsonPayload, "QuotaSpec")
			if tt.expectCount == nil {
				assert.NotContains(t, jsonPayload, `"quota"`)
				return
			}

			var decoded struct {
				Quota *APIKeyQuota `json:"quota"`
			}
			require.NoError(t, json.Unmarshal(payload, &decoded))
			require.NotNil(t, decoded.Quota)
			require.NotNil(t, decoded.Quota.Sandbox)
			require.NotNil(t, decoded.Quota.Sandbox.Count)
			assert.Equal(t, *tt.expectCount, *decoded.Quota.Sandbox.Count)
		})
	}
}

func TestAPIKeyQuotaFromSpecChecked(t *testing.T) {
	tests := []struct {
		name        string
		spec        *QuotaSpec
		expectCount *int64
		expectError string
	}{
		{
			name: "limited spec converts to public quota",
			spec: &QuotaSpec{
				Limits: []QuotaLimit{
					{
						Dimension: DimSandboxCount,
						Limit:     ptrInt64ForQuotaTest(4),
					},
				},
			},
			expectCount: ptrInt64ForQuotaTest(4),
		},
		{
			name: "unlimited spec converts to nil",
		},
		{
			name: "non-empty scope returns error from checked variant",
			spec: &QuotaSpec{
				Limits: []QuotaLimit{
					{
						Dimension: DimSandboxCount,
						Scope: QuotaScope{
							Template: "tmpl",
						},
						Limit: ptrInt64ForQuotaTest(1),
					},
				},
			},
			expectError: "scope",
		},
		{
			name: "negative limit returns error from checked variant",
			spec: &QuotaSpec{
				Limits: []QuotaLimit{
					{
						Dimension: DimSandboxCount,
						Limit:     ptrInt64ForQuotaTest(-1),
					},
				},
			},
			expectError: "negative",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			quota, err := APIKeyQuotaFromSpecChecked(tt.spec)
			uncheckedQuota := APIKeyQuotaFromSpec(tt.spec)
			if tt.expectError != "" {
				require.Error(t, err)
				assert.Contains(t, err.Error(), tt.expectError)
				assert.Nil(t, uncheckedQuota)
				return
			}

			require.NoError(t, err)
			if tt.expectCount == nil {
				assert.Nil(t, quota)
				assert.Nil(t, uncheckedQuota)
				return
			}

			require.NotNil(t, quota)
			require.NotNil(t, quota.Sandbox)
			require.NotNil(t, quota.Sandbox.Count)
			assert.Equal(t, *tt.expectCount, *quota.Sandbox.Count)
			require.NotNil(t, uncheckedQuota)
			require.NotNil(t, uncheckedQuota.Sandbox)
			require.NotNil(t, uncheckedQuota.Sandbox.Count)
			assert.Equal(t, *tt.expectCount, *uncheckedQuota.Sandbox.Count)
		})
	}
}

func TestAPIKeyQuotaDeepCopy(t *testing.T) {
	tests := []struct {
		name  string
		quota *APIKeyQuota
	}{
		{
			name: "limited quota copies count pointer value",
			quota: &APIKeyQuota{
				Sandbox: &SandboxQuota{
					Count: ptrInt64ForQuotaTest(2),
				},
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			copyQuota := tt.quota.DeepCopy()
			require.NotNil(t, copyQuota)
			require.NotNil(t, tt.quota.Sandbox)
			require.NotNil(t, copyQuota.Sandbox)
			require.NotNil(t, tt.quota.Sandbox.Count)
			require.NotNil(t, copyQuota.Sandbox.Count)

			*tt.quota.Sandbox.Count = 6
			assert.Equal(t, int64(2), *copyQuota.Sandbox.Count)

			*copyQuota.Sandbox.Count = 8
			assert.Equal(t, int64(6), *tt.quota.Sandbox.Count)
		})
	}
}

func TestQuotaSpecSandboxCountLimit(t *testing.T) {
	tests := []struct {
		name          string
		spec          *QuotaSpec
		expectLimit   int64
		expectOK      bool
		expectLimited bool
	}{
		{
			name: "empty scope sandbox count is limited",
			spec: &QuotaSpec{
				Limits: []QuotaLimit{
					{
						Dimension: DimSandboxCount,
						Limit:     ptrInt64ForQuotaTest(1),
					},
				},
			},
			expectLimit:   1,
			expectOK:      true,
			expectLimited: true,
		},
		{
			name: "non-empty scope sandbox count is ignored",
			spec: &QuotaSpec{
				Limits: []QuotaLimit{
					{
						Dimension: DimSandboxCount,
						Scope: QuotaScope{
							Template: "tmpl",
						},
						Limit: ptrInt64ForQuotaTest(1),
					},
				},
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			limit, ok := tt.spec.SandboxCountLimit()
			assert.Equal(t, tt.expectOK, ok)
			assert.Equal(t, tt.expectLimit, limit)
			assert.Equal(t, tt.expectLimited, tt.spec.IsLimited())
		})
	}
}

func TestQuotaSpecDeepCopy(t *testing.T) {
	tests := []struct {
		name string
		spec *QuotaSpec
	}{
		{
			name: "limited spec copies limit pointer value",
			spec: &QuotaSpec{
				Limits: []QuotaLimit{
					{
						Dimension: DimSandboxCount,
						Limit:     ptrInt64ForQuotaTest(3),
					},
				},
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			copySpec := tt.spec.DeepCopy()
			require.NotNil(t, copySpec)
			require.Len(t, tt.spec.Limits, 1)
			require.Len(t, copySpec.Limits, 1)
			require.NotNil(t, tt.spec.Limits[0].Limit)
			require.NotNil(t, copySpec.Limits[0].Limit)

			*tt.spec.Limits[0].Limit = 5
			assert.Equal(t, int64(3), *copySpec.Limits[0].Limit)

			*copySpec.Limits[0].Limit = 7
			assert.Equal(t, int64(5), *tt.spec.Limits[0].Limit)
		})
	}
}

func ptrInt64ForQuotaTest(value int64) *int64 {
	return &value
}
