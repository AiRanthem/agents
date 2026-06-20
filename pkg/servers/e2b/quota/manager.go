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

	"k8s.io/klog/v2"
)

type Manager struct {
	backend Backend
}

func NewManager(backend Backend) *Manager {
	if backend == nil {
		backend = NoopBackend{}
	}
	return &Manager{backend: backend}
}

func (m *Manager) Acquire(ctx context.Context, req AcquireRequest) error {
	limit, limited := req.Quota.SandboxCountLimit()
	if !limited {
		acquireTotal.WithLabelValues(acquireResultUnlimited).Inc()
		return nil
	}
	if req.APIKeyID == "" || req.LockString == "" {
		acquireTotal.WithLabelValues(acquireResultError).Inc()
		return fmt.Errorf("%w: apiKeyID=%q lockString=%q", ErrMissingIdentity, req.APIKeyID, req.LockString)
	}

	err := m.backend.Acquire(ctx, req.APIKeyID, req.LockString, limit)
	switch {
	case err == nil:
		acquireTotal.WithLabelValues(acquireResultAllowed).Inc()
		return nil
	case errors.Is(err, ErrQuotaExceeded):
		acquireTotal.WithLabelValues(acquireResultRejected).Inc()
		return ErrQuotaExceeded
	case errors.Is(err, ErrBackendUnavailable):
		backendErrorsTotal.WithLabelValues(backendOperationAcquire).Inc()
		acquireTotal.WithLabelValues(acquireResultFailOpen).Inc()
		klog.FromContext(ctx).Error(err, "quota backend unavailable, failing open", "apiKeyID", req.APIKeyID)
		return nil
	default:
		backendErrorsTotal.WithLabelValues(backendOperationAcquire).Inc()
		acquireTotal.WithLabelValues(acquireResultFailOpen).Inc()
		klog.FromContext(ctx).Error(err, "unexpected quota backend error, failing open", "apiKeyID", req.APIKeyID)
		return nil
	}
}

func (m *Manager) Release(ctx context.Context, req ReleaseRequest) error {
	if req.APIKeyID == "" || req.LockString == "" {
		return nil
	}
	if err := m.backend.Release(ctx, req.APIKeyID, req.LockString); err != nil {
		return err
	}
	return nil
}

func (m *Manager) DeleteSubject(ctx context.Context, apiKeyID string) error {
	if apiKeyID == "" {
		return nil
	}
	if err := m.backend.DeleteSubject(ctx, apiKeyID); err != nil {
		return err
	}
	return nil
}
