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
	"errors"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
)

func TestBreaker(t *testing.T) {
	t.Run("opens after consecutive failures and closes after successful probe", func(t *testing.T) {
		clk := &breakerTestClock{t: time.Unix(0, 0)}
		backend := &breakerTestBackend{acquireErr: errors.New("dial tcp")}
		b := NewBreakerBackend(backend, 3, 30*time.Second)
		b.now = clk.now

		ctx := context.Background()
		for i := 0; i < 3; i++ {
			require.ErrorIs(t, b.Acquire(ctx, AcquireParams{APIKeyID: "K", LockString: "l"}), ErrBackendUnavailable)
		}
		require.Equal(t, 3, backend.acquireCalls)

		require.ErrorIs(t, b.Acquire(ctx, AcquireParams{APIKeyID: "K", LockString: "l2"}), ErrBackendUnavailable)
		require.Equal(t, 3, backend.acquireCalls, "open breaker must not touch inner")

		clk.t = clk.t.Add(31 * time.Second)
		require.ErrorIs(t, b.Acquire(ctx, AcquireParams{APIKeyID: "K", LockString: "l3"}), ErrBackendUnavailable)
		require.Equal(t, 4, backend.acquireCalls)

		backend.acquireErr = nil
		clk.t = clk.t.Add(31 * time.Second)
		require.NoError(t, b.Acquire(ctx, AcquireParams{APIKeyID: "K", LockString: "l4"}))
		require.Equal(t, 5, backend.acquireCalls)
		require.NoError(t, b.Acquire(ctx, AcquireParams{APIKeyID: "K", LockString: "l5"}))
		require.Equal(t, 6, backend.acquireCalls)
	})

	t.Run("quota exceeded does not trip breaker", func(t *testing.T) {
		clk := &breakerTestClock{t: time.Unix(0, 0)}
		backend := &breakerTestBackend{acquireErr: ErrQuotaExceeded}
		b := NewBreakerBackend(backend, 3, 30*time.Second)
		b.now = clk.now

		ctx := context.Background()
		for i := 0; i < 4; i++ {
			require.ErrorIs(t, b.Acquire(ctx, AcquireParams{APIKeyID: "K", LockString: "l"}), ErrQuotaExceeded)
		}
		require.Equal(t, 4, backend.acquireCalls)
		clk.t = clk.t.Add(time.Hour)
		require.ErrorIs(t, b.Acquire(ctx, AcquireParams{APIKeyID: "K", LockString: "l2"}), ErrQuotaExceeded)
		require.Equal(t, 5, backend.acquireCalls)
	})

	t.Run("defaults are applied when configured values are non-positive", func(t *testing.T) {
		backend := &breakerTestBackend{}
		b := NewBreakerBackend(backend, 0, 0)
		require.Equal(t, 3, b.n)
		require.Equal(t, 30*time.Second, b.d)
	})

	t.Run("other backend methods short-circuit while breaker is open", func(t *testing.T) {
		clk := &breakerTestClock{t: time.Unix(0, 0)}
		backend := &breakerTestBackend{
			releaseErr:     errors.New("dial tcp"),
			listEntriesErr: errors.New("dial tcp"),
			cleanupErr:     errors.New("dial tcp"),
		}
		b := NewBreakerBackend(backend, 1, 30*time.Second)
		b.now = clk.now

		ctx := context.Background()
		require.ErrorIs(t, b.Release(ctx, "K", "l1"), ErrBackendUnavailable)
		require.Equal(t, 1, backend.releaseCalls)
		require.ErrorIs(t, b.Release(ctx, "K", "l2"), ErrBackendUnavailable)
		require.Equal(t, 1, backend.releaseCalls)

		clk.t = clk.t.Add(31 * time.Second)
		backend.listEntries = map[string]Entry{"l1": {}}
		backend.listEntriesErr = nil
		entries, err := b.ListEntries(ctx, "K")
		require.NoError(t, err)
		require.Equal(t, backend.listEntries, entries)
		require.Equal(t, 1, backend.listEntriesCalls)

		backend.cleanupErr = errors.New("dial tcp")
		require.ErrorIs(t, b.Cleanup(ctx, "K"), ErrBackendUnavailable)
		require.Equal(t, 1, backend.cleanupCalls)
		require.ErrorIs(t, b.Cleanup(ctx, "K"), ErrBackendUnavailable)
		require.Equal(t, 1, backend.cleanupCalls)
	})
}

type breakerTestClock struct {
	t time.Time
}

func (c *breakerTestClock) now() time.Time {
	return c.t
}

type breakerTestBackend struct {
	acquireErr     error
	releaseErr     error
	listEntries    map[string]Entry
	listEntriesErr error
	cleanupErr     error

	acquireCalls     int
	releaseCalls     int
	listEntriesCalls int
	cleanupCalls     int
}

func (b *breakerTestBackend) Acquire(context.Context, AcquireParams) error {
	b.acquireCalls++
	return b.acquireErr
}

func (b *breakerTestBackend) Release(context.Context, string, string) error {
	b.releaseCalls++
	return b.releaseErr
}

func (b *breakerTestBackend) ListEntries(context.Context, string) (map[string]Entry, error) {
	b.listEntriesCalls++
	return b.listEntries, b.listEntriesErr
}

func (b *breakerTestBackend) Cleanup(context.Context, string) error {
	b.cleanupCalls++
	return b.cleanupErr
}
