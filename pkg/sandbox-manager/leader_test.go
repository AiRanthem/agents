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
	"testing"

	"github.com/openkruise/agents/pkg/sandbox-manager/config"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestPrimaryState(t *testing.T) {
	tests := []struct {
		name          string
		configure     func(*primaryState)
		state         *primaryState
		expectPrimary bool
	}{
		{
			name:          "nil state is primary",
			state:         nil,
			expectPrimary: true,
		},
		{
			name:          "zero state is not primary",
			state:         &primaryState{},
			expectPrimary: false,
		},
		{
			name:  "set true marks primary",
			state: &primaryState{},
			configure: func(state *primaryState) {
				state.set(true)
			},
			expectPrimary: true,
		},
		{
			name:  "set false marks not primary",
			state: &primaryState{},
			configure: func(state *primaryState) {
				state.set(true)
				state.set(false)
			},
			expectPrimary: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if tt.configure != nil {
				tt.configure(tt.state)
			}

			assert.Equal(t, tt.expectPrimary, tt.state.IsPrimary())
		})
	}
}

func TestSandboxManagerIsPrimaryDefaults(t *testing.T) {
	tests := []struct {
		name          string
		manager       *SandboxManager
		expectPrimary bool
	}{
		{
			name:          "nil manager is primary",
			manager:       nil,
			expectPrimary: true,
		},
		{
			name:          "nil primary state is primary",
			manager:       &SandboxManager{},
			expectPrimary: true,
		},
		{
			name:          "nil elector is primary for tests",
			manager:       &SandboxManager{primary: &primaryState{}},
			expectPrimary: true,
		},
		{
			name:          "elector manager follows explicit state",
			manager:       &SandboxManager{primary: &primaryState{}, elector: &primaryElector{}},
			expectPrimary: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.expectPrimary, tt.manager.IsPrimary())
		})
	}
}

func TestNewSandboxManagerBuilderNilRestConfigPrimaryBehavior(t *testing.T) {
	builder := NewSandboxManagerBuilder(config.SandboxManagerOptions{})

	require.NotNil(t, builder.instance)
	require.NotNil(t, builder.instance.primary)
	assert.Nil(t, builder.opts.RestConfig)
	assert.Nil(t, builder.instance.elector)
	assert.False(t, builder.instance.primary.IsPrimary())
	assert.True(t, builder.instance.IsPrimary())
}
