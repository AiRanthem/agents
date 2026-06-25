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

	"github.com/prometheus/client_golang/prometheus/testutil"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/openkruise/agents/pkg/servers/e2b/models"
)

type managerTestBackend struct {
	acquireCalls  int
	releaseCalls  int
	cleanupCalls  int
	acquireParams []AcquireParams
	releaseArgs   []ReleaseRequest
	cleanupKeys   []string
	acquireErr    error
	releaseErr    error
	cleanupErr    error
}

func (b *managerTestBackend) Acquire(_ context.Context, p AcquireParams) error {
	b.acquireCalls++
	b.acquireParams = append(b.acquireParams, p)
	return b.acquireErr
}

func (b *managerTestBackend) Release(_ context.Context, apiKeyID, lockString string) error {
	b.releaseCalls++
	b.releaseArgs = append(b.releaseArgs, ReleaseRequest{APIKeyID: apiKeyID, LockString: lockString})
	return b.releaseErr
}

func (b *managerTestBackend) ListEntries(context.Context, string) (map[string]Entry, error) {
	return map[string]Entry{}, nil
}

func (b *managerTestBackend) Cleanup(_ context.Context, apiKeyID string) error {
	b.cleanupCalls++
	b.cleanupKeys = append(b.cleanupKeys, apiKeyID)
	return b.cleanupErr
}

func TestManagerAcquire(t *testing.T) {
	quota := &models.QuotaSpec{Limits: []models.QuotaLimit{{
		Dimension: models.DimSandboxCount,
		Scope:     models.ScopeAll,
		Limit:     2,
	}, {
		Dimension: models.DimLimitsCPU,
		Scope:     models.ScopeRunning,
		Limit:     4000,
	}}}

	tests := []struct {
		name                string
		req                 AcquireRequest
		acquireErr          error
		expectError         string
		expectMetric        string
		expectBackendCalls  int
		expectBackendErrors int
		wantParams          *AcquireParams
	}{
		{
			name: "unlimited short circuits without backend io",
			req: AcquireRequest{
				APIKeyID:   "K",
				LockString: "l1",
				Scopes:     []models.QuotaScope{models.ScopeRunning},
			},
			expectMetric: "unlimited",
		},
		{
			name: "limited forwards full request to backend",
			req: AcquireRequest{
				APIKeyID:   "K",
				LockString: "l1",
				Quota:      quota,
				Footprint: map[models.QuotaDimension]int64{
					models.DimLimitsCPU: 2000,
				},
				Scopes: []models.QuotaScope{models.ScopeRunning},
			},
			expectMetric:       "allowed",
			expectBackendCalls: 1,
			wantParams: &AcquireParams{
				APIKeyID:   "K",
				LockString: "l1",
				Footprint: map[models.QuotaDimension]int64{
					models.DimLimitsCPU: 2000,
				},
				Scopes:  []models.QuotaScope{models.ScopeRunning},
				Enforce: true,
				Limits:  quota.LimitedPairs(),
			},
		},
		{
			name: "quota exceeded propagates",
			req: AcquireRequest{
				APIKeyID:   "K",
				LockString: "l1",
				Quota:      quota,
				Scopes:     []models.QuotaScope{models.ScopeRunning},
			},
			acquireErr:         ErrQuotaExceeded,
			expectError:        "quota exceeded",
			expectMetric:       "rejected",
			expectBackendCalls: 1,
		},
		{
			name: "backend transport error fails open",
			req: AcquireRequest{
				APIKeyID:   "K",
				LockString: "l1",
				Quota:      quota,
				Scopes:     []models.QuotaScope{models.ScopeRunning},
			},
			acquireErr:          ErrBackendUnavailable,
			expectMetric:        "fail_open",
			expectBackendCalls:  1,
			expectBackendErrors: 1,
		},
		{
			name: "unexpected backend error fails open",
			req: AcquireRequest{
				APIKeyID:   "K",
				LockString: "l1",
				Quota:      quota,
				Scopes:     []models.QuotaScope{models.ScopeRunning},
			},
			acquireErr:          errors.New("boom"),
			expectMetric:        "fail_open",
			expectBackendCalls:  1,
			expectBackendErrors: 1,
		},
		{
			name: "limited missing identity returns error before backend io",
			req: AcquireRequest{
				LockString: "l1",
				Quota:      quota,
			},
			expectError:  "quota acquire missing identity",
			expectMetric: "error",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			backend := &managerTestBackend{acquireErr: tt.acquireErr}
			manager := NewManager(backend)
			beforeMetric := testutil.ToFloat64(acquireTotal.WithLabelValues(tt.expectMetric))
			beforeBackendErrors := testutil.ToFloat64(backendErrorsTotal.WithLabelValues("acquire"))

			err := manager.Acquire(context.Background(), tt.req)
			if tt.expectError != "" {
				require.Error(t, err)
				assert.Contains(t, err.Error(), tt.expectError)
			} else {
				require.NoError(t, err)
			}

			assert.Equal(t, tt.expectBackendCalls, backend.acquireCalls)
			assert.Equal(t, beforeMetric+1, testutil.ToFloat64(acquireTotal.WithLabelValues(tt.expectMetric)))
			assert.Equal(t, beforeBackendErrors+float64(tt.expectBackendErrors), testutil.ToFloat64(backendErrorsTotal.WithLabelValues("acquire")))
			if tt.wantParams != nil {
				require.Len(t, backend.acquireParams, 1)
				assert.Equal(t, *tt.wantParams, backend.acquireParams[0])
			}
		})
	}
}

