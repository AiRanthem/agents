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

package sandbox_manager

import (
	"errors"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"

	agentsv1alpha1 "github.com/openkruise/agents/api/v1alpha1"
	"github.com/openkruise/agents/pkg/sandbox-manager/infra"
	"github.com/openkruise/agents/pkg/sandbox-manager/infra/sandboxcr"
	"github.com/openkruise/agents/pkg/sandboxid"
)

func TestDecoratePreModifier(t *testing.T) {
	tests := []struct {
		name           string
		labels         map[string]string
		modifier       func(infra.Sandbox) error
		expectError    string
		expectReserved bool
	}{
		{name: "nil modifier stays nil"},
		{
			name: "unrelated mutation succeeds",
			modifier: func(sandbox infra.Sandbox) error {
				sandbox.SetAnnotations(map[string]string{"example": "value"})
				return nil
			},
		},
		{
			name: "reserved addition is rejected",
			modifier: func(sandbox infra.Sandbox) error {
				sandbox.SetLabels(map[string]string{sandboxid.LabelKey: "spoofed"})
				return nil
			},
			expectError:    "reserved sandbox ID label was mutated",
			expectReserved: true,
		},
		{
			name:   "reserved deletion is rejected",
			labels: map[string]string{sandboxid.LabelKey: "existing"},
			modifier: func(sandbox infra.Sandbox) error {
				delete(sandbox.GetLabels(), sandboxid.LabelKey)
				return nil
			},
			expectError:    "reserved sandbox ID label was mutated",
			expectReserved: true,
		},
		{
			name:   "reserved value change is rejected",
			labels: map[string]string{sandboxid.LabelKey: "existing"},
			modifier: func(sandbox infra.Sandbox) error {
				sandbox.GetLabels()[sandboxid.LabelKey] = "changed"
				return nil
			},
			expectError:    "reserved sandbox ID label was mutated",
			expectReserved: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			modifier := decoratePreModifier(tt.modifier)
			if tt.modifier == nil {
				assert.Nil(t, modifier)
				return
			}
			sandbox := sandboxcr.AsSandbox(&agentsv1alpha1.Sandbox{ObjectMeta: metav1.ObjectMeta{Labels: tt.labels}}, nil)
			err := modifier(sandbox)
			if tt.expectError == "" {
				require.NoError(t, err)
				return
			}
			require.Error(t, err)
			assert.Contains(t, err.Error(), tt.expectError)
			assert.Equal(t, tt.expectReserved, errors.Is(err, ErrReservedSandboxIDMutation))
		})
	}
}

func TestDecoratePostModifier(t *testing.T) {
	callerErr := errors.New("caller failed")
	tests := []struct {
		name             string
		enableAssignment bool
		prefix           string
		uid              types.UID
		labels           map[string]string
		modifier         func(metav1.Object) (bool, error)
		expectNil        bool
		expectChanged    bool
		expectID         string
		expectError      string
		expectReserved   bool
		expectAnnotation string
	}{
		{name: "disabled without caller stays nil", expectNil: true},
		{
			name: "disabled caller mutation is preserved",
			modifier: func(object metav1.Object) (bool, error) {
				object.SetAnnotations(map[string]string{"example": "value"})
				return true, nil
			},
			expectChanged: true,
		},
		{
			name: "caller cannot add reserved label",
			modifier: func(object metav1.Object) (bool, error) {
				object.SetLabels(map[string]string{sandboxid.LabelKey: "spoofed"})
				return true, nil
			},
			expectError:    "reserved sandbox ID label was mutated",
			expectReserved: true,
		},
		{
			name:   "caller cannot delete existing empty entry",
			labels: map[string]string{sandboxid.LabelKey: ""},
			modifier: func(object metav1.Object) (bool, error) {
				delete(object.GetLabels(), sandboxid.LabelKey)
				return true, nil
			},
			expectError:    "reserved sandbox ID label was mutated",
			expectReserved: true,
		},
		{
			name:   "caller cannot change existing value",
			labels: map[string]string{sandboxid.LabelKey: "existing"},
			modifier: func(object metav1.Object) (bool, error) {
				object.GetLabels()[sandboxid.LabelKey] = "changed"
				return true, nil
			},
			expectError:    "reserved sandbox ID label was mutated",
			expectReserved: true,
		},
		{
			name:             "caller runs before core assignment",
			enableAssignment: true,
			uid:              types.UID("00000000-0000-0000-0000-000000000001"),
			modifier: func(object metav1.Object) (bool, error) {
				if _, present := object.GetLabels()[sandboxid.LabelKey]; present {
					return false, errors.New("core assignment ran before caller")
				}
				object.SetAnnotations(map[string]string{"order": "caller-first"})
				return true, nil
			},
			expectChanged:    true,
			expectID:         "aaaaaaaaaaaaaaaaaaaaaaaaae",
			expectAnnotation: "caller-first",
		},
		{
			name:             "enabled assignment prepends configured prefix",
			enableAssignment: true,
			prefix:           "prod-",
			uid:              types.UID("00000000-0000-0000-0000-000000000001"),
			expectChanged:    true,
			expectID:         "prod-aaaaaaaaaaaaaaaaaaaaaaaaae",
		},
		{
			name:             "enabled assignment preserves existing ID",
			enableAssignment: true,
			uid:              types.UID("invalid"),
			labels:           map[string]string{sandboxid.LabelKey: "existing"},
			expectID:         "existing",
		},
		{
			name:             "caller failure stops assignment",
			enableAssignment: true,
			uid:              types.UID("00000000-0000-0000-0000-000000000001"),
			modifier: func(metav1.Object) (bool, error) {
				return false, callerErr
			},
			expectError: "caller failed",
		},
		{
			name:             "invalid UID fails assignment",
			enableAssignment: true,
			uid:              types.UID("invalid"),
			expectError:      "invalid sandbox UID",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			object := &metav1.ObjectMeta{UID: tt.uid, Labels: tt.labels}
			modifier := decoratePostModifier(tt.modifier, tt.enableAssignment, tt.prefix)
			if tt.expectNil {
				assert.Nil(t, modifier)
				return
			}
			require.NotNil(t, modifier)

			changed, err := modifier(object)
			if tt.expectError != "" {
				require.Error(t, err)
				assert.Contains(t, err.Error(), tt.expectError)
				assert.Equal(t, tt.expectReserved, errors.Is(err, ErrReservedSandboxIDMutation))
				assert.False(t, changed)
				return
			}

			require.NoError(t, err)
			assert.Equal(t, tt.expectChanged, changed)
			assert.Equal(t, tt.expectID, object.GetLabels()[sandboxid.LabelKey])
			assert.Equal(t, tt.expectAnnotation, object.GetAnnotations()["order"])
		})
	}
}
