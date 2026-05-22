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

package e2b

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"time"

	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/klog/v2"

	"github.com/openkruise/agents/api/v1alpha1"
	cacheutils "github.com/openkruise/agents/pkg/cache/utils"
	managererrors "github.com/openkruise/agents/pkg/sandbox-manager/errors"
	"github.com/openkruise/agents/pkg/sandbox-manager/infra"
	"github.com/openkruise/agents/pkg/servers/e2b/models"
	"github.com/openkruise/agents/pkg/servers/web"
	"github.com/openkruise/agents/pkg/utils/runtime"
	"github.com/openkruise/agents/pkg/utils/timeout"
)

func (sc *Controller) PauseSandbox(r *http.Request) (web.ApiResponse[struct{}], *web.ApiError) {
	id := r.PathValue("sandboxID")
	ctx := r.Context()
	log := klog.FromContext(ctx).WithValues("sandboxID", id)
	sbx, apiErr := sc.getSandboxOfUser(ctx, id)
	if apiErr != nil {
		return web.ApiResponse[struct{}]{}, apiErr
	}
	timeoutOptions := sc.buildPauseTimeoutOptions(sbx, time.Now())
	if err := sc.manager.PauseSandbox(ctx, sbx, infra.PauseOptions{
		Timeout: &timeoutOptions,
	}); err != nil {
		return web.ApiResponse[struct{}]{}, &web.ApiError{
			Code:    pauseSandboxErrorCode(err),
			Message: fmt.Sprintf("Failed to pause sandbox: %v", err),
		}
	}
	log.Info("sandbox paused", "timeout", timeoutOptions)
	return web.ApiResponse[struct{}]{
		Code: http.StatusNoContent,
	}, nil
}

func pauseSandboxErrorCode(err error) int {
	if apierrors.IsNotFound(err) {
		return http.StatusNotFound
	}
	if managererrors.GetErrCode(err) == managererrors.ErrorConflict ||
		errors.Is(err, cacheutils.ErrWaitTaskConflict) {
		return http.StatusConflict
	}
	return http.StatusInternalServerError
}

func (sc *Controller) buildPauseTimeoutOptions(sbx infra.Sandbox, now time.Time) timeout.Options {
	opts := sbx.GetTimeout()
	// Only set timeout if the sandbox has a timeout configured (not never-timeout)
	if !opts.ShutdownTime.IsZero() {
		// Paused sandboxes are kept indefinitely — there is no automatic deletion or time-to-live limit
		endAt := now.AddDate(1000, 0, 0)
		opts.ShutdownTime = endAt
		if !opts.PauseTime.IsZero() {
			opts.PauseTime = endAt
		}
	}
	return opts
}

