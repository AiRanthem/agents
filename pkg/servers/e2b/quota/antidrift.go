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
	"reflect"
	"sync"
	"time"

	toolscache "k8s.io/client-go/tools/cache"
	"k8s.io/klog/v2"

	agentsv1alpha1 "github.com/openkruise/agents/api/v1alpha1"
	cachepkg "github.com/openkruise/agents/pkg/cache"
)

type AntiDriftConfig struct {
	Interval     time.Duration
	Grace        time.Duration
	CycleTimeout time.Duration
}

type leakedObservation struct {
	firstSeen time.Time
	confirmed bool
}

type AntiDriftDriver struct {
	cfg     AntiDriftConfig
	primary PrimaryChecker
	keys    LimitedKeyStore
	cache   LiveSandboxCache
	backend Backend

	mu            sync.Mutex
	registration  cachepkg.SandboxEventHandlerRegistration
	runDone       chan struct{}
	cycleCancel   context.CancelFunc
	seenLeaked    map[string]leakedObservation
	limitedOwners map[string]struct{}
	stopped       bool
	now           func() time.Time

	runOnce  sync.Once
	stopOnce sync.Once
	stopCh   chan struct{}
}

func NewAntiDriftDriver(cfg AntiDriftConfig, primary PrimaryChecker, keys LimitedKeyStore, liveCache LiveSandboxCache, backend Backend) *AntiDriftDriver {
	if cfg.Interval <= 0 {
		cfg.Interval = 5 * time.Minute
	}
	if cfg.Grace <= 0 {
		cfg.Grace = 10 * time.Minute
	}
	if cfg.CycleTimeout <= 0 {
		cfg.CycleTimeout = 30 * time.Second
	}
	return &AntiDriftDriver{
		cfg:           cfg,
		primary:       primary,
		keys:          keys,
		cache:         liveCache,
		backend:       backend,
		seenLeaked:    map[string]leakedObservation{},
		limitedOwners: map[string]struct{}{},
		now:           time.Now,
		stopCh:        make(chan struct{}),
	}
}

func (d *AntiDriftDriver) SetEventRegistration(reg cachepkg.SandboxEventHandlerRegistration) {
	if d == nil {
		return
	}
	d.mu.Lock()
	if d.stopped {
		d.mu.Unlock()
		if reg != nil {
			_ = reg.Remove()
		}
		return
	}
	d.registration = reg
	d.mu.Unlock()
}

func (d *AntiDriftDriver) Run(ctx context.Context) {
	if d == nil {
		return
	}

	d.runOnce.Do(func() {
		d.mu.Lock()
		if d.stopped {
			d.mu.Unlock()
			return
		}
		d.runDone = make(chan struct{})
		d.mu.Unlock()

		go func() {
			defer close(d.runDone)
			d.runLoop(ctx)
		}()
	})
}

func (d *AntiDriftDriver) runLoop(ctx context.Context) {
	ticker := time.NewTicker(d.cfg.Interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-d.stopCh:
			return
		case <-ticker.C:
			cycleCtx, cancel := context.WithTimeout(ctx, d.cycleTimeout())
			if !d.setCycleCancel(cancel) {
				cancel()
				continue
			}
			if err := d.RunOnce(cycleCtx); err != nil && !errors.Is(err, context.Canceled) && !errors.Is(err, context.DeadlineExceeded) {
				klog.FromContext(ctx).Error(err, "quota anti-drift cycle failed")
			}
			d.clearCycleCancel()
			cancel()
		}
	}
}

