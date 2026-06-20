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
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	toolscache "k8s.io/client-go/tools/cache"

	agentsv1alpha1 "github.com/openkruise/agents/api/v1alpha1"
	"github.com/openkruise/agents/pkg/cache"
	"github.com/openkruise/agents/pkg/servers/e2b/models"
)

type fakeLimitedKeyStore struct {
	keys []*models.CreatedTeamAPIKey
	err  error
}

func (f fakeLimitedKeyStore) ListLimited(context.Context) ([]*models.CreatedTeamAPIKey, error) {
	return f.keys, f.err
}

type fakeLiveCache struct {
	liveByOwner map[string][]cache.LiveLockstring
	liveErr     error
	removeSafe  bool
	listCalls   int
}

func (f *fakeLiveCache) ListLiveLockstringsByOwner(_ context.Context, opts cache.ListLiveLockstringsByOwnerOptions) ([]cache.LiveLockstring, error) {
	f.listCalls++
	if f.liveErr != nil {
		return nil, f.liveErr
	}
	return append([]cache.LiveLockstring(nil), f.liveByOwner[opts.Owner]...), nil
}

func (f *fakeLiveCache) RemoveSafe() bool {
	return f.removeSafe
}

type fakePrimary struct{ primary bool }

func (f fakePrimary) IsPrimary() bool {
	return f.primary
}

type fakeRegistration struct {
	removed bool
}

func (f *fakeRegistration) HasSynced() bool {
	return true
}

func (f *fakeRegistration) Remove() error {
	f.removed = true
	return nil
}

type recordingBackend struct {
	mu      sync.Mutex
	have    map[string]map[string]time.Time
	added   map[string][]string
	removed map[string][]string
	listErr error
}

func newRecordingBackend() *recordingBackend {
	return &recordingBackend{
		have:    map[string]map[string]time.Time{},
		added:   map[string][]string{},
		removed: map[string][]string{},
	}
}

func (r *recordingBackend) Acquire(context.Context, string, string, int64) error {
	return nil
}

func (r *recordingBackend) AddObserved(_ context.Context, apiKeyID, lockString string, acquiredAt time.Time) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.added[apiKeyID] = append(r.added[apiKeyID], lockString)
	if r.have[apiKeyID] == nil {
		r.have[apiKeyID] = map[string]time.Time{}
	}
	r.have[apiKeyID][lockString] = acquiredAt
	return nil
}

func (r *recordingBackend) List(_ context.Context, apiKeyID string) (map[string]time.Time, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.listErr != nil {
		return nil, r.listErr
	}
	out := map[string]time.Time{}
	for lock, ts := range r.have[apiKeyID] {
		out[lock] = ts
	}
	return out, nil
}

func (r *recordingBackend) Release(_ context.Context, apiKeyID, lockString string) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.removed[apiKeyID] = append(r.removed[apiKeyID], lockString)
	delete(r.have[apiKeyID], lockString)
	return nil
}

func (r *recordingBackend) DeleteSubject(context.Context, string) error {
	return nil
}

func TestAntiDriftAddsMissingLiveEntriesWithoutLimitCheck(t *testing.T) {
	limit := int64(1)
	key := limitedQuotaKey(t, limit)
	backend := newRecordingBackend()
	liveCache := &fakeLiveCache{
		removeSafe: true,
		liveByOwner: map[string][]cache.LiveLockstring{
			key.ID.String(): {{LockString: "lock-1", CreationTimestamp: time.Now().Add(-2 * time.Minute)}},
		},
	}
	driver := NewAntiDriftDriver(AntiDriftConfig{Grace: time.Minute}, fakePrimary{primary: true}, fakeLimitedKeyStore{keys: []*models.CreatedTeamAPIKey{key}}, liveCache, backend)

	require.NoError(t, driver.RunOnce(context.Background()))

	assert.Contains(t, backend.added[key.ID.String()], "lock-1")
}