// ResumeSandbox is DEPRECATED and kept only for old SDK compatibility.
//
// E2B exposes one "connect" behavior, but different SDK versions call different endpoints:
// - New SDK: calls ConnectSandbox directly.
// - Old SDK: first calls SetSandboxTimeout; that path returns 500 on this flow, then falls back to ResumeSandbox.
//
// Because ResumeSandbox is only used for the paused->running flow, it applies the floor-enforced
// requested timeout. Placeholder writing and ExtendOnly post-Resume semantics mirror ConnectSandbox.
// The running-sandbox "extend only" guard is intentionally implemented in ConnectSandbox only.
func (sc *Controller) ResumeSandbox(r *http.Request) (web.ApiResponse[struct{}], *web.ApiError) {
	id := r.PathValue("sandboxID")
	ctx := r.Context()
	log := klog.FromContext(ctx).WithValues("sandboxID", id)

	request, apiErr := ParseSetTimeoutRequest(r, sc.maxTimeout)
	if apiErr != nil {
		apiErr.Code = http.StatusInternalServerError // E2B returns 500
		return web.ApiResponse[struct{}]{}, apiErr
	}

	sbx, apiErr := sc.getSandboxOfUser(ctx, id)
	if apiErr != nil {
		return web.ApiResponse[struct{}]{}, apiErr
	}
	autoPause, currentEndAt := ParseTimeout(sbx)

	state, reason := sbx.GetState()
	if state != v1alpha1.SandboxStatePaused {
		log.Info("skip resume sandbox: sandbox is not paused", "state", state, "reason", reason)
		return web.ApiResponse[struct{}]{}, &web.ApiError{
			Code:    http.StatusConflict,
			Message: fmt.Sprintf("Sandbox %s is not paused", id),
		}
	}

	// Floor enforcement mirrors ConnectSandbox.
	effectiveTimeout := request.TimeoutSeconds
	if !currentEndAt.IsZero() && effectiveTimeout < sc.minResumeTimeout {
		log.Info("connect-on-paused timeout floor applied",
			"requestedSeconds", request.TimeoutSeconds,
			"effectiveSeconds", sc.minResumeTimeout,
			"reason", "request shorter than --e2b-min-resume-timeout")
		effectiveTimeout = sc.minResumeTimeout
	}

	var resumeOpts infra.ResumeOptions
	if !currentEndAt.IsZero() {
		realTimeout := sc.buildSetTimeoutOptions(autoPause, time.Now(), effectiveTimeout)
		resumeOpts.Timeout = &realTimeout
	}
	log.Info("resuming sandbox")
	if err := sc.manager.ResumeSandbox(ctx, sbx, resumeOpts); err != nil {
		code := http.StatusInternalServerError
		if managererrors.GetErrCode(err) == managererrors.ErrorBadRequest {
			code = http.StatusBadRequest
		}
		return web.ApiResponse[struct{}]{}, &web.ApiError{
			Code:    code,
			Message: fmt.Sprintf("Failed to resume sandbox: %v", err),
		}
	}

	// Set the real timeout. ExtendOnly is safe because the placeholder was built
	// from the same effectiveTimeout; the post-Resume opts here will be
	// ~resumeDuration later and ExtendOnly extends naturally.
	if !currentEndAt.IsZero() {
		opts := sc.buildSetTimeoutOptions(autoPause, time.Now(), effectiveTimeout)
		log.Info("sandbox resumed, resetting sandbox timeout", "timeout", opts)
		if _, err := sbx.SaveTimeoutWithPolicy(ctx, opts, timeout.UpdatePolicyExtendOnly); err != nil {
			return web.ApiResponse[struct{}]{}, &web.ApiError{
				Message: fmt.Sprintf("Failed to set sandbox timeout: %v", err),
			}
		}
	} else {
		log.Info("skip resetting timeout for never-timeout sandbox")
	}
	return web.ApiResponse[struct{}]{
		Code: http.StatusNoContent,
	}, nil
}