func TestManagerRelease(t *testing.T) {
	tests := []struct {
		name                string
		req                 ReleaseRequest
		releaseErr          error
		expectError         string
		expectBackendCalls  int
		expectBackendErrors int
		expectMetric        string
	}{
		{
			name:         "empty api key id is no op",
			req:          ReleaseRequest{LockString: "l1"},
			expectMetric: "skipped",
		},
		{
			name:         "empty lock string is no op",
			req:          ReleaseRequest{APIKeyID: "K"},
			expectMetric: "skipped",
		},
		{
			name:               "release delegates to backend",
			req:                ReleaseRequest{APIKeyID: "K", LockString: "l1"},
			expectBackendCalls: 1,
			expectMetric:       "released",
		},
		{
			name:                "release propagates backend error",
			req:                 ReleaseRequest{APIKeyID: "K", LockString: "l1"},
			releaseErr:          ErrBackendUnavailable,
			expectError:         "quota backend unavailable",
			expectBackendCalls:  1,
			expectBackendErrors: 1,
			expectMetric:        "error",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			backend := &managerTestBackend{releaseErr: tt.releaseErr}
			manager := NewManager(backend)
			beforeBackendErrors := testutil.ToFloat64(backendErrorsTotal.WithLabelValues("release"))
			beforeReleaseTotal := testutil.ToFloat64(releaseTotal.WithLabelValues(tt.expectMetric))

			err := manager.Release(context.Background(), tt.req)
			if tt.expectError != "" {
				require.Error(t, err)
				assert.Contains(t, err.Error(), tt.expectError)
			} else {
				require.NoError(t, err)
			}

			assert.Equal(t, tt.expectBackendCalls, backend.releaseCalls)
			assert.Equal(t, beforeBackendErrors+float64(tt.expectBackendErrors), testutil.ToFloat64(backendErrorsTotal.WithLabelValues("release")))
			assert.Equal(t, beforeReleaseTotal+1, testutil.ToFloat64(releaseTotal.WithLabelValues(tt.expectMetric)))
		})
	}
}

func TestManagerCleanup(t *testing.T) {
	tests := []struct {
		name                string
		apiKeyID            string
		cleanupErr          error
		expectError         string
		expectBackendCalls  int
		expectBackendErrors int
	}{
		{
			name: "empty api key id is no op",
		},
		{
			name:               "cleanup delegates to backend",
			apiKeyID:           "K",
			expectBackendCalls: 1,
		},
		{
			name:                "cleanup propagates backend error",
			apiKeyID:            "K",
			cleanupErr:          ErrBackendUnavailable,
			expectError:         "quota backend unavailable",
			expectBackendCalls:  1,
			expectBackendErrors: 1,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			backend := &managerTestBackend{cleanupErr: tt.cleanupErr}
			manager := NewManager(backend)
			beforeBackendErrors := testutil.ToFloat64(backendErrorsTotal.WithLabelValues("cleanup"))

			err := manager.Cleanup(context.Background(), tt.apiKeyID)
			if tt.expectError != "" {
				require.Error(t, err)
				assert.Contains(t, err.Error(), tt.expectError)
			} else {
				require.NoError(t, err)
			}

			assert.Equal(t, tt.expectBackendCalls, backend.cleanupCalls)
			assert.Equal(t, beforeBackendErrors+float64(tt.expectBackendErrors), testutil.ToFloat64(backendErrorsTotal.WithLabelValues("cleanup")))
		})
	}
}