func TestAntiDriftRemovesStaleRedisEntriesWhenCacheHealthy(t *testing.T) {
	limit := int64(1)
	key := limitedQuotaKey(t, limit)
	backend := newRecordingBackend()
	backend.have[key.ID.String()] = map[string]time.Time{"leaked": time.Now().Add(-2 * time.Minute)}
	driver := NewAntiDriftDriver(AntiDriftConfig{Grace: time.Minute}, fakePrimary{primary: true}, fakeLimitedKeyStore{keys: []*models.CreatedTeamAPIKey{key}}, &fakeLiveCache{removeSafe: true}, backend)

	require.NoError(t, driver.RunOnce(context.Background()))

	assert.Contains(t, backend.removed[key.ID.String()], "leaked")
}

func TestAntiDriftSkipsRemoveWhenCacheUnhealthy(t *testing.T) {
	limit := int64(1)
	key := limitedQuotaKey(t, limit)
	backend := newRecordingBackend()
	backend.have[key.ID.String()] = map[string]time.Time{"leaked": time.Now().Add(-2 * time.Minute)}
	driver := NewAntiDriftDriver(AntiDriftConfig{Grace: time.Minute}, fakePrimary{primary: true}, fakeLimitedKeyStore{keys: []*models.CreatedTeamAPIKey{key}}, &fakeLiveCache{removeSafe: false}, backend)

	require.NoError(t, driver.RunOnce(context.Background()))

	assert.Empty(t, backend.removed[key.ID.String()])
}

func TestAntiDriftEnumerationErrorSkipsCycle(t *testing.T) {
	backend := newRecordingBackend()
	driver := NewAntiDriftDriver(AntiDriftConfig{Grace: time.Minute}, fakePrimary{primary: true}, fakeLimitedKeyStore{err: errors.New("key store down")}, &fakeLiveCache{removeSafe: true}, backend)

	require.Error(t, driver.RunOnce(context.Background()))

	assert.Empty(t, backend.added)
	assert.Empty(t, backend.removed)
}

func TestAntiDriftAddsEvenWhenRemoveUnsafe(t *testing.T) {
	limit := int64(1)
	key := limitedQuotaKey(t, limit)
	backend := newRecordingBackend()
	backend.have[key.ID.String()] = map[string]time.Time{"leaked": time.Now().Add(-2 * time.Minute)}
	liveCache := &fakeLiveCache{
		removeSafe: false,
		liveByOwner: map[string][]cache.LiveLockstring{
			key.ID.String(): {{LockString: "lock-1", CreationTimestamp: time.Now().Add(-2 * time.Minute)}},
		},
	}
	driver := NewAntiDriftDriver(AntiDriftConfig{Grace: time.Minute}, fakePrimary{primary: true}, fakeLimitedKeyStore{keys: []*models.CreatedTeamAPIKey{key}}, liveCache, backend)

	require.NoError(t, driver.RunOnce(context.Background()))

	assert.Contains(t, backend.added[key.ID.String()], "lock-1", "add must run even when remove is unsafe")
	assert.Empty(t, backend.removed[key.ID.String()], "remove must be skipped when RemoveSafe is false")
}

func TestAntiDriftSkipsKeyWhenLiveListErrors(t *testing.T) {
	limit := int64(1)
	key := limitedQuotaKey(t, limit)
	backend := newRecordingBackend()
	backend.have[key.ID.String()] = map[string]time.Time{"leaked": time.Now().Add(-2 * time.Minute)}
	driver := NewAntiDriftDriver(AntiDriftConfig{Grace: time.Minute}, fakePrimary{primary: true}, fakeLimitedKeyStore{keys: []*models.CreatedTeamAPIKey{key}}, &fakeLiveCache{removeSafe: true, liveErr: errors.New("informer cold")}, backend)

	require.NoError(t, driver.RunOnce(context.Background()))

	assert.Empty(t, backend.added[key.ID.String()], "probe failure must skip add")
	assert.Empty(t, backend.removed[key.ID.String()], "probe failure must skip remove")
}

