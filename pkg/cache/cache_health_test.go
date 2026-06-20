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

package cache

import (
	"errors"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/openkruise/agents/pkg/cache/controllers"
)

func TestCache_RemoveSafeHealth(t *testing.T) {
	c, health := newHealthCacheForTest(t)

	tests := []struct {
		name       string
		setup      func()
		expectSafe bool
	}{
		{
			name:       "unsynced cache is not remove safe",
			expectSafe: false,
		},
		{
			name: "synced cache is remove safe",
			setup: func() {
				health.MarkSynced()
			},
			expectSafe: true,
		},
		{
			name: "recent watch error is not remove safe",
			setup: func() {
				health.MarkSynced()
				health.RecordWatchError(nil, errors.New("watch failed"))
			},
			expectSafe: false,
		},
		{
			name: "old watch error is remove safe",
			setup: func() {
				health.MarkSynced()
				health.RecordWatchError(nil, errors.New("watch failed"))
				health.lastWatchError.Store(time.Now().Add(-time.Hour).UnixNano())
			},
			expectSafe: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c, health = newHealthCacheForTest(t)
			if tt.setup != nil {
				tt.setup()
			}
			assert.Equal(t, tt.expectSafe, c.RemoveSafe())
		})
	}
}

func TestCache_RemoveSafeWaitsForSandboxEventHandlerSync(t *testing.T) {
	tests := []struct {
		name       string
		synced     bool
		expectSafe bool
	}{
		{
			name:       "registered unsynced handler is not remove safe",
			expectSafe: false,
		},
		{
			name:       "registered synced handler is remove safe",
			synced:     true,
			expectSafe: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c, health := newHealthCacheForTest(t)
			health.MarkSynced()

			reg := &fakeSandboxEventRegistration{synced: tt.synced}
			c.sandboxEventRegistrationMu.Lock()
			c.sandboxEventRegistration = reg
			c.sandboxEventRegistrationMu.Unlock()

			assert.Equal(t, tt.expectSafe, c.RemoveSafe())
		})
	}
}

type fakeSandboxEventRegistration struct {
	synced bool
}

func (r *fakeSandboxEventRegistration) HasSynced() bool {
	return r.synced
}

func (r *fakeSandboxEventRegistration) Remove() error {
	return nil
}

func newHealthCacheForTest(t *testing.T) (*Cache, *InformerHealth) {
	t.Helper()
	mgrBuilder, err := controllers.NewMockManagerBuilder(t)
	require.NoError(t, err)

	health := NewInformerHealth()
	c, err := NewCacheWithHealth(mgrBuilder.Build(), health)
	require.NoError(t, err)
	return c, health
}