func (d *AntiDriftDriver) RunOnce(ctx context.Context) error {
	if d == nil {
		return nil
	}
	if d.primary != nil && !d.primary.IsPrimary() {
		antiDriftSkippedTotal.WithLabelValues("not_primary").Inc()
		d.clearLeaked()
		return nil
	}
	if d.keys == nil || d.cache == nil || d.backend == nil {
		antiDriftSkippedTotal.WithLabelValues("not_ready").Inc()
		return nil
	}

	limitedKeys, err := d.keys.ListLimited(ctx)
	if err != nil {
		antiDriftSkippedTotal.WithLabelValues("key_store_error").Inc()
		d.clearLeaked()
		return nil
	}
	limitedOwners := map[string]struct{}{}
	for _, key := range limitedKeys {
		if key == nil || key.QuotaSpec == nil || !key.QuotaSpec.IsLimited() {
			continue
		}
		limitedOwners[key.ID.String()] = struct{}{}
	}
	d.replaceLimitedOwners(limitedOwners)

	healthy := d.cache.SandboxInformerHealthy()
	now := d.now()
	var firstErr error
	for _, key := range limitedKeys {
		if err := ctx.Err(); err != nil {
			return err
		}
		if key == nil || key.QuotaSpec == nil || !key.QuotaSpec.IsLimited() {
			continue
		}

		apiKeyID := key.ID.String()
		liveSandboxes, err := d.cache.ListLiveSandboxesByOwner(ctx, apiKeyID)
		if err != nil {
			antiDriftErrorsTotal.WithLabelValues("list_live").Inc()
			d.clearLeakedForKey(apiKeyID)
			if firstErr == nil {
				firstErr = err
			}
			continue
		}

		haveEntries, err := d.backend.ListEntries(ctx, apiKeyID)
		if err != nil {
			antiDriftErrorsTotal.WithLabelValues("list_entries").Inc()
			d.clearLeakedForKey(apiKeyID)
			if firstErr == nil {
				firstErr = err
			}
			continue
		}

		liveLocks := make(map[string]struct{}, len(liveSandboxes))
		nextLeaked := map[string]leakedObservation{}
		keyFailed := false
		for _, sbx := range liveSandboxes {
			lockString := lockStringOf(sbx)
			if lockString == "" {
				continue
			}
			liveLocks[lockString] = struct{}{}

			want := liveEntryForSandbox(sbx)
			have, ok := haveEntries[lockString]
			if ok {
				if entriesEqual(have, want) {
					continue
				}
			} else if !sandboxOlderThan(sbx, now, d.cfg.Grace) {
				continue
			}

			if err := d.backend.Acquire(ctx, AcquireParams{
				APIKeyID:   apiKeyID,
				LockString: lockString,
				Footprint:  want.Footprint,
				Scopes:     want.Scopes,
				Enforce:    false,
				Limits:     key.QuotaSpec.LimitedPairs(),
			}); err != nil {
				antiDriftErrorsTotal.WithLabelValues("acquire").Inc()
				keyFailed = true
				if firstErr == nil {
					firstErr = err
				}
			}
		}

		for lockString := range haveEntries {
			if _, ok := liveLocks[lockString]; ok {
				continue
			}

			obs := d.leakedObservation(apiKeyID, lockString)
			if obs.firstSeen.IsZero() {
				obs.firstSeen = now
			}
			seenPreviousSuccessfulPass := obs.confirmed
			obs.confirmed = true
			nextLeaked[lockString] = obs

			if !seenPreviousSuccessfulPass || now.Sub(obs.firstSeen) < d.cfg.Grace || !healthy {
				continue
			}
			if err := d.backend.Release(ctx, apiKeyID, lockString); err != nil {
				antiDriftErrorsTotal.WithLabelValues("release").Inc()
				keyFailed = true
				if firstErr == nil {
					firstErr = err
				}
				continue
			}
			delete(nextLeaked, lockString)
		}

		if keyFailed {
			for lockString, obs := range nextLeaked {
				obs.confirmed = false
				nextLeaked[lockString] = obs
			}
		}
		d.replaceLeakedForKey(apiKeyID, nextLeaked)
	}

	return firstErr
}

func (d *AntiDriftDriver) SandboxEventHandler() toolscache.ResourceEventHandler {
	return toolscache.ResourceEventHandlerFuncs{
		AddFunc: func(obj any) {
			d.reconcileSandboxEvent(sandboxFromEvent(obj))
		},
		UpdateFunc: func(_, newObj any) {
			d.reconcileSandboxEvent(sandboxFromEvent(newObj))
		},
		DeleteFunc: func(obj any) {
			d.reconcileSandboxEvent(sandboxFromEvent(obj))
		},
	}
}

func (d *AntiDriftDriver) Stop() {
	if d == nil {
		return
	}

	d.stopOnce.Do(func() {
		d.mu.Lock()
		d.stopped = true
		registration := d.registration
		d.registration = nil
		d.seenLeaked = map[string]leakedObservation{}
		d.limitedOwners = map[string]struct{}{}
		done := d.runDone
		cycleCancel := d.cycleCancel
		close(d.stopCh)
		d.mu.Unlock()

		if cycleCancel != nil {
			cycleCancel()
		}
		if registration != nil {
			_ = registration.Remove()
		}
		if done != nil {
			<-done
		}
	})
}

func (d *AntiDriftDriver) cycleTimeout() time.Duration {
	timeout := d.cfg.CycleTimeout
	if d.cfg.Interval < timeout {
		timeout = d.cfg.Interval
	}
	return timeout
}

func (d *AntiDriftDriver) setCycleCancel(cancel context.CancelFunc) bool {
	d.mu.Lock()
	defer d.mu.Unlock()
	if d.stopped {
		return false
	}
	d.cycleCancel = cancel
	return true
}

func (d *AntiDriftDriver) clearCycleCancel() {
	d.mu.Lock()
	defer d.mu.Unlock()
	d.cycleCancel = nil
}

