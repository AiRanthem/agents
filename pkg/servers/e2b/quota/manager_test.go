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
	"sync/atomic"
	"testing"
	"time"

	"github.com/openkruise/agents/pkg/servers/e2b/models"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

type fakeBackend struct {
	acquireCalls       atomic.Int64
	releaseCalls       atomic.Int64
	addObservedCalls   atomic.Int64
	listCalls          atomic.Int64
	deleteSubjectCalls atomic.Int64
	releaseHadDeadline atomic.Bool
	deleteHadDeadline  atomic.Bool
	acquireErr         error
	releaseErr         error
	deleteSubjectErr   error
}

func (f *fakeBackend) Acquire(context.Context, string, string, int64) error {
	f.acquireCalls.Add(1)
	return f.acquireErr
}

func (f *fakeBackend) Release(ctx context.Context, _, _ string) error {
	f.releaseCalls.Add(1)
	_, ok := ctx.Deadline()
	f.releaseHadDeadline.Store(ok)
	return f.releaseErr
}

func (f *fakeBackend) AddObserved(context.Context, string, string, time.Time) error {
	f.addObservedCalls.Add(1)
	return nil
}

func (f *fakeBackend) List(context.Context, string) (map[string]time.Time, error) {
	f.listCalls.Add(1)
	return map[string]time.Time{}, nil
}

func (f *fakeBackend) DeleteSubject(ctx context.Context, _ string) error {
	f.deleteSubjectCalls.Add(1)
	_, ok := ctx.Deadline()
	f.deleteHadDeadline.Store(ok)
	return f.deleteSubjectErr
}

func TestManagerAcquireUnlimitedZeroBackendIO(t *testing.T) {
	tests := []struct {
		name       string
		apiKeyID   string
		lockString string
		quota      *models.QuotaSpec
	}{
		{name: "nil quota with non-empty identity", apiKeyID: "key", lockString: "lock"},
		{name: "nil quota with empty apiKeyID", apiKeyID: "", lockString: "lock"},
		{name: "nil quota with empty lockstring", apiKeyID: "key", lockString: ""},
		{name: "nil quota with empty both", apiKeyID: "", lockString: ""},
		{name: "all nil limits quota", apiKeyID: "", lockString: "", quota: &models.QuotaSpec{Limits: []models.QuotaLimit{{Dimension: models.DimSandboxCount}}}},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			backend := &fakeBackend{}
			manager := NewManager(backend)

			err := manager.Acquire(context.Background(), AcquireRequest{
				APIKeyID:   tt.apiKeyID,
				LockString: tt.lockString,
				Quota:      tt.quota,
			})

			require.NoError(t, err)
			assert.Equal(t, int64(0), backend.acquireCalls.Load(), "unlimited keys need no backend identity")
		})
	}
}

func TestManagerAcquireLimitedRejectAndFailOpen(t *testing.T) {
	limit := int64(1)
	tests := []struct {
		name        string
		backendErr  error
		expectError error
	}{
		{name: "quota rejected is terminal", backendErr: ErrQuotaExceeded, expectError: ErrQuotaExceeded},
		{name: "backend unavailable fail-open", backendErr: ErrBackendUnavailable},
		{name: "unexpected backend error fail-open", backendErr: errors.New("redis protocol drift")},
		{name: "backend allowed", backendErr: nil},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			backend := &fakeBackend{acquireErr: tt.backendErr}
			manager := NewManager(backend)

			err := manager.Acquire(context.Background(), AcquireRequest{
				APIKeyID:   "key",
				LockString: "lock",
				Quota:      quotaSpecWithSandboxCountLimit(limit),
			})

			if tt.expectError != nil {
				require.ErrorIs(t, err, tt.expectError)
			} else {
				require.NoError(t, err)
			}
			assert.Equal(t, int64(1), backend.acquireCalls.Load())
		})
	}
}

func TestManagerAcquireLimitedMissingIdentityErrors(t *testing.T) {
	limit := int64(1)
	tests := []struct {
		name       string
		apiKeyID   string
		lockString string
	}{
		{name: "empty lockstring", apiKeyID: "key", lockString: ""},
		{name: "empty apiKeyID", apiKeyID: "", lockString: "lock"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			backend := &fakeBackend{}
			manager := NewManager(backend)

			err := manager.Acquire(context.Background(), AcquireRequest{
				APIKeyID:   tt.apiKeyID,
				LockString: tt.lockString,
				Quota:      quotaSpecWithSandboxCountLimit(limit),
			})

			require.ErrorIs(t, err, ErrMissingIdentity)
			assert.NotErrorIs(t, err, ErrQuotaExceeded)
			assert.Equal(t, int64(0), backend.acquireCalls.Load(), "limited missing-identity must not call the backend")
		})
	}
}

func TestManagerReleaseDoesNotCreateTimeout(t *testing.T) {
	backend := &fakeBackend{}
	manager := NewManager(backend)

	require.NoError(t, manager.Release(context.Background(), ReleaseRequest{
		APIKeyID:   "key",
		LockString: "lock",
	}))

	assert.Equal(t, int64(1), backend.releaseCalls.Load())
	assert.False(t, backend.releaseHadDeadline.Load())
}

func TestManagerReleaseEmptyIdentityNoop(t *testing.T) {
	tests := []struct {
		name       string
		apiKeyID   string
		lockString string
	}{
		{name: "empty apiKeyID", apiKeyID: "", lockString: "lock"},
		{name: "empty lockstring", apiKeyID: "key", lockString: ""},
		{name: "empty both", apiKeyID: "", lockString: ""},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			backend := &fakeBackend{}
			manager := NewManager(backend)

			require.NoError(t, manager.Release(context.Background(), ReleaseRequest{
				APIKeyID:   tt.apiKeyID,
				LockString: tt.lockString,
			}))

			assert.Equal(t, int64(0), backend.releaseCalls.Load())
		})
	}
}

func TestManagerDeleteSubject(t *testing.T) {
	tests := []struct {
		name       string
		apiKeyID   string
		expectCall bool
	}{
		{name: "empty apiKeyID is no-op", apiKeyID: ""},
		{name: "non-empty apiKeyID deletes subject", apiKeyID: "key", expectCall: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			backend := &fakeBackend{}
			manager := NewManager(backend)

			require.NoError(t, manager.DeleteSubject(context.Background(), tt.apiKeyID))

			if tt.expectCall {
				assert.Equal(t, int64(1), backend.deleteSubjectCalls.Load())
				assert.False(t, backend.deleteHadDeadline.Load())
			} else {
				assert.Equal(t, int64(0), backend.deleteSubjectCalls.Load())
			}
		})
	}
}

func quotaSpecWithSandboxCountLimit(limit int64) *models.QuotaSpec {
	limitCopy := limit
	return &models.QuotaSpec{
		Limits: []models.QuotaLimit{
			{
				Dimension: models.DimSandboxCount,
				Limit:     &limitCopy,
			},
		},
	}
}