func TestAntiDriftSkipsRemoveWhenRedisListErrors(t *testing.T) {
	limit := int64(1)
	key := limitedQuotaKey(t, limit)
	backend := newRecordingBackend()
	backend.have[key.ID.String()] = map[string]time.Time{"leaked": time.Now().Add(-2 * time.Minute)}
	backend.listErr = ErrBackendUnavailable
	liveCache := &fakeLiveCache{
		removeSafe: true,
		liveByOwner: map[string][]cache.LiveLockstring{
			key.ID.String(): {{LockString: "lock-1", CreationTimestamp: time.Now().Add(-2 * time.Minute)}},
		},
	}
	driver := NewAntiDriftDriver(AntiDriftConfig{Grace: time.Minute}, fakePrimary{primary: true}, fakeLimitedKeyStore{keys: []*models.CreatedTeamAPIKey{key}}, liveCache, backend)

	require.NoError(t, driver.RunOnce(context.Background()))

	assert.Empty(t, backend.added[key.ID.String()], "redis list failure must skip add for this key")
	assert.Empty(t, backend.removed[key.ID.String()], "redis list failure must not be treated as empty and must not HDEL")
}

func TestAntiDriftEventUpdateToNotLiveReleasesWithProbe(t *testing.T) {
	owner := uuid.New().String()
	tests := []struct {
		name   string
		mutate func(*agentsv1alpha1.Sandbox)
	}{
		{
			name: "deletion timestamp",
			mutate: func(sbx *agentsv1alpha1.Sandbox) {
				sbx.DeletionTimestamp = &metav1.Time{Time: time.Now()}
			},
		},
		{
			name: "terminating phase",
			mutate: func(sbx *agentsv1alpha1.Sandbox) {
				sbx.Status.Phase = agentsv1alpha1.SandboxTerminating
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			sbx := sandboxForQuotaEvent(owner, "lock-1")
			tt.mutate(sbx)
			backend := newRecordingBackend()
			backend.have[owner] = map[string]time.Time{"lock-1": time.Now()}
			driver := NewAntiDriftDriver(AntiDriftConfig{Grace: time.Minute}, fakePrimary{primary: true}, fakeLimitedKeyStore{}, &fakeLiveCache{removeSafe: true}, backend)

			driver.SandboxEventHandler().OnUpdate(sandboxForQuotaEvent(owner, "lock-1"), sbx)

			assert.Contains(t, backend.removed[owner], "lock-1")
		})
	}
}

func TestAntiDriftDeleteTombstoneReleasesWithProbe(t *testing.T) {
	owner := uuid.New().String()
	sbx := sandboxForQuotaEvent(owner, "lock-1")
	backend := newRecordingBackend()
	backend.have[owner] = map[string]time.Time{"lock-1": time.Now()}
	driver := NewAntiDriftDriver(AntiDriftConfig{Grace: time.Minute}, fakePrimary{primary: true}, fakeLimitedKeyStore{}, &fakeLiveCache{removeSafe: true}, backend)

	driver.SandboxEventHandler().OnDelete(toolscache.DeletedFinalStateUnknown{Obj: sbx})

	assert.Contains(t, backend.removed[owner], "lock-1")
}

