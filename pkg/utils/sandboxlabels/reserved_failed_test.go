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

package sandboxlabels

import (
	"testing"

	"github.com/stretchr/testify/assert"

	agentsv1alpha1 "github.com/openkruise/agents/api/v1alpha1"
)

func TestIsReservedFailedSandbox(t *testing.T) {
	tests := []struct {
		name   string
		labels map[string]string
		expect bool
	}{
		{
			name:   "nil labels",
			labels: nil,
			expect: false,
		},
		{
			name:   "missing label",
			labels: map[string]string{},
			expect: false,
		},
		{
			name: "reserved failed true",
			labels: map[string]string{
				agentsv1alpha1.LabelSandboxReservedFailed: agentsv1alpha1.True,
			},
			expect: true,
		},
		{
			name: "reserved failed false",
			labels: map[string]string{
				agentsv1alpha1.LabelSandboxReservedFailed: agentsv1alpha1.False,
			},
			expect: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.expect, IsReservedFailedSandbox(tt.labels))
		})
	}
}
