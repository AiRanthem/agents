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
	"strconv"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/prometheus/client_golang/prometheus/testutil"
	"github.com/redis/go-redis/v9"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/openkruise/agents/pkg/servers/e2b/models"
)

func TestAcquireUpsert(t *testing.T) {
	tests := []struct {
		name        string
		seed        []AcquireParams
		op          AcquireParams
		wantSum     map[string]map[string]int64
		expectError string
	}{
		{
			name: "first create charges count all and running",
			op: AcquireParams{
				APIKeyID:   "K",
				LockString: "l1",
				Scopes:     []models.QuotaScope{models.ScopeRunning},
				Enforce:    true,
				Limits: map[models.QuotaDimension]map[models.QuotaScope]int64{
					models.DimSandboxCount: {models.ScopeAll: 10},
				},
			},
			wantSum: map[string]map[string]int64{
				"sandbox.count": {"all": 1, "running": 1},
			},
		},
		{
			name: "idempotent reacquire is zero delta",
			seed: []AcquireParams{{
				APIKeyID:   "K",
				LockString: "l1",
				Scopes:     []models.QuotaScope{models.ScopeRunning},
			}},
			op: AcquireParams{
				APIKeyID:   "K",
				LockString: "l1",
				Scopes:     []models.QuotaScope{models.ScopeRunning},
			},
			wantSum: map[string]map[string]int64{
				"sandbox.count": {"all": 1, "running": 1},
			},
		},
		{
			name: "pause drops running and keeps all",
			seed: []AcquireParams{{
				APIKeyID:   "K",
				LockString: "l1",
				Scopes:     []models.QuotaScope{models.ScopeRunning},
			}},
			op: AcquireParams{
				APIKeyID:   "K",
				LockString: "l1",
			},
			wantSum: map[string]map[string]int64{
				"sandbox.count": {"all": 1, "running": 0},
			},
		},
		{
			name: "enforce rejects at all scope cap",
			seed: []AcquireParams{{
				APIKeyID:   "K",
				LockString: "l1",
				Scopes:     []models.QuotaScope{models.ScopeRunning},
			}},
			op: AcquireParams{
				APIKeyID:   "K",
				LockString: "l2",
				Scopes:     []models.QuotaScope{models.ScopeRunning},
				Enforce:    true,
				Limits: map[models.QuotaDimension]map[models.QuotaScope]int64{
					models.DimSandboxCount: {models.ScopeAll: 1},
				},
			},
			expectError: "quota exceeded",
		},
		{
			name: "cpu footprint charges all and running",
			op: AcquireParams{
				APIKeyID:   "K",
				LockString: "l1",
				Footprint: map[models.QuotaDimension]int64{
					models.DimLimitsCPU: 2000,
				},
				Scopes: []models.QuotaScope{models.ScopeRunning},
			},
			wantSum: map[string]map[string]int64{
				"sandbox.count": {"all": 1, "running": 1},
				"limits.cpu":    {"all": 2000, "running": 2000},
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			backend, client := newTestRedisBackend(t)
			ctx := context.Background()

			for _, seed := range tt.seed {
				require.NoError(t, backend.Acquire(ctx, seed))
			}

			err := backend.Acquire(ctx, tt.op)
			if tt.expectError != "" {
				require.Error(t, err)
				assert.Contains(t, err.Error(), tt.expectError)
			} else {
				require.NoError(t, err)
			}

			for dim, scopes := range tt.wantSum {
				for scope, want := range scopes {
					assert.Equal(t, want, readSum(t, client, "K", models.QuotaDimension(dim), models.QuotaScope(scope)))
				}
			}
		})
	}
}

func TestReleaseSubtractsAllScopes(t *testing.T) {
	backend, client := newTestRedisBackend(t)
	ctx := context.Background()

	require.NoError(t, backend.Acquire(ctx, AcquireParams{
		APIKeyID:   "K",
		LockString: "l1",
		Footprint: map[models.QuotaDimension]int64{
			models.DimLimitsCPU:    2000,
			models.DimLimitsMemory: 4096,
		},
		Scopes: []models.QuotaScope{models.ScopeRunning},
	}))

	require.NoError(t, backend.Release(ctx, "K", "l1"))
	require.NoError(t, backend.Release(ctx, "K", "l1"))

	assert.Equal(t, int64(0), readSum(t, client, "K", models.DimSandboxCount, models.ScopeAll))
	assert.Equal(t, int64(0), readSum(t, client, "K", models.DimSandboxCount, models.ScopeRunning))
	assert.Equal(t, int64(0), readSum(t, client, "K", models.DimLimitsCPU, models.ScopeAll))
	assert.Equal(t, int64(0), readSum(t, client, "K", models.DimLimitsCPU, models.ScopeRunning))
	assert.Equal(t, int64(0), readSum(t, client, "K", models.DimLimitsMemory, models.ScopeAll))
	assert.Equal(t, int64(0), readSum(t, client, "K", models.DimLimitsMemory, models.ScopeRunning))

	entries, err := backend.ListEntries(ctx, "K")
	require.NoError(t, err)
	assert.Empty(t, entries)
}

func TestListEntriesReturnsDecodedEntries(t *testing.T) {
	backend, _ := newTestRedisBackend(t)
	ctx := context.Background()

	require.NoError(t, backend.Acquire(ctx, AcquireParams{
		APIKeyID:   "K",
		LockString: "l1",
		Footprint: map[models.QuotaDimension]int64{
			models.DimLimitsCPU: 2000,
		},
		Scopes: []models.QuotaScope{models.ScopeRunning},
	}))
	require.NoError(t, backend.Acquire(ctx, AcquireParams{
		APIKeyID:   "K",
		LockString: "l2",
		Scopes:     nil,
	}))

	entries, err := backend.ListEntries(ctx, "K")
	require.NoError(t, err)
	require.Len(t, entries, 2)
	assert.Equal(t, Entry{
		Footprint: map[models.QuotaDimension]int64{models.DimLimitsCPU: 2000},
		Scopes:    []models.QuotaScope{models.ScopeRunning},
	}, entries["l1"])
	assert.Equal(t, Entry{}, entries["l2"])
}