func TestAntiDriftEventReleaseRequiresProbe(t *testing.T) {
	owner := uuid.New().String()
	tests := []struct {
		name          string
		primary       bool
		removeSafe    bool
		liveErr       error
		live          []cache.LiveLockstring
		owner         string
		lockString    string
		expectRelease bool
	}{
		{name: "not primary skips", primary: false, removeSafe: true, owner: owner, lockString: "lock-1"},
		{name: "remove unsafe skips", primary: true, removeSafe: false, owner: owner, lockString: "lock-1"},
		{name: "missing owner skips", primary: true, removeSafe: true, lockString: "lock-1"},
		{name: "missing lockstring skips", primary: true, removeSafe: true, owner: owner},
		{name: "probe error skips", primary: true, removeSafe: true, liveErr: errors.New("probe failed"), owner: owner, lockString: "lock-1"},
		{name: "lock still live skips", primary: true, removeSafe: true, live: []cache.LiveLockstring{{LockString: "lock-1"}}, owner: owner, lockString: "lock-1"},
		{name: "probe confirms gone releases", primary: true, removeSafe: true, owner: owner, lockString: "lock-1", expectRelease: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			sbx := sandboxForQuotaEvent(tt.owner, tt.lockString)
			backend := newRecordingBackend()
			backend.have[owner] = map[string]time.Time{"lock-1": time.Now()}
			liveCache := &fakeLiveCache{
				removeSafe: tt.removeSafe,
				liveErr:    tt.liveErr,
				liveByOwner: map[string][]cache.LiveLockstring{
					tt.owner: tt.live,
				},
			}
			driver := NewAntiDriftDriver(AntiDriftConfig{Grace: time.Minute}, fakePrimary{primary: tt.primary}, fakeLimitedKeyStore{}, liveCache, backend)

			driver.SandboxEventHandler().OnDelete(sbx)

			if tt.expectRelease {
				assert.Contains(t, backend.removed[owner], "lock-1")
			} else {
				assert.Empty(t, backend.removed[owner])
			}
		})
	}
}

func TestAntiDriftRunStartsNonBlockingAndStops(t *testing.T) {
	driver := NewAntiDriftDriver(AntiDriftConfig{Interval: time.Hour, Grace: time.Minute}, fakePrimary{primary: true}, fakeLimitedKeyStore{}, &fakeLiveCache{removeSafe: true}, newRecordingBackend())
	registration := &fakeRegistration{}
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
		t.Fatal("AntiDriftDriver.Run must start the ticker loop asynchronously and return")
	}

	cancel()
	driver.Stop()
	assert.True(t, registration.removed)
}

func TestAntiDriftRunOnceHonorsCancellation(t *testing.T) {
	limit := int64(1)
	key := limitedQuotaKey(t, limit)
	backend := newRecordingBackend()
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	liveCache := &fakeLiveCache{
		removeSafe: true,
		liveByOwner: map[string][]cache.LiveLockstring{
			key.ID.String(): {{LockString: "lock-1", CreationTimestamp: time.Now().Add(-2 * time.Minute)}},
		},
	}
	driver := NewAntiDriftDriver(AntiDriftConfig{Grace: time.Minute}, fakePrimary{primary: true}, fakeLimitedKeyStore{keys: []*models.CreatedTeamAPIKey{key}}, liveCache, backend)

	require.ErrorIs(t, driver.RunOnce(ctx), context.Canceled)
	assert.Empty(t, backend.added)
	assert.Empty(t, backend.removed)
}

func limitedQuotaKey(t *testing.T, limit int64) *models.CreatedTeamAPIKey {
	t.Helper()
	limitCopy := limit
	return &models.CreatedTeamAPIKey{
		ID: uuid.New(),
		QuotaSpec: &models.QuotaSpec{
			Limits: []models.QuotaLimit{
				{
					Dimension: models.DimSandboxCount,
					Limit:     &limitCopy,
				},
			},
		},
	}
}

func sandboxForQuotaEvent(owner, lockString string) *agentsv1alpha1.Sandbox {
	annotations := map[string]string{}
	if owner != "" {
		annotations[agentsv1alpha1.AnnotationOwner] = owner
	}
	if lockString != "" {
		annotations[agentsv1alpha1.AnnotationLock] = lockString
	}
	return &agentsv1alpha1.Sandbox{
		ObjectMeta: metav1.ObjectMeta{
			Name:        "sbx-1",
			Namespace:   "default",
			Annotations: annotations,
		},
	}
}