func (d *AntiDriftDriver) reconcileSandboxEvent(sbx *agentsv1alpha1.Sandbox) {
	if d == nil || sbx == nil || d.backend == nil {
		return
	}
	if d.primary != nil && !d.primary.IsPrimary() {
		antiDriftSkippedTotal.WithLabelValues("not_primary").Inc()
		return
	}

	apiKeyID := sbx.GetAnnotations()[agentsv1alpha1.AnnotationOwner]
	lockString := lockStringOf(sbx)
	if apiKeyID == "" || lockString == "" {
		return
	}
	if !d.isKnownLimited(apiKeyID) {
		return
	}

	ctx, cancel := context.WithTimeout(context.Background(), d.cycleTimeout())
	defer cancel()

	if !IsLiveForQuota(sbx) {
		if d.cache == nil || !d.cache.SandboxInformerHealthy() {
			antiDriftEventReleaseTotal.WithLabelValues("skipped_unhealthy").Inc()
			return
		}
		if err := d.backend.Release(ctx, apiKeyID, lockString); err != nil {
			antiDriftErrorsTotal.WithLabelValues("event_release").Inc()
			antiDriftEventReleaseTotal.WithLabelValues("error").Inc()
			return
		}
		antiDriftEventReleaseTotal.WithLabelValues("released").Inc()
		return
	}

	if err := d.backend.Acquire(ctx, AcquireParams{
		APIKeyID:   apiKeyID,
		LockString: lockString,
		Footprint:  FootprintOf(sbx),
		Scopes:     ConditionalScopesOf(sbx),
		Enforce:    false,
	}); err != nil {
		antiDriftErrorsTotal.WithLabelValues("event_acquire").Inc()
	}
}

func (d *AntiDriftDriver) clearLeaked() {
	d.mu.Lock()
	defer d.mu.Unlock()
	clear(d.seenLeaked)
}

func (d *AntiDriftDriver) replaceLimitedOwners(limitedOwners map[string]struct{}) {
	d.mu.Lock()
	defer d.mu.Unlock()
	d.limitedOwners = limitedOwners
}

func (d *AntiDriftDriver) isKnownLimited(apiKeyID string) bool {
	d.mu.Lock()
	defer d.mu.Unlock()
	_, ok := d.limitedOwners[apiKeyID]
	return ok
}

func (d *AntiDriftDriver) leakedObservation(apiKeyID, lockString string) leakedObservation {
	d.mu.Lock()
	defer d.mu.Unlock()
	return d.seenLeaked[leakedKey(apiKeyID, lockString)]
}

func (d *AntiDriftDriver) clearLeakedForKey(apiKeyID string) {
	d.mu.Lock()
	defer d.mu.Unlock()
	prefix := apiKeyID + "\x00"
	for key := range d.seenLeaked {
		if len(key) >= len(prefix) && key[:len(prefix)] == prefix {
			delete(d.seenLeaked, key)
		}
	}
}

func (d *AntiDriftDriver) replaceLeakedForKey(apiKeyID string, leaked map[string]leakedObservation) {
	d.mu.Lock()
	defer d.mu.Unlock()
	prefix := apiKeyID + "\x00"
	for key := range d.seenLeaked {
		if len(key) >= len(prefix) && key[:len(prefix)] == prefix {
			delete(d.seenLeaked, key)
		}
	}
	for lockString, obs := range leaked {
		d.seenLeaked[leakedKey(apiKeyID, lockString)] = obs
	}
}

func leakedKey(apiKeyID, lockString string) string {
	return apiKeyID + "\x00" + lockString
}

func sandboxFromEvent(obj any) *agentsv1alpha1.Sandbox {
	switch v := obj.(type) {
	case *agentsv1alpha1.Sandbox:
		return v
	case toolscache.DeletedFinalStateUnknown:
		sbx, _ := v.Obj.(*agentsv1alpha1.Sandbox)
		return sbx
	default:
		return nil
	}
}

func lockStringOf(sbx *agentsv1alpha1.Sandbox) string {
	if sbx == nil {
		return ""
	}
	return sbx.GetAnnotations()[agentsv1alpha1.AnnotationLock]
}

func sandboxOlderThan(sbx *agentsv1alpha1.Sandbox, now time.Time, grace time.Duration) bool {
	if sbx == nil {
		return false
	}
	return now.Sub(sbx.CreationTimestamp.Time) > grace
}

func liveEntryForSandbox(sbx *agentsv1alpha1.Sandbox) Entry {
	return Entry{
		Footprint: FootprintOf(sbx),
		Scopes:    ConditionalScopesOf(sbx),
	}
}

func entriesEqual(have, want Entry) bool {
	return reflect.DeepEqual(have.Footprint, want.Footprint) && reflect.DeepEqual(have.Scopes, want.Scopes)
}
