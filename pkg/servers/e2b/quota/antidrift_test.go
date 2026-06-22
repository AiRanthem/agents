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

package quota

import (
	"context"
	"sync/atomic"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

type stubPrimary struct {
	primary bool
}

func (p stubPrimary) IsPrimary() bool {
	return p.primary
}

type stubBackend struct {
	releaseCalls atomic.Int64
}

func (b *stubBackend) Acquire(context.Context, AcquireParams) error {
	return nil
}

func (b *stubBackend) Release(context.Context, string, string) error {
	b.releaseCalls.Add(1)
	return nil
}

func (b *stubBackend) ListEntries(context.Context, string) (map[string]Entry, error) {
	return map[string]Entry{}, nil
}

func (b *stubBackend) Cleanup(context.Context, string) error {
	return nil
}

type stubRegistration struct {
	removed atomic.Bool
}

func (r *stubRegistration) HasSynced() bool {
	return true
}

func (r *stubRegistration) Remove() error {
	r.removed.Store(true)
	return nil
}

func TestAntiDriftRunOnceStubReturnsNil(t *testing.T) {
	tests := []struct {
		name    string
		primary bool
	}{
		{name: "primary", primary: true},
		{name: "not primary", primary: false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			driver := NewAntiDriftDriver(
				AntiDriftConfig{Interval: time.Hour, Grace: time.Minute},
				stubPrimary{primary: tt.primary},
				nil,
				nil,
				&stubBackend{},
			)
			require.NoError(t, driver.RunOnce(context.Background()))
		})
	}
}

func TestAntiDriftSandboxEventHandlerIsNoopInStub(t *testing.T) {
	backend := &stubBackend{}
	driver := NewAntiDriftDriver(
		AntiDriftConfig{Interval: time.Hour, Grace: time.Minute},
		stubPrimary{primary: true},
		nil,
		nil,
		backend,
	)

	handler := driver.SandboxEventHandler()
	handler.OnDelete(struct{}{})
	handler.OnUpdate(struct{}{}, struct{}{})

	assert.Zero(t, backend.releaseCalls.Load())
}

func TestAntiDriftRunStartsNonBlockingAndStopRemovesRegistration(t *testing.T) {
	registration := &stubRegistration{}
	driver := NewAntiDriftDriver(
		AntiDriftConfig{Interval: time.Hour, Grace: time.Minute},
		stubPrimary{primary: true},
		nil,
		nil,
		&stubBackend{},
	)
	driver.SetEventRegistration(registration)

	ctx, cancel := context.WithCancel(context.Background())
	t.Cleanup(cancel)

	returned := make(chan struct{})
	go func() {
		driver.Run(ctx)
		close(returned)
	}()

	select {
	case <-returned:
	case <-time.After(100 * time.Millisecond):
		t.Fatal("Run must return without waiting for the loop")
	}

	cancel()
	driver.Stop()
	assert.True(t, registration.removed.Load())
}

func TestAntiDriftSetEventRegistrationAfterStopRemovesRegistration(t *testing.T) {
	driver := NewAntiDriftDriver(
		AntiDriftConfig{Interval: time.Hour, Grace: time.Minute},
		stubPrimary{primary: true},
		nil,
		nil,
		&stubBackend{},
	)
	registration := &stubRegistration{}

	driver.Stop()
	driver.SetEventRegistration(registration)
	driver.Stop()
	assert.True(t, registration.removed.Load())
}
