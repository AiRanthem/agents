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
	"time"

	toolscache "k8s.io/client-go/tools/cache"
	"k8s.io/klog/v2"

	cachepkg "github.com/openkruise/agents/pkg/cache"
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

	mu           sync.Mutex
	registration cachepkg.SandboxEventHandlerRegistration
	runDone      chan struct{}
	cycleCancel  context.CancelFunc
	stopped      bool

	runOnce  sync.Once
	stopOnce sync.Once
	stopCh   chan struct{}
}

func NewAntiDriftDriver(cfg AntiDriftConfig, primary PrimaryChecker, keys LimitedKeyStore, liveCache LiveLockstringCache, backend Backend) *AntiDriftDriver {
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
		cfg:     cfg,
		primary: primary,
		keys:    keys,
		cache:   liveCache,
		backend: backend,
		stopCh:  make(chan struct{}),
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

func (d *AntiDriftDriver) RunOnce(context.Context) error {
	if d == nil {
		return nil
	}
	if d.primary != nil && !d.primary.IsPrimary() {
		antiDriftSkippedTotal.WithLabelValues("not_primary").Inc()
	}
	return nil
}

func (d *AntiDriftDriver) SandboxEventHandler() toolscache.ResourceEventHandler {
	return toolscache.ResourceEventHandlerFuncs{}
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
