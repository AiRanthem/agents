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
	"fmt"
	"sync"
	"time"
)

const (
	defaultBreakerN = 3
	defaultBreakerD = 30 * time.Second
)

type breakerBackend struct {
	inner Backend
	n     int
	d     time.Duration
	now   func() time.Time

	mu             sync.Mutex
	consecutiveErr int
	openedUntil    time.Time
}

func NewBreakerBackend(inner Backend, n int, d time.Duration) *breakerBackend {
	if n <= 0 {
		n = defaultBreakerN
	}
	if d <= 0 {
		d = defaultBreakerD
	}
	return &breakerBackend{
		inner: inner,
		n:     n,
		d:     d,
		now:   time.Now,
	}
}

func (b *breakerBackend) Acquire(ctx context.Context, p AcquireParams) error {
	if err := b.beforeCall(); err != nil {
		return err
	}
	err := b.inner.Acquire(ctx, p)
	b.afterCall(err)
	return breakerError(err)
}

func (b *breakerBackend) Release(ctx context.Context, apiKeyID, lockString string) error {
	if err := b.beforeCall(); err != nil {
		return err
	}
	err := b.inner.Release(ctx, apiKeyID, lockString)
	b.afterCall(err)
	return breakerError(err)
}

func (b *breakerBackend) ListEntries(ctx context.Context, apiKeyID string) (map[string]Entry, error) {
	if err := b.beforeCall(); err != nil {
		return nil, err
	}
	entries, err := b.inner.ListEntries(ctx, apiKeyID)
	b.afterCall(err)
	return entries, breakerError(err)
}

func (b *breakerBackend) Cleanup(ctx context.Context, apiKeyID string) error {
	if err := b.beforeCall(); err != nil {
		return err
	}
	err := b.inner.Cleanup(ctx, apiKeyID)
	b.afterCall(err)
	return breakerError(err)
}

func (b *breakerBackend) beforeCall() error {
	b.mu.Lock()
	defer b.mu.Unlock()

	if b.now().Before(b.openedUntil) {
		return ErrBackendUnavailable
	}
	return nil
}

func (b *breakerBackend) afterCall(err error) {
	b.mu.Lock()
	defer b.mu.Unlock()

	if err == nil || errors.Is(err, ErrQuotaExceeded) {
		if !b.openedUntil.IsZero() {
			breakerStateTotal.WithLabelValues("closed").Inc()
		}
		b.consecutiveErr = 0
		b.openedUntil = time.Time{}
		return
	}

	b.consecutiveErr++
	if b.consecutiveErr < b.n {
		return
	}

	// ponytail: single breaker for the one Redis backend; split per shard only if multi-Redis arrives.
	b.consecutiveErr = 0
	b.openedUntil = b.now().Add(b.d)
	breakerStateTotal.WithLabelValues("open").Inc()
}

func breakerError(err error) error {
	if err == nil || errors.Is(err, ErrQuotaExceeded) || errors.Is(err, ErrBackendUnavailable) {
		return err
	}
	return fmt.Errorf("%w: %v", ErrBackendUnavailable, err)
}
