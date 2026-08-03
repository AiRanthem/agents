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

package sandboxid

import (
	"maps"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"

	agentsv1alpha1 "github.com/openkruise/agents/api/v1alpha1"
)

func TestResolve(t *testing.T) {
	tests := []struct {
		name     string
		labels   map[string]string
		expected string
	}{
		{name: "non-empty label is authoritative", labels: map[string]string{LabelKey: "operator-assigned-value"}, expected: "operator-assigned-value"},
		{name: "absent label uses legacy ID", labels: map[string]string{"app": "sandbox"}, expected: "team-a--sandbox-a"},
		{name: "empty label uses legacy ID", labels: map[string]string{LabelKey: ""}, expected: "team-a--sandbox-a"},
		{name: "nil labels use legacy ID", labels: nil, expected: "team-a--sandbox-a"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			sandbox := &agentsv1alpha1.Sandbox{ObjectMeta: metav1.ObjectMeta{
				Namespace: "team-a",
				Name:      "sandbox-a",
				Labels:    tt.labels,
			}}
			assert.Equal(t, tt.expected, Resolve(sandbox))
		})
	}
}

func TestLegacy(t *testing.T) {
	tests := []struct {
		name      string
		namespace string
		sandbox   string
		expected  string
	}{
		{name: "standard names", namespace: "team-a", sandbox: "sandbox-a", expected: "team-a--sandbox-a"},
		{name: "name contains separator", namespace: "team-a", sandbox: "sandbox--a", expected: "team-a--sandbox--a"},
		{name: "empty namespace preserves encoding", namespace: "", sandbox: "sandbox-a", expected: "--sandbox-a"},
		{name: "empty name preserves encoding", namespace: "team-a", sandbox: "", expected: "team-a--"},
	}

	assert.Equal(t, agentsv1alpha1.LabelSandboxID, LabelKey)

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.expected, Legacy(tt.namespace, tt.sandbox))
		})
	}
}

func TestGenerateShort(t *testing.T) {
	tests := []struct {
		name        string
		uid         types.UID
		expected    string
		expectError string
	}{
		{name: "zero UUID encodes all bits deterministically", uid: types.UID("00000000-0000-0000-0000-000000000000"), expected: strings.Repeat("a", 26)},
		{name: "different UUID changes the encoded value", uid: types.UID("00000000-0000-0000-0000-000000000001"), expected: strings.Repeat("a", 25) + "e"},
		{name: "invalid UUID is rejected", uid: types.UID("not-a-uuid"), expectError: "invalid sandbox UID"},
		{name: "empty UUID is rejected", uid: types.UID(""), expectError: "invalid sandbox UID"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			actual, err := GenerateShort(tt.uid)
			if tt.expectError != "" {
				require.Error(t, err)
				assert.Contains(t, err.Error(), tt.expectError)
				assert.Empty(t, actual)
				return
			}
			require.NoError(t, err)
			assert.Equal(t, tt.expected, actual)
			assert.Len(t, actual, ShortIDLength)
			assert.Regexp(t, `^[a-z2-7]{26}$`, actual)
		})
	}
}

func TestValidatePrefix(t *testing.T) {
	tests := []struct {
		name        string
		prefix      string
		expectError string
	}{
		{name: "empty prefix"},
		{name: "lowercase prefix", prefix: "prod-"},
		{name: "numeric prefix", prefix: "42-"},
		{name: "long prefix is accepted", prefix: strings.Repeat("a", 128)},
		{name: "uppercase is rejected", prefix: "Prod-", expectError: "invalid"},
		{name: "underscore is rejected", prefix: "prod_", expectError: "invalid"},
		{name: "leading hyphen is rejected", prefix: "-prod", expectError: "invalid"},
		{name: "legacy separator is rejected", prefix: "prod--x", expectError: "legacy ID separator"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := ValidatePrefix(tt.prefix)
			if tt.expectError == "" {
				require.NoError(t, err)
				return
			}
			require.Error(t, err)
			assert.Contains(t, err.Error(), tt.expectError)
		})
	}
}

func TestAssignShort(t *testing.T) {
	tests := []struct {
		name          string
		uid           types.UID
		labels        map[string]string
		prefix        string
		expectChanged bool
		expectedID    string
		expectError   string
	}{
		{name: "missing label is assigned", uid: types.UID("00000000-0000-0000-0000-000000000000"), expectChanged: true, expectedID: strings.Repeat("a", 26)},
		{name: "prefix is prepended and other labels are preserved", uid: types.UID("00000000-0000-0000-0000-000000000001"), labels: map[string]string{LabelKey: "", "app": "sandbox"}, prefix: "prod-", expectChanged: true, expectedID: "prod-" + strings.Repeat("a", 25) + "e"},
		{name: "non-empty label is preserved without UID or prefix validation", uid: types.UID("not-a-uuid"), labels: map[string]string{LabelKey: "operator-assigned-value"}, prefix: "INVALID_", expectedID: "operator-assigned-value"},
		{name: "assignment trusts caller prefix", uid: types.UID("00000000-0000-0000-0000-000000000001"), labels: map[string]string{"app": "sandbox"}, prefix: "INVALID_", expectChanged: true, expectedID: "INVALID_" + strings.Repeat("a", 25) + "e"},
		{name: "invalid UID leaves labels unchanged", uid: types.UID("not-a-uuid"), labels: map[string]string{"app": "sandbox"}, expectError: "invalid sandbox UID"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			initialLabels := maps.Clone(tt.labels)
			sandbox := &agentsv1alpha1.Sandbox{ObjectMeta: metav1.ObjectMeta{
				Namespace: "team-a",
				Name:      "sandbox-a",
				UID:       tt.uid,
				Labels:    maps.Clone(tt.labels),
			}}

			changed, err := AssignShort(sandbox, tt.prefix)
			if tt.expectError != "" {
				require.Error(t, err)
				assert.Contains(t, err.Error(), tt.expectError)
				assert.False(t, changed)
				assert.Equal(t, initialLabels, sandbox.Labels)
				return
			}

			require.NoError(t, err)
			assert.Equal(t, tt.expectChanged, changed)
			assert.Equal(t, tt.expectedID, Resolve(sandbox))
			if initialLabels["app"] != "" {
				assert.Equal(t, initialLabels["app"], sandbox.Labels["app"])
			}

			changed, err = AssignShort(sandbox, tt.prefix)
			require.NoError(t, err)
			assert.False(t, changed)
		})
	}
}
