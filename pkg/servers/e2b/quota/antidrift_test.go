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
	"sync/atomic"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	agentsv1alpha1 "github.com/openkruise/agents/api/v1alpha1"
	"github.com/openkruise/agents/pkg/servers/e2b/models"
)

type mutablePrimary struct {
	primary atomic.Bool
}

func newMutablePrimary(primary bool) *mutablePrimary {
	p := &mutablePrimary{}
	p.primary.Store(primary)
	return p
}

func (p *mutablePrimary) IsPrimary() bool {
	return p.primary.Load()
}

func (p *mutablePrimary) SetPrimary(primary bool) {
	p.primary.Store(primary)
}

type fakeKeyStore struct {
	limited []*models.CreatedTeamAPIKey
	err     error
}

func (s *fakeKeyStore) ListLimited(context.Context) ([]*models.CreatedTeamAPIKey, error) {
	if s.err != nil {
		return nil, s.err
	}
	return s.limited, nil
}

type fakeLiveSandboxCache struct {
	liveByOwner map[string][]*agentsv1alpha1.Sandbox
	healthy     bool
	err         error
}

func (c *fakeLiveSandboxCache) ListLiveSandboxesByOwner(_ context.Context, owner string) ([]*agentsv1alpha1.Sandbox, error) {
	if c.err != nil {
		return nil, c.err
	}
	return c.liveByOwner[owner], nil
}

func (c *fakeLiveSandboxCache) SandboxInformerHealthy() bool {
	return c.healthy
}

type acquireCall struct {
	params AcquireParams
}

type releaseCall struct {
	apiKeyID   string
	lockString string
}

type fakeBackend struct {
	mu               sync.Mutex
	acquireCalls     []acquireCall
	releaseCalls     []releaseCall
	entriesByKey     map[string]map[string]Entry
	listEntriesCalls atomic.Int64
}

func (b *fakeBackend) Acquire(_ context.Context, p AcquireParams) error {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.acquireCalls = append(b.acquireCalls, acquireCall{params: p})
	return nil
}

func (b *fakeBackend) Release(_ context.Context, apiKeyID, lockString string) error {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.releaseCalls = append(b.releaseCalls, releaseCall{apiKeyID: apiKeyID, lockString: lockString})
	return nil
}

func (b *fakeBackend) ListEntries(_ context.Context, apiKeyID string) (map[string]Entry, error) {
	b.listEntriesCalls.Add(1)
	if b.entriesByKey == nil || b.entriesByKey[apiKeyID] == nil {
		return map[string]Entry{}, nil
	}
	got := make(map[string]Entry, len(b.entriesByKey[apiKeyID]))
	for lockString, entry := range b.entriesByKey[apiKeyID] {
		got[lockString] = entry
	}
	return got, nil
}

func (b *fakeBackend) Cleanup(context.Context, string) error {
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

func TestAntiDriftDiff(t *testing.T) {
	now := time.Date(2026, 6, 23, 12, 0, 0, 0, time.UTC)
	owner := uuid.NewSHA1(uuid.Nil, []byte("owner-1")).String()
	key := limitedKey(owner)

	tests := []struct {
		name         string
		liveCRs      []*agentsv1alpha1.Sandbox
		haveEntries  map[string]Entry
		healthy      bool
		secondPass   bool
		leakedAge    time.Duration
		wantCharged  []string
		wantReleased []string
	}{
		{
			name:        "missing entry for live CR charged",
			liveCRs:     []*agentsv1alpha1.Sandbox{runningSandbox(now, owner, "l1", 11*time.Minute, 250, 128, false)},
			healthy:     true,
			wantCharged: []string{"l1"},
		},
		{
			name:         "leaked released 2nd pass healthy past grace",
			haveEntries:  map[string]Entry{"l9": {}},
			healthy:      true,
			secondPass:   true,
			leakedAge:    11 * time.Minute,
			wantReleased: []string{"l9"},
		},
		{
			name:        "leaked not released first pass",
			haveEntries: map[string]Entry{"l9": {}},
			healthy:     true,
		},
		{
			name:        "leaked not released within grace",
			haveEntries: map[string]Entry{"l9": {}},
			healthy:     true,
			secondPass:  true,
			leakedAge:   3 * time.Minute,
		},
		{
			name:        "release skipped when cache unhealthy",
			haveEntries: map[string]Entry{"l9": {}},
			healthy:     false,
			secondPass:  true,
			leakedAge:   11 * time.Minute,
		},
		{
			name:    "fresh CR under grace not charged",
			liveCRs: []*agentsv1alpha1.Sandbox{runningSandbox(now, owner, "l2", time.Minute, 250, 128, false)},
			healthy: true,
		},
		{
			name:        "fresh CR with stale entry corrected immediately",
			liveCRs:     []*agentsv1alpha1.Sandbox{runningSandbox(now, owner, "l3", time.Minute, 250, 128, false)},
			haveEntries: map[string]Entry{"l3": {Scopes: []models.QuotaScope{}}},
			healthy:     true,
			wantCharged: []string{"l3"},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			backend := &fakeBackend{entriesByKey: map[string]map[string]Entry{owner: tt.haveEntries}}
			liveCache := &fakeLiveSandboxCache{
				liveByOwner: map[string][]*agentsv1alpha1.Sandbox{owner: tt.liveCRs},
				healthy:     tt.healthy,
			}
			driver := NewAntiDriftDriver(
				AntiDriftConfig{Interval: time.Hour, Grace: 10 * time.Minute},
				newMutablePrimary(true),
				&fakeKeyStore{limited: []*models.CreatedTeamAPIKey{key}},
				liveCache,
				backend,
			)
			currentNow := now
			driver.now = func() time.Time { return currentNow }

			if tt.secondPass {
				require.NoError(t, driver.RunOnce(context.Background()))
				backend.resetCalls()
				currentNow = currentNow.Add(tt.leakedAge)
			}

			require.NoError(t, driver.RunOnce(context.Background()))
			assert.ElementsMatch(t, tt.wantCharged, backend.acquireLockstrings())
			assert.ElementsMatch(t, tt.wantReleased, backend.releaseLockstrings())
		})
	}
}

