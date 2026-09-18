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

package sandbox_manager

import (
	"context"
	"errors"
	"time"

	"k8s.io/klog/v2"

	"github.com/openkruise/agents/api/v1alpha1"
	managererrors "github.com/openkruise/agents/pkg/sandbox-manager/errors"
	"github.com/openkruise/agents/pkg/sandbox-manager/infra"
	"github.com/openkruise/agents/pkg/utils/timeout"
)

const (
	DefaultSessionClaimTimeout  = 5 * time.Minute
	DefaultSessionPauseAfter    = 30 * time.Minute
	DefaultSessionShutdownAfter = 24 * time.Hour
	sessionClaimUser            = "openai-agents"
)

// ActivateSessionOptions is the protocol-neutral activate contract.
type ActivateSessionOptions struct {
	SessionID       string
	Namespace       string
	Template        string
	CreateIfMissing bool
	PauseAfter      time.Duration
	ShutdownAfter   time.Duration
	ClaimTimeout    time.Duration
	PostClaim       *infra.PostClaimRun
	Accepted        chan struct{}
}

// DeactivateSessionOptions is the protocol-neutral deactivate contract.
type DeactivateSessionOptions struct {
	SessionID     string
	Namespace     string
	PauseAfter    time.Duration
	ShutdownAfter time.Duration
}

// CloseSessionOptions is the protocol-neutral close contract.
type CloseSessionOptions struct {
	SessionID string
	Namespace string
}

func (m *SandboxManager) ActivateSession(ctx context.Context, opts ActivateSessionOptions) error {
	if opts.SessionID == "" || opts.Namespace == "" {
		return managererrors.NewError(managererrors.ErrorBadRequest, "session id and namespace are required")
	}
	claimTimeout := opts.ClaimTimeout
	if claimTimeout <= 0 {
		claimTimeout = DefaultSessionClaimTimeout
	}
	shutdownAfter := opts.ShutdownAfter
	if shutdownAfter <= 0 {
		shutdownAfter = DefaultSessionShutdownAfter
	}

	info, err := m.lookupSessionKey(ctx, opts.Namespace, opts.SessionID)
	if err != nil {
		return err
	}
	if info != nil {
		if info.Failed {
			return managererrors.NewError(managererrors.ErrorInternal, "session %s claim has failed", opts.SessionID)
		}
	} else if !opts.CreateIfMissing {
		return managererrors.NewError(managererrors.ErrorNotFound, "session %s not found", opts.SessionID)
	} else if opts.Template == "" {
		return managererrors.NewError(managererrors.ErrorBadRequest, "template is required to create a session")
	} else if !m.infra.HasTemplate(ctx, infra.HasTemplateOptions{Namespace: opts.Namespace, Name: opts.Template}) {
		return managererrors.NewError(managererrors.ErrorNotFound, "template %s not found", opts.Template)
	}

	claimOpts := infra.ClaimSandboxOptions{
		Namespace:        opts.Namespace,
		User:             sessionClaimUser,
		Template:         opts.Template,
		ClaimTimeout:     claimTimeout,
		CreateOnNoStock:  true,
		BindOwnerToClaim: true,
		PostClaim:        opts.PostClaim,
		Idempotency: &infra.IdempotencyOptions{
			Key:      opts.SessionID,
			Accepted: opts.Accepted,
		},
	}
	sbx, _, err := m.infra.ClaimSandbox(ctx, claimOpts)
	if err != nil {
		if errors.Is(err, infra.ErrSessionSandboxMissing) {
			return managererrors.WrapError(managererrors.ErrorConflict, err, "session %s sandbox is missing", opts.SessionID)
		}
		return preserveTypedError(err, "activate session")
	}

	if err := m.applySessionActivate(ctx, sbx, shutdownAfter); err != nil {
		return err
	}
	notifyAccepted(opts.Accepted)
	if err := m.syncRoute(ctx, sbx, false); err != nil {
		klog.FromContext(ctx).Error(err, "failed to sync route after session activate")
	}
	return nil
}

