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
	"sync"
	"time"

	toolscache "k8s.io/client-go/tools/cache"
	"k8s.io/klog/v2"

	agentsv1alpha1 "github.com/openkruise/agents/api/v1alpha1"
	"github.com/openkruise/agents/pkg/cache"
)

const (
	defaultAntiDriftInterval     = 5 * time.Minute
	defaultAntiDriftGrace        = 10 * time.Minute
	defaultAntiDriftCycleTimeout = 30 * time.Second
	eventReleaseTimeout          = 5 * time.Second
)

type AntiDriftConfig struct {
	Interval     time.Duration
	Grace        time.Duration
	CycleTimeout time.Duration
}

type AntiDriftDriver struct {
	cfg     AntiDriftConfig
	primary PrimaryChecker
	keys    LimitedKeyStore
	cache   LiveLockstringCache
	backend Backend

	registrationMu sync.Mutex
	registration   cache.SandboxEventHandlerRegistration
	runOnce        sync.Once
	stopOnce       sync.Once
	stop           chan struct{}
}

func NewAntiDriftDriver(cfg AntiDriftConfig, primary PrimaryChecker, keys LimitedKeyStore, liveCache LiveLockstringCache, backend Backend) *AntiDriftDriver {
	if cfg.Interval <= 0 {
		cfg.Interval = defaultAntiDriftInterval
	}
	if cfg.Grace <= 0 {
		cfg.Grace = defaultAntiDriftGrace
	}
	if cfg.CycleTimeout <= 0 {
		cfg.CycleTimeout = defaultAntiDriftCycleTimeout
	}
	if backend == nil {
		backend = NoopBackend{}
	}
	return &AntiDriftDriver{
		cfg:     cfg,
		primary: primary,
		keys:    keys,
		cache:   liveCache,
		backend: backend,
		stop:    make(chan struct{}),
	}
}

func (d *AntiDriftDriver) SetEventRegistration(reg cache.SandboxEventHandlerRegistration) {
	if d == nil {
		return
	}
	d.registrationMu.Lock()
	defer d.registrationMu.Unlock()
	d.registration = reg
}

func (d *AntiDriftDriver) Run(ctx context.Context) {
	if d == nil {
		return
	}
	d.runOnce.Do(func() {
		go d.runLoop(ctx)
	})
}

func (d *AntiDriftDriver) runLoop(ctx context.Context) {
	ticker := time.NewTicker(d.cfg.Interval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-d.stop:
			return
		case <-ticker.C:
			timeout := d.cfg.CycleTimeout
			if d.cfg.Interval < timeout {
				timeout = d.cfg.Interval
			}
			cycleCtx, cancel := context.WithTimeout(ctx, timeout)
			if err := d.RunOnce(cycleCtx); err != nil {
				klog.FromContext(ctx).Error(err, "quota anti-drift cycle failed")
			}
			cancel()
		}
	}
}

func (d *AntiDriftDriver) Stop() {
	if d == nil {
		return
	}
	d.stopOnce.Do(func() {
		close(d.stop)
		d.registrationMu.Lock()
		defer d.registrationMu.Unlock()
		if d.registration != nil {
			if err := d.registration.Remove(); err != nil {
				klog.Background().Error(err, "remove quota anti-drift event registration")
			}
		}
	})
}