func TestAntiDriftEventReconcile(t *testing.T) {
	now := time.Date(2026, 6, 23, 12, 0, 0, 0, time.UTC)
	owner := uuid.NewSHA1(uuid.Nil, []byte("owner-event")).String()

	tests := []struct {
		name         string
		sbx          *agentsv1alpha1.Sandbox
		healthy      bool
		wantCharged  []string
		wantReleased []string
	}{
		{
			name:        "live sandbox acquired with predicate data",
			sbx:         runningSandbox(now, owner, "lock-live", 30*time.Minute, 500, 256, false),
			healthy:     true,
			wantCharged: []string{"lock-live"},
		},
		{
			name:         "not live sandbox released when cache healthy",
			sbx:          terminatingSandbox(now, owner, "lock-dead"),
			healthy:      true,
			wantReleased: []string{"lock-dead"},
		},
		{
			name:    "not live sandbox release skipped when cache unhealthy",
			sbx:     terminatingSandbox(now, owner, "lock-skipped"),
			healthy: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			backend := &fakeBackend{}
			driver := NewAntiDriftDriver(
				AntiDriftConfig{Interval: time.Hour, Grace: 10 * time.Minute},
				newMutablePrimary(true),
				nil,
				&fakeLiveSandboxCache{healthy: tt.healthy},
				backend,
			)

			driver.SandboxEventHandler().OnUpdate(nil, tt.sbx)
			assert.ElementsMatch(t, tt.wantCharged, backend.acquireLockstrings())
			assert.ElementsMatch(t, tt.wantReleased, backend.releaseLockstrings())

			if len(tt.wantCharged) == 1 {
				require.Len(t, backend.acquireCalls, 1)
				got := backend.acquireCalls[0].params
				assert.Equal(t, owner, got.APIKeyID)
				assert.Equal(t, "lock-live", got.LockString)
				assert.Equal(t, FootprintOf(tt.sbx), got.Footprint)
				assert.Equal(t, ConditionalScopesOf(tt.sbx), got.Scopes)
				assert.False(t, got.Enforce)
			}
		})
	}
}

func TestAntiDriftKeyStoreErrorSkipsCycle(t *testing.T) {
	backend := &fakeBackend{entriesByKey: map[string]map[string]Entry{
		uuid.NewSHA1(uuid.Nil, []byte("owner-skip")).String(): {"lock-1": {}},
	}}
	driver := NewAntiDriftDriver(
		AntiDriftConfig{Interval: time.Hour, Grace: time.Minute},
		newMutablePrimary(true),
		&fakeKeyStore{err: errors.New("boom")},
		&fakeLiveSandboxCache{healthy: true},
		backend,
	)
	require.NoError(t, driver.RunOnce(context.Background()))
	assert.Zero(t, backend.listEntriesCalls.Load())
	assert.Empty(t, backend.acquireLockstrings())
	assert.Empty(t, backend.releaseLockstrings())
}

func TestAntiDriftReappearingEntryClearsLeakedMemory(t *testing.T) {
	now := time.Date(2026, 6, 23, 12, 0, 0, 0, time.UTC)
	owner := uuid.NewSHA1(uuid.Nil, []byte("owner-reappear")).String()
	live := runningSandbox(now, owner, "lock-1", 30*time.Minute, 250, 128, false)
	backend := &fakeBackend{entriesByKey: map[string]map[string]Entry{
		owner: {"lock-1": entryForSandbox(live)},
	}}
	liveCache := &fakeLiveSandboxCache{liveByOwner: map[string][]*agentsv1alpha1.Sandbox{owner: nil}, healthy: true}
	driver := NewAntiDriftDriver(
		AntiDriftConfig{Interval: time.Hour, Grace: 10 * time.Minute},
		newMutablePrimary(true),
		&fakeKeyStore{limited: []*models.CreatedTeamAPIKey{limitedKey(owner)}},
		liveCache,
		backend,
	)
	currentNow := now
	driver.now = func() time.Time { return currentNow }

	require.NoError(t, driver.RunOnce(context.Background()))
	require.Len(t, driver.seenLeaked, 1)

	liveCache.liveByOwner[owner] = []*agentsv1alpha1.Sandbox{live}
	currentNow = currentNow.Add(11 * time.Minute)
	require.NoError(t, driver.RunOnce(context.Background()))
	assert.Empty(t, backend.releaseLockstrings())
	assert.Empty(t, driver.seenLeaked)
}