func TestListEntriesNormalizesConditionalScopesOnly(t *testing.T) {
	backend, _ := newTestRedisBackend(t)
	ctx := context.Background()

	require.NoError(t, backend.Acquire(ctx, AcquireParams{
		APIKeyID:   "K",
		LockString: "l1",
		Scopes: []models.QuotaScope{
			models.ScopeAll,
			models.ScopeRunning,
			models.ScopeRunning,
		},
	}))

	entries, err := backend.ListEntries(ctx, "K")
	require.NoError(t, err)
	require.Contains(t, entries, "l1")
	assert.Equal(t, Entry{
		Scopes: []models.QuotaScope{models.ScopeRunning},
	}, entries["l1"])
}

func TestListEntriesNormalizesFootprintDimensions(t *testing.T) {
	backend, _ := newTestRedisBackend(t)
	ctx := context.Background()

	require.NoError(t, backend.Acquire(ctx, AcquireParams{
		APIKeyID:   "K",
		LockString: "l1",
		Footprint: map[models.QuotaDimension]int64{
			models.DimSandboxCount:               1,
			models.DimLimitsCPU:                  2000,
			models.DimLimitsMemory:               4096,
			models.QuotaDimension("limits.gpu"):  8,
			models.QuotaDimension("unknown.dim"): -1,
		},
	}))

	entries, err := backend.ListEntries(ctx, "K")
	require.NoError(t, err)
	require.Contains(t, entries, "l1")
	assert.Equal(t, Entry{
		Footprint: map[models.QuotaDimension]int64{
			models.DimLimitsCPU:    2000,
			models.DimLimitsMemory: 4096,
		},
	}, entries["l1"])
}

func TestListEntriesSkipsMalformedEntries(t *testing.T) {
	srv := miniredis.RunT(t)
	backend := NewRedisBackend(redis.NewClient(&redis.Options{Addr: srv.Addr()}), time.Second)

	ctx := context.Background()
	beforeDecodeErrors := testutil.ToFloat64(backendErrorsTotal.WithLabelValues("list_entries_decode"))
	require.NoError(t, backend.Acquire(ctx, AcquireParams{
		APIKeyID:   "K",
		LockString: "good",
		Footprint:  map[models.QuotaDimension]int64{models.DimLimitsCPU: 1000},
		Scopes:     []models.QuotaScope{models.ScopeRunning},
	}))
	srv.HSet(liveKey("K"), "bad", "{")

	entries, err := backend.ListEntries(ctx, "K")
	require.NoError(t, err)
	require.Contains(t, entries, "good")
	require.NotContains(t, entries, "bad")
	assert.Equal(t, beforeDecodeErrors+1, testutil.ToFloat64(backendErrorsTotal.WithLabelValues("list_entries_decode")))
}

func TestCleanupDeletesLiveAndAllSums(t *testing.T) {
	backend, client := newTestRedisBackend(t)
	ctx := context.Background()

	require.NoError(t, backend.Acquire(ctx, AcquireParams{
		APIKeyID:   "K",
		LockString: "l1",
		Footprint: map[models.QuotaDimension]int64{
			models.DimLimitsCPU: 2000,
		},
		Scopes: []models.QuotaScope{models.ScopeRunning},
	}))
	require.NoError(t, backend.Cleanup(ctx, "K"))

	assert.Equal(t, int64(0), readSum(t, client, "K", models.DimSandboxCount, models.ScopeAll))
	assert.Equal(t, int64(0), readSum(t, client, "K", models.DimLimitsCPU, models.ScopeAll))
	assert.False(t, keyExists(t, client, liveKey("K")))
	assert.False(t, keyExists(t, client, sumKey("K", models.DimSandboxCount)))
	assert.False(t, keyExists(t, client, sumKey("K", models.DimLimitsCPU)))
	assert.False(t, keyExists(t, client, sumKey("K", models.DimLimitsMemory)))
}

func TestNoopBackend(t *testing.T) {
	backend := NoopBackend{}
	ctx := context.Background()

	require.NoError(t, backend.Acquire(ctx, AcquireParams{APIKeyID: "K", LockString: "l1"}))
	require.NoError(t, backend.Release(ctx, "K", "l1"))
	require.NoError(t, backend.Cleanup(ctx, "K"))

	entries, err := backend.ListEntries(ctx, "K")
	require.NoError(t, err)
	assert.Empty(t, entries)
}

func newTestRedisBackend(t *testing.T) (*RedisBackend, *redis.Client) {
	t.Helper()

	srv := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: srv.Addr()})
	t.Cleanup(func() {
		_ = client.Close()
		srv.Close()
	})
	return NewRedisBackend(client, 50*time.Millisecond), client
}

func readSum(t *testing.T, client *redis.Client, apiKeyID string, dimension models.QuotaDimension, scope models.QuotaScope) int64 {
	t.Helper()

	value, err := client.HGet(context.Background(), sumKey(apiKeyID, dimension), string(scope)).Result()
	if err == redis.Nil {
		return 0
	}
	require.NoError(t, err)

	sum, err := strconv.ParseInt(value, 10, 64)
	require.NoError(t, err)
	return sum
}

func keyExists(t *testing.T, client *redis.Client, key string) bool {
	t.Helper()

	exists, err := client.Exists(context.Background(), key).Result()
	require.NoError(t, err)
	return exists == 1
}