func (sc *Controller) ConnectSandbox(r *http.Request) (web.ApiResponse[*models.Sandbox], *web.ApiError) {
	id := r.PathValue("sandboxID")
	ctx := r.Context()
	log := klog.FromContext(ctx).WithValues("sandboxID", id)
	log.Info("connecting sandbox")

	request, apiErr := ParseSetTimeoutRequest(r, sc.maxTimeout)
	if apiErr != nil {
		return web.ApiResponse[*models.Sandbox]{}, apiErr
	}

	sbx, apiErr := sc.getSandboxOfUser(ctx, id)
	if apiErr != nil {
		return web.ApiResponse[*models.Sandbox]{}, apiErr
	}
	// `state` is intentionally the pre-connect observation.
	// We only enforce the extend-only guard for sandboxes that were already
	// running when Connect was called. Paused->resume requests apply the
	// requested timeout (post-floor) atomically inside Resume.
	state, pauseResumeReason := sbx.GetState()
	autoPause, currentEndAt := ParseTimeout(sbx)

	// Floor enforcement: requests that will trigger Resume on a timed Paused
	// sandbox must have an effective timeout long enough to outlast the
	// Resume wall-clock duration; otherwise the placeholder PauseTime expires
	// mid-Resume and the controller auto-pauses the in-transition sandbox.
	// Never-timeout sandboxes (currentEndAt zero) have no PauseTime so no
	// race exists; the floor would only generate misleading log noise. See
	// docs/superpowers/specs/2026-05-22-resume-atomic-pausetime-design.md.
	effectiveTimeout := request.TimeoutSeconds
	if state == v1alpha1.SandboxStatePaused && !currentEndAt.IsZero() &&
		effectiveTimeout < sc.minResumeTimeout {
		log.Info("connect-on-paused timeout floor applied",
			"requestedSeconds", request.TimeoutSeconds,
			"effectiveSeconds", sc.minResumeTimeout,
			"reason", "request shorter than --e2b-min-resume-timeout")
		effectiveTimeout = sc.minResumeTimeout
	}

	// Step 1: Resuming the sandbox if it is paused, atomically writing the
	// placeholder timeout for timed sandboxes.
	statusCode := http.StatusOK
	if state == v1alpha1.SandboxStatePaused {
		log.Info("sandbox is paused, will resume it", "reason", pauseResumeReason)
		var resumeOpts infra.ResumeOptions
		if !currentEndAt.IsZero() {
			realTimeout := sc.buildSetTimeoutOptions(autoPause, time.Now(), effectiveTimeout)
			resumeOpts.Timeout = &realTimeout
		}
		// Never-timeout sandbox: leave resumeOpts.Timeout nil. Writing a
		// derived placeholder would convert it into a timed sandbox.
		if err := sc.manager.ResumeSandbox(ctx, sbx, resumeOpts); err != nil {
			log.Error(err, "failed to resume sandbox")
			code := http.StatusInternalServerError
			if managererrors.GetErrCode(err) == managererrors.ErrorConflict {
				code = http.StatusBadRequest
			}
			return web.ApiResponse[*models.Sandbox]{}, &web.ApiError{
				Code:    code,
				Message: fmt.Sprintf("Failed to resume sandbox: %v", err),
			}
		}
		statusCode = http.StatusCreated
		log.Info("sandbox resumed", "timeout", sbx.GetTimeout())
	} else {
		log.Info("sandbox is not paused, skip resuming", "state", state, "reason", pauseResumeReason)
	}

	// Step 2: Update the sandbox timeout with the effective (post-floor)
	// value. updateConnectTimeout short-circuits on never-timeout sandboxes.
	log.Info("updating sandbox timeout")
	if err := sc.updateConnectTimeout(ctx, sbx, effectiveTimeout, state, autoPause, currentEndAt); err != nil {
		log.Error(err, "failed to update sandbox timeout")
		return web.ApiResponse[*models.Sandbox]{}, err
	}
	log.Info("sandbox timeout updated")

	return web.ApiResponse[*models.Sandbox]{
		Code: statusCode,
		Body: sc.convertToE2BSandbox(sbx, runtime.GetAccessToken(sbx)),
	}, nil
}

// updateConnectTimeout updates the sandbox timeout after a Connect or Resume.
//
// Always uses UpdatePolicyExtendOnly: the placeholder written by Resume()
// uses the same buildSetTimeoutOptions formula as `opts` below, differing
// only by the elapsed Resume wall-clock duration. ExtendOnly's monotonic
// "later wins" semantics absorb that gap (extending the placeholder to the
// post-Resume value) and concurrent-writer races (longer timeout wins).
// See docs/superpowers/specs/2026-05-22-resume-atomic-pausetime-design.md.
func (sc *Controller) updateConnectTimeout(ctx context.Context, sbx infra.Sandbox, timeoutSeconds int, preConnectState string, autoPause bool, currentEndAt time.Time) *web.ApiError {
	log := klog.FromContext(ctx).WithValues("sandboxID", sbx.GetSandboxID())

	// Sandboxes without endAt are never-timeout; their timeout must not change.
	if currentEndAt.IsZero() {
		log.Info("skip resetting timeout for never-timeout sandbox")
		return nil
	}

	now := time.Now()
	opts := sc.buildSetTimeoutOptions(autoPause, now, timeoutSeconds)

	log.Info("saving timeout to sandbox", "timeout", opts, "currentEndAt", currentEndAt,
		"requestedEndAt", TimeAfterSeconds(now, timeoutSeconds), "requestedTimeoutSeconds", timeoutSeconds,
		"policy", timeout.UpdatePolicyExtendOnly, "preConnectState", preConnectState)
	result, err := sbx.SaveTimeoutWithPolicy(ctx, opts, timeout.UpdatePolicyExtendOnly)
	if err != nil {
		return &web.ApiError{
			Message: fmt.Sprintf("Failed to set sandbox timeout: %v", err),
		}
	}
	if !result.Updated {
		log.Info("skip resetting timeout according to ExtendOnly policy",
			"currentEndAt", currentEndAt,
			"requestedTimeoutSeconds", timeoutSeconds)
	} else {
		log.Info("timeout updated", "requestedTimeoutSeconds", timeoutSeconds)
	}
	return nil
}
