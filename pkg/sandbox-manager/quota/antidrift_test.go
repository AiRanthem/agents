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
	"github.com/prometheus/client_golang/prometheus/testutil"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	toolscache "k8s.io/client-go/tools/cache"

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
	limited  []*models.CreatedTeamAPIKey
	byID     map[string]*models.CreatedTeamAPIKey
	err      error
	loadByID func(string)
}

func (s *fakeKeyStore) ListLimited(context.Context) ([]*models.CreatedTeamAPIKey, error) {
	if s.err != nil {
		return nil, s.err
	}
	return s.limited, nil
}

func (s *fakeKeyStore) LoadByID(_ context.Context, id string) (*models.CreatedTeamAPIKey, bool) {
	if s.loadByID != nil {
		s.loadByID(id)
	}
	if s.byID == nil {
		return nil, false
	}
	key, ok := s.byID[id]
	return key, ok
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
	mu                  sync.Mutex
	acquireCalls        []acquireCall
	releaseCalls        []releaseCall
	acquireTimeouts     []time.Duration
	releaseTimeouts     []time.Duration
	entriesByKey        map[string]map[string]Entry
	acquireErrByLock    map[string]error
	releaseErrByLock    map[string]error
	listEntriesErrByKey map[string]error
	afterListEntries    func()
	listEntriesCalls    atomic.Int64
}

func (b *fakeBackend) Acquire(ctx context.Context, p AcquireParams) error {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.acquireCalls = append(b.acquireCalls, acquireCall{params: p})
	if deadline, ok := ctx.Deadline(); ok {
		b.acquireTimeouts = append(b.acquireTimeouts, time.Until(deadline))
	}
	if err := b.acquireErrByLock[p.LockString]; err != nil {
		return err
	}
	return nil
}

func (b *fakeBackend) Release(ctx context.Context, apiKeyID, lockString string) error {
	b.mu.Lock()
	defer b.mu.Unlock()
	if deadline, ok := ctx.Deadline(); ok {
		b.releaseTimeouts = append(b.releaseTimeouts, time.Until(deadline))
	}
	if err := b.releaseErrByLock[lockString]; err != nil {
		return err
	}
	b.releaseCalls = append(b.releaseCalls, releaseCall{apiKeyID: apiKeyID, lockString: lockString})
	return nil
}