func (m *SandboxManager) DeactivateSession(ctx context.Context, opts DeactivateSessionOptions) error {
	if opts.SessionID == "" || opts.Namespace == "" {
		return managererrors.NewError(managererrors.ErrorBadRequest, "session id and namespace are required")
	}
	info, err := m.lookupSessionKey(ctx, opts.Namespace, opts.SessionID)
	if err != nil {
		return err
	}
	if info == nil {
		return nil
	}
	if info.Failed {
		return nil
	}

	sbx, err := m.infra.GetSandbox(ctx, infra.GetSandboxOptions{Namespace: opts.Namespace, SessionID: opts.SessionID})
	if err != nil {
		if errors.Is(err, infra.ErrSandboxNotFound) || errors.Is(err, infra.ErrSessionSandboxMissing) {
			return nil
		}
		return preserveTypedError(err, "deactivate session")
	}

	pauseAfter := opts.PauseAfter
	if pauseAfter <= 0 {
		pauseAfter = DefaultSessionPauseAfter
	}
	shutdownAfter := opts.ShutdownAfter
	if shutdownAfter <= 0 {
		shutdownAfter = DefaultSessionShutdownAfter
	}
	now := time.Now()
	requested := timeout.Options{
		PauseTime:    now.Add(pauseAfter),
		ShutdownTime: now.Add(shutdownAfter),
	}

	state, _ := sbx.GetState()
	if state == v1alpha1.SandboxStatePaused {
		requested.PauseTime = time.Time{}
	}
	_, err = sbx.SaveTimeoutWithPolicy(ctx, infra.SaveTimeoutOptions{Timeout: requested}, timeout.UpdatePolicyHoldOrAdvancePause)
	if err != nil {
		return preserveTypedError(err, "deactivate session")
	}
	return nil
}

func (m *SandboxManager) CloseSession(ctx context.Context, opts CloseSessionOptions) error {
	if opts.SessionID == "" || opts.Namespace == "" {
		return managererrors.NewError(managererrors.ErrorBadRequest, "session id and namespace are required")
	}
	sbx, err := m.infra.GetSandbox(ctx, infra.GetSandboxOptions{Namespace: opts.Namespace, SessionID: opts.SessionID})
	if err != nil && !errors.Is(err, infra.ErrSandboxNotFound) && !errors.Is(err, infra.ErrSessionSandboxMissing) {
		klog.FromContext(ctx).Error(err, "failed to load sandbox before closing session")
	}
	if err := m.infra.DeleteSessionKey(ctx, infra.DeleteSessionKeyOptions{Namespace: opts.Namespace, SessionID: opts.SessionID}); err != nil {
		return preserveTypedError(err, "close session")
	}
	if sbx != nil {
		m.deleteRouteAndSync(ctx, sbx)
	}
	return nil
}

func (m *SandboxManager) ListSessionKeys(ctx context.Context, opts infra.ListSessionKeysOptions) ([]infra.SessionKeyInfo, error) {
	keys, err := m.infra.ListSessionKeys(ctx, opts)
	if err != nil {
		return nil, preserveTypedError(err, "list session keys")
	}
	return keys, nil
}

func (m *SandboxManager) lookupSessionKey(ctx context.Context, namespace, sessionID string) (*infra.SessionKeyInfo, error) {
	keys, err := m.infra.ListSessionKeys(ctx, infra.ListSessionKeysOptions{Namespace: namespace})
	if err != nil {
		return nil, preserveTypedError(err, "list session keys")
	}
	for i := range keys {
		if keys[i].SessionID == sessionID {
			return &keys[i], nil
		}
	}
	return nil, nil
}

func (m *SandboxManager) applySessionActivate(ctx context.Context, sbx infra.Sandbox, shutdownAfter time.Duration) error {
	state, _ := sbx.GetState()
	now := time.Now()
	active := timeout.Options{ShutdownTime: now.Add(shutdownAfter)}
	if state == v1alpha1.SandboxStatePaused {
		if err := m.ResumeSandbox(ctx, sbx, infra.ResumeOptions{Timeout: &active}); err != nil {
			return preserveTypedError(err, "resume session sandbox")
		}
	}
	_, err := sbx.SaveTimeoutWithPolicy(ctx, infra.SaveTimeoutOptions{Timeout: active}, timeout.UpdatePolicyAlways)
	if err != nil {
		return preserveTypedError(err, "refresh session timeout")
	}
	return nil
}

func notifyAccepted(ch chan struct{}) {
	if ch == nil {
		return
	}
	select {
	case <-ch:
	default:
		close(ch)
	}
}