func (d *AntiDriftDriver) RunOnce(ctx context.Context) error {
	if d == nil || !d.isPrimary() {
		return nil
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	if d.keys == nil || d.cache == nil {
		return nil
	}

	now := time.Now()
	keys, err := d.keys.ListLimited(ctx)
	if err != nil {
		antiDriftSkippedTotal.WithLabelValues(antiDriftSkipReasonKeyStoreError).Inc()
		return err
	}

	for _, key := range keys {
		if err := ctx.Err(); err != nil {
			return err
		}
		if key == nil || !key.QuotaSpec.IsLimited() {
			continue
		}
		keyID := key.ID.String()
		live, err := d.cache.ListLiveLockstringsByOwner(ctx, cache.ListLiveLockstringsByOwnerOptions{Owner: keyID})
		if err != nil {
			antiDriftSkippedTotal.WithLabelValues(antiDriftSkipReasonLiveListError).Inc()
			klog.FromContext(ctx).Error(err, "skip quota anti-drift key after live-list error", "apiKeyID", keyID)
			continue
		}

		have, err := d.backend.List(ctx, keyID)
		if err != nil {
			antiDriftSkippedTotal.WithLabelValues(antiDriftSkipReasonBackendListError).Inc()
			klog.FromContext(ctx).Error(err, "skip quota anti-drift key after backend-list error", "apiKeyID", keyID)
			continue
		}

		liveSet := make(map[string]cache.LiveLockstring, len(live))
		for _, entry := range live {
			if err := ctx.Err(); err != nil {
				return err
			}
			if entry.LockString == "" {
				continue
			}
			liveSet[entry.LockString] = entry
			if _, ok := have[entry.LockString]; ok {
				continue
			}
			if now.Sub(entry.CreationTimestamp) <= d.cfg.Grace {
				continue
			}
			if err := d.backend.AddObserved(ctx, keyID, entry.LockString, entry.CreationTimestamp); err != nil {
				if ctxErr := ctx.Err(); ctxErr != nil {
					return ctxErr
				}
				klog.FromContext(ctx).Error(err, "add missing quota live-set entry", "apiKeyID", keyID, "lockString", entry.LockString)
			}
		}

		if !d.cache.RemoveSafe() {
			continue
		}
		for lockString, acquiredAt := range have {
			if err := ctx.Err(); err != nil {
				return err
			}
			if _, ok := liveSet[lockString]; ok {
				continue
			}
			if now.Sub(acquiredAt) <= d.cfg.Grace {
				continue
			}
			if err := d.backend.Release(ctx, keyID, lockString); err != nil {
				if ctxErr := ctx.Err(); ctxErr != nil {
					return ctxErr
				}
				klog.FromContext(ctx).Error(err, "remove stale quota live-set entry", "apiKeyID", keyID, "lockString", lockString)
			}
		}
	}
	return nil
}

func (d *AntiDriftDriver) SandboxEventHandler() toolscache.ResourceEventHandler {
	return toolscache.ResourceEventHandlerFuncs{
		UpdateFunc: func(_, newObj any) {
			ctx, cancel := context.WithTimeout(context.Background(), eventReleaseTimeout)
			defer cancel()
			d.releaseIfNotLive(ctx, newObj)
		},
		DeleteFunc: func(obj any) {
			ctx, cancel := context.WithTimeout(context.Background(), eventReleaseTimeout)
			defer cancel()
			d.releaseDeleted(ctx, obj)
		},
	}
}

func (d *AntiDriftDriver) releaseIfNotLive(ctx context.Context, obj any) {
	sbx, ok := sandboxFromObject(obj)
	if !ok || sbx == nil || sandboxLiveForQuota(sbx) {
		return
	}
	d.releaseSandboxWithProbe(ctx, sbx)
}

func (d *AntiDriftDriver) releaseDeleted(ctx context.Context, obj any) {
	sbx, ok := sandboxFromObject(obj)
	if !ok || sbx == nil {
		return
	}
	d.releaseSandboxWithProbe(ctx, sbx)
}

func (d *AntiDriftDriver) releaseSandboxWithProbe(ctx context.Context, sbx *agentsv1alpha1.Sandbox) {
	annotations := sbx.GetAnnotations()
	d.releaseWithProbe(ctx, annotations[agentsv1alpha1.AnnotationOwner], annotations[agentsv1alpha1.AnnotationLock])
}

func (d *AntiDriftDriver) releaseWithProbe(ctx context.Context, owner, lockString string) {
	if d == nil || !d.isPrimary() {
		antiDriftSkippedTotal.WithLabelValues(antiDriftSkipReasonEventNotPrimary).Inc()
		return
	}
	if owner == "" || lockString == "" {
		antiDriftSkippedTotal.WithLabelValues(antiDriftSkipReasonEventMissingIdentity).Inc()
		return
	}
	if d.cache == nil || !d.cache.RemoveSafe() {
		antiDriftSkippedTotal.WithLabelValues(antiDriftSkipReasonEventRemoveUnsafe).Inc()
		return
	}

	live, err := d.cache.ListLiveLockstringsByOwner(ctx, cache.ListLiveLockstringsByOwnerOptions{Owner: owner})
	if err != nil {
		antiDriftSkippedTotal.WithLabelValues(antiDriftSkipReasonEventProbeError).Inc()
		klog.FromContext(ctx).Error(err, "skip quota event release after live-list probe error", "apiKeyID", owner, "lockString", lockString)
		return
	}
	for _, entry := range live {
		if entry.LockString == lockString {
			antiDriftSkippedTotal.WithLabelValues(antiDriftSkipReasonEventStillLive).Inc()
			return
		}
	}
	if d.backend == nil {
		return
	}
	if err := d.backend.Release(ctx, owner, lockString); err != nil {
		klog.FromContext(ctx).Error(err, "release quota live-set entry from sandbox event", "apiKeyID", owner, "lockString", lockString)
	}
}

func (d *AntiDriftDriver) isPrimary() bool {
	return d != nil && (d.primary == nil || d.primary.IsPrimary())
}

func sandboxFromObject(obj any) (*agentsv1alpha1.Sandbox, bool) {
	switch typed := obj.(type) {
	case *agentsv1alpha1.Sandbox:
		return typed, true
	case agentsv1alpha1.Sandbox:
		return &typed, true
	case toolscache.DeletedFinalStateUnknown:
		return sandboxFromObject(typed.Obj)
	default:
		return nil, false
	}
}

func sandboxLiveForQuota(sbx *agentsv1alpha1.Sandbox) bool {
	return sbx.GetDeletionTimestamp() == nil && sbx.Status.Phase != agentsv1alpha1.SandboxTerminating
}