func (b *fakeBackend) ListEntries(_ context.Context, apiKeyID string) (map[string]Entry, error) {
	b.listEntriesCalls.Add(1)
	if err := b.listEntriesErrByKey[apiKeyID]; err != nil {
		return nil, err
	}
	if b.entriesByKey == nil || b.entriesByKey[apiKeyID] == nil {
		if b.afterListEntries != nil {
			b.afterListEntries()
		}
		return map[string]Entry{}, nil
	}
	got := make(map[string]Entry, len(b.entriesByKey[apiKeyID]))
	for lockString, entry := range b.entriesByKey[apiKeyID] {
		got[lockString] = entry
	}
	if b.afterListEntries != nil {
		b.afterListEntries()
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
			name:        "fresh CR under grace with missing entry charged immediately",
			liveCRs:     []*agentsv1alpha1.Sandbox{runningSandbox(now, owner, "l2", time.Minute, 250, 128, false)},
			healthy:     true,
			wantCharged: []string{"l2"},
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
	otherOwner := uuid.NewSHA1(uuid.Nil, []byte("owner-event-other")).String()

	tests := []struct {
		name          string
		limitedOwners []string
		sbx           *agentsv1alpha1.Sandbox
		healthy       bool
		wantCharged   []string
		wantReleased  []string
	}{
		{
			name:          "live sandbox acquired with predicate data",
			limitedOwners: []string{owner},
			sbx:           runningSandbox(now, owner, "lock-live", 30*time.Minute, 500, 256, false),
			healthy:       true,
			wantCharged:   []string{"lock-live"},
		},
		{
			name:          "not live sandbox released when cache healthy",
			limitedOwners: []string{owner},
			sbx:           terminatingSandbox(now, owner, "lock-dead"),
			healthy:       true,
			wantReleased:  []string{"lock-dead"},
		},
		{
			name:          "not live sandbox release skipped when cache unhealthy",
			limitedOwners: []string{owner},
			sbx:           terminatingSandbox(now, owner, "lock-skipped"),
			healthy:       false,
		},
		{
			name:          "owner not in limited set skipped",
			limitedOwners: []string{otherOwner},
			sbx:           runningSandbox(now, owner, "lock-unlimited", 30*time.Minute, 500, 256, false),
			healthy:       true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			backend := &fakeBackend{}
			limited := make([]*models.CreatedTeamAPIKey, 0, len(tt.limitedOwners))
			for _, limitedOwner := range tt.limitedOwners {
				limited = append(limited, limitedKey(limitedOwner))
			}
			driver := NewAntiDriftDriver(
				AntiDriftConfig{Interval: time.Hour, Grace: 10 * time.Minute},
				newMutablePrimary(true),
				&fakeKeyStore{limited: limited},
				&fakeLiveSandboxCache{
					healthy:     tt.healthy,
					liveByOwner: map[string][]*agentsv1alpha1.Sandbox{},
				},
				backend,
			)
			require.NoError(t, driver.RunOnce(context.Background()))
			backend.resetCalls()

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

func TestAntiDriftAcquiresMissingLiveEntryWithoutGrace(t *testing.T) {
	now := time.Date(2026, 6, 24, 12, 0, 0, 0, time.UTC)
	owner := uuid.NewString()
	key := limitedKey(owner)
	sb := runningSandbox(now, owner, "lock-1", time.Minute, 1000, 512, false)
	cache := &fakeLiveSandboxCache{
		liveByOwner: map[string][]*agentsv1alpha1.Sandbox{owner: {sb}},
		healthy:     true,
	}
	backend := &fakeBackend{entriesByKey: map[string]map[string]Entry{owner: {}}}
	driver := NewAntiDriftDriver(
		AntiDriftConfig{Grace: 10 * time.Minute},
		newMutablePrimary(true),
		&fakeKeyStore{limited: []*models.CreatedTeamAPIKey{key}},
		cache,
		backend,
	)
	driver.now = func() time.Time { return now }

	require.NoError(t, driver.RunOnce(context.Background()))
	require.Equal(t, []string{"lock-1"}, backend.acquireLockstrings())
}

func TestAntiDriftStopsCycleWhenPrimaryLost(t *testing.T) {
	now := time.Now()
	owner1 := uuid.NewString()
	owner2 := uuid.NewString()
	primary := newMutablePrimary(true)
	keys := &fakeKeyStore{limited: []*models.CreatedTeamAPIKey{
		limitedKey(owner1),
		limitedKey(owner2),
	}}
	cache := &fakeLiveSandboxCache{
		liveByOwner: map[string][]*agentsv1alpha1.Sandbox{
			owner1: {runningSandbox(now, owner1, "lock-1", time.Hour, 1000, 512, false)},
			owner2: {runningSandbox(now, owner2, "lock-2", time.Hour, 1000, 512, false)},
		},
		healthy: true,
	}
	backend := &fakeBackend{entriesByKey: map[string]map[string]Entry{owner1: {}, owner2: {}}}
	// Lose leadership right after the first ListEntries; the re-check before
	// Acquire must abort the cycle before any Redis write.
	backend.afterListEntries = func() { primary.SetPrimary(false) }
	driver := NewAntiDriftDriver(AntiDriftConfig{Grace: time.Minute}, primary, keys, cache, backend)

	require.NoError(t, driver.RunOnce(context.Background()))
	require.Empty(t, backend.acquireLockstrings())
}

func TestAntiDriftEventReconcileLooksUpUnknownLimitedOwner(t *testing.T) {
	now := time.Now()
	key := limitedKey(uuid.NewString())
	sb := runningSandbox(now, key.ID.String(), "lock-1", time.Hour, 1000, 512, false)
	backend := &fakeBackend{}
	driver := NewAntiDriftDriver(
		AntiDriftConfig{Interval: time.Hour, Grace: 10 * time.Minute},
		newMutablePrimary(true),
		&fakeKeyStore{byID: map[string]*models.CreatedTeamAPIKey{key.ID.String(): key}},
		&fakeLiveSandboxCache{healthy: true},
		backend,
	)

	driver.reconcileSandboxEvent(sb, false)

	calls := backend.acquireCallsSnapshot()
	require.Len(t, calls, 1)
	assert.Equal(t, key.ID.String(), calls[0].params.APIKeyID)
	assert.Equal(t, "lock-1", calls[0].params.LockString)
}

func TestAntiDriftEventReconcileSkipsWriteWhenPrimaryLostBeforeWrite(t *testing.T) {
	now := time.Now()

	tests := []struct {
		name             string
		sbx              *agentsv1alpha1.Sandbox
		cache            *fakeLiveSandboxCache
		reconcile        func(*AntiDriftDriver, *agentsv1alpha1.Sandbox)
		wantAcquireCalls int
		wantReleaseCalls int
	}{
		{
			name: "before acquire",
			sbx:  runningSandbox(now, uuid.NewString(), "lock-acquire", time.Hour, 1000, 512, false),
			cache: &fakeLiveSandboxCache{
				healthy: true,
			},
			reconcile: func(driver *AntiDriftDriver, sbx *agentsv1alpha1.Sandbox) {
				driver.reconcileSandboxEvent(sbx, false)
			},
		},
		{
			name: "before release",
			sbx:  terminatingSandbox(now, uuid.NewString(), "lock-release"),
			cache: &fakeLiveSandboxCache{
				healthy: true,
			},
			reconcile: func(driver *AntiDriftDriver, sbx *agentsv1alpha1.Sandbox) {
				driver.reconcileSandboxEvent(sbx, false)
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			owner := tt.sbx.GetAnnotations()[agentsv1alpha1.AnnotationOwner]
			key := limitedKey(owner)
			primary := newMutablePrimary(true)
			keyStore := &fakeKeyStore{
				byID: map[string]*models.CreatedTeamAPIKey{
					owner: key,
				},
				loadByID: func(string) {
					primary.SetPrimary(false)
				},
			}
			backend := &fakeBackend{}
			driver := NewAntiDriftDriver(
				AntiDriftConfig{Interval: time.Hour, Grace: time.Minute},
				primary,
				keyStore,
				tt.cache,
				backend,
			)
			driver.seenLeaked[leakedKey(owner, "stale-lock")] = leakedObservation{firstSeen: now, confirmed: true}

			beforeSkipped := testutil.ToFloat64(antiDriftSkippedTotal.WithLabelValues("not_primary"))

			tt.reconcile(driver, tt.sbx)

			assert.Len(t, backend.acquireCallsSnapshot(), tt.wantAcquireCalls)
			assert.Len(t, backend.releaseLockstrings(), tt.wantReleaseCalls)
			assert.Empty(t, driver.seenLeaked)
			assert.Equal(t, beforeSkipped+1, testutil.ToFloat64(antiDriftSkippedTotal.WithLabelValues("not_primary")))
		})
	}
}

func TestAntiDriftDriver_DeleteEventReleasesTombstone(t *testing.T) {
	now := time.Now()
	key := limitedKey(uuid.NewString())
	sb := runningSandbox(now, key.ID.String(), "lock-1", time.Hour, 1000, 512, false)
	tests := []struct {
		name string
		obj  any
	}{
		{
			name: "direct sandbox delete object",
			obj:  sb,
		},
		{
			name: "deleted final state unknown",
			obj: toolscache.DeletedFinalStateUnknown{
				Key: "default/sbx",
				Obj: sb,
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			backend := &fakeBackend{}
			keys := &fakeKeyStore{
				byID: map[string]*models.CreatedTeamAPIKey{
					key.ID.String(): key,
				},
			}
			cache := &fakeLiveSandboxCache{healthy: true}
			driver := NewAntiDriftDriver(AntiDriftConfig{}, nil, keys, cache, backend)

			handler := driver.SandboxEventHandler()
			handler.OnDelete(tt.obj)

			require.Equal(t, []string{"lock-1"}, backend.releaseLockstrings())
			require.Empty(t, backend.acquireCallsSnapshot())
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

func TestAntiDriftUnhealthyReleasePassDoesNotConfirmLeakedEntry(t *testing.T) {
	key := limitedKey(uuid.NewString())
	backend := &fakeBackend{entriesByKey: map[string]map[string]Entry{
		key.ID.String(): {"leaked-lock": {}},
	}}
	liveCache := &fakeLiveSandboxCache{healthy: false}
	driver := NewAntiDriftDriver(
		AntiDriftConfig{Interval: time.Hour, Grace: 10 * time.Minute},
		newMutablePrimary(true),
		&fakeKeyStore{limited: []*models.CreatedTeamAPIKey{key}},
		liveCache,
		backend,
	)
	now := time.Unix(1000, 0)
	driver.now = func() time.Time { return now }

	require.NoError(t, driver.RunOnce(context.Background()))
	assert.Empty(t, backend.releaseLockstrings())

	liveCache.healthy = true
	now = now.Add(11 * time.Minute)
	require.NoError(t, driver.RunOnce(context.Background()))
	assert.Empty(t, backend.releaseLockstrings(), "unhealthy pass must not count as the previous successful confirmation")
}

func TestAntiDriftKeyStoreErrorDoesNotCountAsPreviousPass(t *testing.T) {
	now := time.Date(2026, 6, 23, 12, 0, 0, 0, time.UTC)
	owner := uuid.NewSHA1(uuid.Nil, []byte("owner-key-store-error")).String()
	keyStore := &fakeKeyStore{limited: []*models.CreatedTeamAPIKey{limitedKey(owner)}}
	backend := &fakeBackend{entriesByKey: map[string]map[string]Entry{
		owner: {"lock-1": {}},
	}}
	driver := NewAntiDriftDriver(
		AntiDriftConfig{Interval: time.Hour, Grace: 10 * time.Minute},
		newMutablePrimary(true),
		keyStore,
		&fakeLiveSandboxCache{healthy: true},
		backend,
	)
	currentNow := now
	driver.now = func() time.Time { return currentNow }

	require.NoError(t, driver.RunOnce(context.Background()))
	require.Len(t, driver.seenLeaked, 1)

	currentNow = currentNow.Add(11 * time.Minute)
	keyStore.err = errors.New("boom")
	require.NoError(t, driver.RunOnce(context.Background()))

	keyStore.err = nil
	require.NoError(t, driver.RunOnce(context.Background()))
	assert.Empty(t, backend.releaseLockstrings())
}

func TestAntiDriftListEntriesErrorDoesNotCountAsPreviousPass(t *testing.T) {
	now := time.Date(2026, 6, 23, 12, 0, 0, 0, time.UTC)
	owner := uuid.NewSHA1(uuid.Nil, []byte("owner-list-entries-error")).String()
	backend := &fakeBackend{
		entriesByKey: map[string]map[string]Entry{
			owner: {"lock-1": {}},
		},
	}
	driver := NewAntiDriftDriver(
		AntiDriftConfig{Interval: time.Hour, Grace: 10 * time.Minute},
		newMutablePrimary(true),
		&fakeKeyStore{limited: []*models.CreatedTeamAPIKey{limitedKey(owner)}},
		&fakeLiveSandboxCache{healthy: true},
		backend,
	)
	currentNow := now
	driver.now = func() time.Time { return currentNow }

	require.NoError(t, driver.RunOnce(context.Background()))
	require.Len(t, driver.seenLeaked, 1)

	currentNow = currentNow.Add(11 * time.Minute)
	backend.listEntriesErrByKey = map[string]error{owner: errors.New("boom")}
	require.ErrorContains(t, driver.RunOnce(context.Background()), "boom")

	backend.listEntriesErrByKey = nil
	require.NoError(t, driver.RunOnce(context.Background()))
	assert.Empty(t, backend.releaseLockstrings())
}

func TestAntiDriftReleaseErrorDoesNotCountAsPreviousPass(t *testing.T) {
	now := time.Date(2026, 6, 23, 12, 0, 0, 0, time.UTC)
	owner := uuid.NewSHA1(uuid.Nil, []byte("owner-release-error")).String()
	backend := &fakeBackend{
		entriesByKey: map[string]map[string]Entry{
			owner: {"lock-1": {}},
		},
	}
	driver := NewAntiDriftDriver(
		AntiDriftConfig{Interval: time.Hour, Grace: 10 * time.Minute},
		newMutablePrimary(true),
		&fakeKeyStore{limited: []*models.CreatedTeamAPIKey{limitedKey(owner)}},
		&fakeLiveSandboxCache{healthy: true},
		backend,
	)
	currentNow := now
	driver.now = func() time.Time { return currentNow }

	require.NoError(t, driver.RunOnce(context.Background()))

	currentNow = currentNow.Add(11 * time.Minute)
	backend.releaseErrByLock = map[string]error{"lock-1": errors.New("release failed")}
	require.ErrorContains(t, driver.RunOnce(context.Background()), "release failed")

	backend.releaseErrByLock = nil
	require.NoError(t, driver.RunOnce(context.Background()))
	assert.Equal(t, []string{"lock-1"}, backend.releaseLockstrings())
}

func TestAntiDriftAcquireErrorDoesNotResetUnrelatedLeakedConfirmation(t *testing.T) {
	now := time.Date(2026, 6, 23, 12, 0, 0, 0, time.UTC)
	owner := uuid.NewSHA1(uuid.Nil, []byte("owner-acquire-error")).String()
	live := runningSandbox(now, owner, "live-bad", 30*time.Minute, 250, 128, false)
	backend := &fakeBackend{
		entriesByKey: map[string]map[string]Entry{
			owner: {"leaked-ok": {}},
		},
		acquireErrByLock: map[string]error{"live-bad": errors.New("bad footprint")},
	}
	driver := NewAntiDriftDriver(
		AntiDriftConfig{Interval: time.Hour, Grace: 10 * time.Minute},
		newMutablePrimary(true),
		&fakeKeyStore{limited: []*models.CreatedTeamAPIKey{limitedKey(owner)}},
		&fakeLiveSandboxCache{
			healthy:     true,
			liveByOwner: map[string][]*agentsv1alpha1.Sandbox{owner: {live}},
		},
		backend,
	)
	currentNow := now
	driver.now = func() time.Time { return currentNow }

	require.ErrorContains(t, driver.RunOnce(context.Background()), "bad footprint")
	currentNow = currentNow.Add(11 * time.Minute)
	require.ErrorContains(t, driver.RunOnce(context.Background()), "bad footprint")
	assert.Equal(t, []string{"leaked-ok"}, backend.releaseLockstrings())
}

func TestEntriesEqualNormalizesLiveEntry(t *testing.T) {
	tests := []struct {
		name string
		have Entry
		want Entry
	}{
		{
			name: "nil and empty scopes",
			have: Entry{Scopes: nil},
			want: Entry{Scopes: []models.QuotaScope{}},
		},
		{
			name: "missing and explicit zero footprint dimensions",
			have: Entry{Footprint: map[models.QuotaDimension]int64{models.DimLimitsCPU: 250}},
			want: Entry{Footprint: map[models.QuotaDimension]int64{
				models.DimLimitsCPU:    250,
				models.DimLimitsMemory: 0,
			}},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.True(t, entriesEqual(tt.have, tt.want))
		})
	}
}

func TestAntiDriftEventReconcileUsesShortDeadline(t *testing.T) {
	now := time.Date(2026, 6, 23, 12, 0, 0, 0, time.UTC)
	owner := uuid.NewSHA1(uuid.Nil, []byte("owner-event-deadline")).String()

	tests := []struct {
		name        string
		sbx         *agentsv1alpha1.Sandbox
		timeoutFunc func(*fakeBackend) []time.Duration
	}{
		{
			name: "acquire",
			sbx:  runningSandbox(now, owner, "lock-live", 30*time.Minute, 250, 128, false),
			timeoutFunc: func(backend *fakeBackend) []time.Duration {
				return backend.acquireTimeoutsSnapshot()
			},
		},
		{
			name: "release",
			sbx:  terminatingSandbox(now, owner, "lock-dead"),
			timeoutFunc: func(backend *fakeBackend) []time.Duration {
				return backend.releaseTimeoutsSnapshot()
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			backend := &fakeBackend{}
			driver := NewAntiDriftDriver(
				AntiDriftConfig{Interval: time.Hour, Grace: 10 * time.Minute, CycleTimeout: 30 * time.Second},
				newMutablePrimary(true),
				&fakeKeyStore{limited: []*models.CreatedTeamAPIKey{limitedKey(owner)}},
				&fakeLiveSandboxCache{
					healthy:     true,
					liveByOwner: map[string][]*agentsv1alpha1.Sandbox{},
				},
				backend,
			)
			require.NoError(t, driver.RunOnce(context.Background()))
			backend.resetCalls()

			driver.SandboxEventHandler().OnUpdate(nil, tt.sbx)
			timeouts := tt.timeoutFunc(backend)
			require.Len(t, timeouts, 1)
			assert.Less(t, timeouts[0], 3*time.Second)
			assert.Greater(t, timeouts[0], time.Second)
		})
	}
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

func TestAntiDriftRunExecutesInitialCycleBeforeInterval(t *testing.T) {
	owner := uuid.NewSHA1(uuid.Nil, []byte("owner-startup-cycle")).String()
	backend := &fakeBackend{}
	driver := NewAntiDriftDriver(
		AntiDriftConfig{Interval: time.Hour, Grace: time.Minute},
		newMutablePrimary(true),
		&fakeKeyStore{limited: []*models.CreatedTeamAPIKey{limitedKey(owner)}},
		&fakeLiveSandboxCache{
			healthy:     true,
			liveByOwner: map[string][]*agentsv1alpha1.Sandbox{owner: nil},
		},
		backend,
	)
	ctx, cancel := context.WithCancel(context.Background())
	t.Cleanup(cancel)

	driver.Run(ctx)
	require.Eventually(t, func() bool {
		return backend.listEntriesCalls.Load() > 0
	}, 100*time.Millisecond, 10*time.Millisecond)

	cancel()
	driver.Stop()
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

func (b *fakeBackend) acquireCallsSnapshot() []acquireCall {
	b.mu.Lock()
	defer b.mu.Unlock()
	return append([]acquireCall(nil), b.acquireCalls...)
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

func (b *fakeBackend) acquireTimeoutsSnapshot() []time.Duration {
	b.mu.Lock()
	defer b.mu.Unlock()
	return append([]time.Duration(nil), b.acquireTimeouts...)
}

func (b *fakeBackend) releaseTimeoutsSnapshot() []time.Duration {
	b.mu.Lock()
	defer b.mu.Unlock()
	return append([]time.Duration(nil), b.releaseTimeouts...)
}

func (b *fakeBackend) resetCalls() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.acquireCalls = nil
	b.releaseCalls = nil
	b.acquireTimeouts = nil
	b.releaseTimeouts = nil
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