func TestAntiDriftRunOnceNotPrimaryClearsLeakedState(t *testing.T) {
	now := time.Date(2026, 6, 23, 12, 0, 0, 0, time.UTC)
	owner := uuid.NewSHA1(uuid.Nil, []byte("owner-demote")).String()
	primary := newMutablePrimary(true)
	driver := NewAntiDriftDriver(
		AntiDriftConfig{Interval: time.Hour, Grace: 10 * time.Minute},
		primary,
		&fakeKeyStore{limited: []*models.CreatedTeamAPIKey{limitedKey(owner)}},
		&fakeLiveSandboxCache{healthy: true},
		&fakeBackend{entriesByKey: map[string]map[string]Entry{owner: {"lock-1": {}}}},
	)
	driver.now = func() time.Time { return now }

	require.NoError(t, driver.RunOnce(context.Background()))
	require.Len(t, driver.seenLeaked, 1)

	primary.SetPrimary(false)
	require.NoError(t, driver.RunOnce(context.Background()))
	assert.Empty(t, driver.seenLeaked)
}

func TestAntiDriftRunStartsNonBlockingAndStopRemovesRegistration(t *testing.T) {
	registration := &stubRegistration{}
	driver := NewAntiDriftDriver(
		AntiDriftConfig{Interval: time.Hour, Grace: time.Minute},
		newMutablePrimary(true),
		nil,
		nil,
		&fakeBackend{},
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
		newMutablePrimary(true),
		nil,
		nil,
		&fakeBackend{},
	)
	registration := &stubRegistration{}

	driver.Stop()
	driver.SetEventRegistration(registration)
	driver.Stop()
	assert.True(t, registration.removed.Load())
}

func (b *fakeBackend) acquireLockstrings() []string {
	b.mu.Lock()
	defer b.mu.Unlock()
	locks := make([]string, 0, len(b.acquireCalls))
	for _, call := range b.acquireCalls {
		locks = append(locks, call.params.LockString)
	}
	return locks
}

func (b *fakeBackend) releaseLockstrings() []string {
	b.mu.Lock()
	defer b.mu.Unlock()
	locks := make([]string, 0, len(b.releaseCalls))
	for _, call := range b.releaseCalls {
		locks = append(locks, call.lockString)
	}
	return locks
}

func (b *fakeBackend) resetCalls() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.acquireCalls = nil
	b.releaseCalls = nil
}

func limitedKey(owner string) *models.CreatedTeamAPIKey {
	return &models.CreatedTeamAPIKey{
		ID: uuid.MustParse(owner),
		QuotaSpec: &models.QuotaSpec{Limits: []models.QuotaLimit{{
			Dimension: models.DimSandboxCount,
			Scope:     models.ScopeRunning,
			Limit:     1,
		}}},
	}
}

func runningSandbox(now time.Time, owner, lock string, age time.Duration, cpuMilli, memoryMi int64, paused bool) *agentsv1alpha1.Sandbox {
	sbx := &agentsv1alpha1.Sandbox{
		ObjectMeta: metav1.ObjectMeta{
			Name:              lock,
			CreationTimestamp: metav1.NewTime(now.Add(-age)),
			Annotations: map[string]string{
				agentsv1alpha1.AnnotationOwner: owner,
				agentsv1alpha1.AnnotationLock:  lock,
			},
		},
		Spec: agentsv1alpha1.SandboxSpec{
			Paused: paused,
		},
		Status: agentsv1alpha1.SandboxStatus{Phase: agentsv1alpha1.SandboxRunning},
	}
	sbx.Spec.Template = &corev1.PodTemplateSpec{
		Spec: corev1.PodSpec{
			Containers: []corev1.Container{{
				Resources: corev1.ResourceRequirements{
					Limits: corev1.ResourceList{
						corev1.ResourceCPU:    *resource.NewMilliQuantity(cpuMilli, resource.DecimalSI),
						corev1.ResourceMemory: *resource.NewQuantity(memoryMi*1024*1024, resource.BinarySI),
					},
				},
			}},
		},
	}
	return sbx
}

func terminatingSandbox(now time.Time, owner, lock string) *agentsv1alpha1.Sandbox {
	sbx := runningSandbox(now, owner, lock, 30*time.Minute, 0, 0, false)
	sbx.Status.Phase = agentsv1alpha1.SandboxTerminating
	return sbx
}

func entryForSandbox(sbx *agentsv1alpha1.Sandbox) Entry {
	return Entry{
		Footprint: FootprintOf(sbx),
		Scopes:    ConditionalScopesOf(sbx),
	}
}
