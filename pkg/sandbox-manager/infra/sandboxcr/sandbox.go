/*
Copyright 2025 The Kruise Authors.

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

package sandboxcr

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/google/uuid"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/util/retry"
	"k8s.io/klog/v2"
	"k8s.io/utils/ptr"
	"sigs.k8s.io/controller-runtime/pkg/client"

	agentsv1alpha1 "github.com/openkruise/agents/api/v1alpha1"
	"github.com/openkruise/agents/pkg/agent-runtime/storages"
	"github.com/openkruise/agents/pkg/cache"
	cacheutils "github.com/openkruise/agents/pkg/cache/utils"
	"github.com/openkruise/agents/pkg/proxy"
	"github.com/openkruise/agents/pkg/sandbox-manager/config"
	"github.com/openkruise/agents/pkg/sandbox-manager/consts"
	"github.com/openkruise/agents/pkg/sandbox-manager/infra"
	"github.com/openkruise/agents/pkg/utils"
	csimountutils "github.com/openkruise/agents/pkg/utils/csiutils"
	"github.com/openkruise/agents/pkg/utils/expectations"
	"github.com/openkruise/agents/pkg/utils/runtime"
	sandboxManagerUtils "github.com/openkruise/agents/pkg/utils/sandbox-manager"
	"github.com/openkruise/agents/pkg/utils/sandbox-manager/expectationutils"
	"github.com/openkruise/agents/pkg/utils/sandbox-manager/proxyutils"
	stateutils "github.com/openkruise/agents/pkg/utils/sandboxutils"
)

type ModifierFunc func(sbx *agentsv1alpha1.Sandbox)

type Sandbox struct {
	*agentsv1alpha1.Sandbox
	Cache           cache.Provider
	storageRegistry storages.VolumeMountProviderRegistry
}

var DefaultDeleteSandbox = deleteSandbox

func deleteSandbox(ctx context.Context, sbx *agentsv1alpha1.Sandbox, client client.Client) error {
	return client.Delete(ctx, sbx)
}

func (s *Sandbox) GetTemplate() string {
	return utils.GetTemplateFromSandbox(s.Sandbox)
}

func (s *Sandbox) InplaceRefresh(ctx context.Context, deepcopy bool) error {
	log := klog.FromContext(ctx).WithValues("sandbox", klog.KObj(s.Sandbox)).V(consts.DebugLogLevel)
	fetchFromApiServer := false
	objectKey := client.ObjectKeyFromObject(s.Sandbox)
	newSbx := &agentsv1alpha1.Sandbox{}
	err := s.Cache.GetClient().Get(ctx, objectKey, newSbx)
	if err != nil {
		log.Info("failed to get claimed sandbox from cache, fetch from api-server", "reason", err.Error())
		fetchFromApiServer = true
	} else if !expectationutils.ResourceVersionExpectationSatisfied(newSbx) {
		log.Info("sandbox cache is out-dated, fetch from api-server")
		fetchFromApiServer = true
	}
	if fetchFromApiServer {
		if err = s.Cache.GetAPIReader().Get(ctx, objectKey, newSbx); err != nil {
			return err
		}
	}
	if expectations.IsResourceVersionReallyNewer(s.Sandbox.GetResourceVersion(), newSbx.GetResourceVersion()) {
		if deepcopy {
			s.Sandbox = newSbx.DeepCopy()
		} else {
			s.Sandbox = newSbx
		}
	}
	return nil
}

// refreshFunc returns a RefreshFunc callback that refreshes this sandbox and returns the latest object.
// This allows InitRuntime in utils/runtime to refresh sandbox state without depending on the sandboxcr package.
func (s *Sandbox) refreshFunc() runtime.RefreshFunc {
	return func(ctx context.Context) (*agentsv1alpha1.Sandbox, error) {
		if err := s.InplaceRefresh(ctx, false); err != nil {
			return nil, err
		}
		return s.Sandbox, nil
	}
}

func (s *Sandbox) retryUpdate(ctx context.Context, modifier ModifierFunc) error {
	log := klog.FromContext(ctx).WithValues("sandbox", klog.KObj(s.Sandbox))
	err := retry.RetryOnConflict(retry.DefaultRetry, func() error {
		// get the latest sandbox from cache
		sbx, err := s.Cache.GetClaimedSandbox(ctx, stateutils.GetSandboxID(s.Sandbox))
		if err != nil {
			return err
		}

		copied := sbx.DeepCopy()
		modifier(copied)
		if err := s.Cache.GetClient().Update(ctx, copied); err != nil {
			return err
		}
		s.Sandbox = copied
		expectationutils.ResourceVersionExpectationExpect(copied)
		return nil
	})
	if err != nil {
		log.Error(err, "failed to update sandbox after retries")
	} else {
		log.Info("sandbox updated successfully")
	}
	return err
}

func (s *Sandbox) Kill(ctx context.Context) error {
	if s.GetDeletionTimestamp() != nil {
		return nil
	}
	return DefaultDeleteSandbox(ctx, s.Sandbox, s.Cache.GetClient())
}

func (s *Sandbox) GetSandboxID() string {
	return stateutils.GetSandboxID(s.Sandbox)
}

func (s *Sandbox) GetRoute() proxy.Route {
	return proxyutils.DefaultGetRouteFunc(s.Sandbox)
}

// setTimeout overwrites Spec.PauseTime / Spec.ShutdownTime from opts.
//
// Contract (relied upon by callers such as buildResumeTimeoutOptions and
// SaveTimeout): a zero time.Time in opts is treated as "clear this field" and
// will set the corresponding Spec.*Time pointer back to nil. This is the
// intended way for upper layers to express "this sandbox should be
// never-timeout"; do not change this to skip-on-zero, otherwise callers that
// pass infra.TimeoutOptions{} expecting the underlying fields to be cleared
// will silently retain stale values.
func setTimeout(s *agentsv1alpha1.Sandbox, opts infra.TimeoutOptions) {
	if !opts.PauseTime.IsZero() {
		s.Spec.PauseTime = ptr.To(metav1.NewTime(opts.PauseTime))
	} else {
		s.Spec.PauseTime = nil
	}
	if !opts.ShutdownTime.IsZero() {
		s.Spec.ShutdownTime = ptr.To(metav1.NewTime(opts.ShutdownTime))
	} else {
		s.Spec.ShutdownTime = nil
	}
}

func (s *Sandbox) SetTimeout(opts infra.TimeoutOptions) {
	setTimeout(s.Sandbox, opts)
}

func (s *Sandbox) GetPodLabels() map[string]string {
	if s.Spec.Template != nil {
		return s.Spec.Template.Labels
	}
	return nil
}

func (s *Sandbox) SetPodLabels(labels map[string]string) {
	if s.Spec.Template != nil {
		s.Spec.Template.Labels = labels
	}
}

// SetImage sets the image of the first container
func (s *Sandbox) SetImage(image string) {
	if s.Spec.Template != nil {
		s.Spec.Template.Spec.Containers[0].Image = image
	}
}

func (s *Sandbox) GetImage() string {
	if s.Spec.Template != nil {
		return s.Spec.Template.Spec.Containers[0].Image
	}
	return ""
}

// SaveTimeout persists opts to Spec.PauseTime / Spec.ShutdownTime via the
// API server. Per setTimeout's contract, a zero time.Time in opts clears the
// corresponding spec field; callers that want to mark a sandbox as
// never-timeout should pass infra.TimeoutOptions{} (or a struct with both
// times zero).
func (s *Sandbox) SaveTimeout(ctx context.Context, opts infra.TimeoutOptions) error {
	return s.retryUpdate(ctx, func(sbx *agentsv1alpha1.Sandbox) {
		setTimeout(sbx, opts)
	})
}

func (s *Sandbox) GetTimeout() infra.TimeoutOptions {
	return getTimeoutFromSandbox(s.Sandbox)
}

func getTimeoutFromSandbox(s *agentsv1alpha1.Sandbox) infra.TimeoutOptions {
	opts := infra.TimeoutOptions{}
	if s.Spec.ShutdownTime != nil {
		opts.ShutdownTime = s.Spec.ShutdownTime.Time
	}
	if s.Spec.PauseTime != nil {
		opts.PauseTime = s.Spec.PauseTime.Time
	}
	return opts
}

func (s *Sandbox) GetResource() infra.SandboxResource {
	if s.Spec.Template == nil {
		return infra.SandboxResource{}
	}
	return sandboxManagerUtils.CalculateResourceFromContainers(s.Spec.Template.Spec.Containers)
}

func (s *Sandbox) Request(ctx context.Context, method, path string, port int, body io.Reader) (*http.Response, error) {
	return proxyutils.DefaultRequestFunc(ctx, s.Sandbox, method, path, port, body)
}

func (s *Sandbox) Pause(ctx context.Context, opts infra.PauseOptions) error {
	log := klog.FromContext(ctx)
	if s.Status.Phase != agentsv1alpha1.SandboxRunning {
		return fmt.Errorf("sandbox is not in running phase")
	}
	state, reason := s.GetState()
	if state != agentsv1alpha1.SandboxStateRunning {
		err := fmt.Errorf("pausing is only available for running state, current state: %s", state)
		log.Error(err, "sandbox is not running", "state", state, "reason", reason)
		return err
	}
	err := s.retryUpdate(ctx, func(sbx *agentsv1alpha1.Sandbox) {
		sbx.Spec.Paused = true
		if opts.Timeout != nil {
			setTimeout(sbx, *opts.Timeout)
		}
	})
	if err != nil {
		log.Error(err, "failed to update sandbox spec.paused")
		return err
	}
	expectationutils.ResourceVersionExpectationExpect(s.Sandbox)
	log.Info("waiting sandbox pause")
	start := time.Now()
	if err = s.Cache.NewSandboxPauseTask(ctx, s.Sandbox).Wait(time.Minute); err != nil {
		log.Error(err, "failed to wait sandbox pause")
		return err
	}
	log.Info("sandbox paused", "cost", time.Since(start))
	return s.InplaceRefresh(ctx, false)
}

func bumpResumeTimeoutProtection(sbx *agentsv1alpha1.Sandbox, protectUntil time.Time) {
	if sbx.Spec.PauseTime != nil && sbx.Spec.PauseTime.Time.Before(protectUntil) {
		sbx.Spec.PauseTime = ptr.To(metav1.NewTime(protectUntil))
	}
	if sbx.Spec.ShutdownTime != nil && sbx.Spec.ShutdownTime.Time.Before(protectUntil) {
		sbx.Spec.ShutdownTime = ptr.To(metav1.NewTime(protectUntil))
	}
}

type resumeState string

const (
	resumeStateStartable  resumeState = "startable"
	resumeStateInProgress resumeState = "in-progress"
	resumeStateCompleted  resumeState = "completed"
	resumeStateStale      resumeState = "stale"
	resumeStateBlocked    resumeState = "blocked"
)

var (
	resumeCompletionRecheckInterval = 30 * time.Second
	resumeLockStaleTTL              = 5 * time.Minute
	resumeLockRenewBefore           = time.Minute
	resumeTimeoutProtectionDuration = time.Hour
	postResumeRetryInterval         = 200 * time.Millisecond

	errResumeOwnerLockLost = errors.New("resume owner lock lost")
)

type resumeStateResult struct {
	state resumeState
	err   error
}

func classifyResumeState(sbx *agentsv1alpha1.Sandbox, now time.Time, staleTTL time.Duration) resumeStateResult {
	if isSandboxResumeCompleted(sbx) {
		return resumeStateResult{state: resumeStateCompleted}
	}
	if isTerminalResumeState(sbx, now) {
		state, reason := stateutils.GetSandboxState(sbx)
		return resumeStateResult{
			state: resumeStateBlocked,
			err:   fmt.Errorf("resuming is only available for paused state, current state: %s, reason: %s", state, reason),
		}
	}
	if lock := sbx.GetAnnotations()[agentsv1alpha1.AnnotationResumingLock]; lock != "" {
		if resumeLockStale(sbx, now, staleTTL) {
			return resumeStateResult{state: resumeStateStale}
		}
		return resumeStateResult{state: resumeStateInProgress}
	}

	state, reason := stateutils.GetSandboxState(sbx)
	if state != agentsv1alpha1.SandboxStatePaused {
		return resumeStateResult{
			state: resumeStateBlocked,
			err:   fmt.Errorf("resuming is only available for paused state, current state: %s, reason: %s", state, reason),
		}
	}
	if sbx.Status.Phase != agentsv1alpha1.SandboxPaused {
		return resumeStateResult{
			state: resumeStateBlocked,
			err:   fmt.Errorf("resuming is only available for sandboxes in phase Paused, current phase: %s, state: %s, reason: %s", sbx.Status.Phase, state, reason),
		}
	}
	if !sbx.Spec.Paused {
		return resumeStateResult{
			state: resumeStateBlocked,
			err:   fmt.Errorf("resuming is only available for sandboxes with spec.paused == true, current state: %s, reason: %s", state, reason),
		}
	}
	cond := GetSandboxCondition(sbx, agentsv1alpha1.SandboxConditionPaused)
	if cond.Status == metav1.ConditionFalse {
		return resumeStateResult{
			state: resumeStateBlocked,
			err:   fmt.Errorf("sandbox is pausing, please wait a moment and try again"),
		}
	}
	return resumeStateResult{state: resumeStateStartable}
}

func isSandboxResumeCompleted(sbx *agentsv1alpha1.Sandbox) bool {
	if sbx.GetAnnotations()[agentsv1alpha1.AnnotationResumingLock] != "" {
		return false
	}
	readyCond := GetSandboxCondition(sbx, agentsv1alpha1.SandboxConditionReady)
	resumedCond := GetSandboxCondition(sbx, agentsv1alpha1.SandboxConditionResumed)
	return sbx.Status.Phase == agentsv1alpha1.SandboxRunning &&
		readyCond.Status == metav1.ConditionTrue &&
		resumedCond.Status == metav1.ConditionTrue
}

func isTerminalResumeState(sbx *agentsv1alpha1.Sandbox, now time.Time) bool {
	return sbx.GetDeletionTimestamp() != nil ||
		(sbx.Spec.ShutdownTime != nil && now.After(sbx.Spec.ShutdownTime.Time)) ||
		sbx.Status.Phase == agentsv1alpha1.SandboxFailed ||
		sbx.Status.Phase == agentsv1alpha1.SandboxSucceeded ||
		sbx.Status.Phase == agentsv1alpha1.SandboxTerminating
}

func resumeLockStale(sbx *agentsv1alpha1.Sandbox, now time.Time, staleTTL time.Duration) bool {
	since := sbx.GetAnnotations()[agentsv1alpha1.AnnotationResumingSince]
	resumingSince, err := time.Parse(time.RFC3339Nano, since)
	return err != nil || !now.Before(resumingSince.Add(staleTTL))
}

func (s *Sandbox) Resume(ctx context.Context, opts infra.ResumeOptions) error {
	log := klog.FromContext(ctx).WithValues("sandbox", klog.KObj(s.Sandbox))
	for {
		if err := ctx.Err(); err != nil {
			return err
		}
		if err := s.InplaceRefresh(ctx, false); err != nil {
			return err
		}
		classification := classifyResumeState(s.Sandbox, time.Now(), resumeLockStaleTTL)
		switch classification.state {
		case resumeStateCompleted:
			return infra.ErrResumeCompletedByOtherRequest
		case resumeStateStartable, resumeStateStale:
			ownerID := uuid.NewString()
			acquired, err := s.tryAcquireResumeOwner(ctx, ownerID)
			if err != nil {
				log.Error(err, "failed to acquire resume owner")
				return err
			}
			if acquired {
				return s.runResumeOwner(ctx, ownerID, opts)
			}
		case resumeStateInProgress:
			err := s.waitResumeOwner(ctx)
			if err == nil {
				return infra.ErrResumeCompletedByOtherRequest
			}
			if errors.Is(err, cacheutils.ErrSandboxResumeLockStale) ||
				errors.Is(err, cacheutils.ErrSandboxResumeOwnerFinished) ||
				errors.Is(err, cacheutils.ErrObjectNotSatisfiedDuringDoubleCheck) {
				continue
			}
			return err
		default:
			return classification.err
		}
	}
}

func (s *Sandbox) tryAcquireResumeOwner(ctx context.Context, ownerID string) (bool, error) {
	acquired := false
	err := retry.RetryOnConflict(retry.DefaultRetry, func() error {
		sbx, err := s.Cache.GetClaimedSandbox(ctx, stateutils.GetSandboxID(s.Sandbox))
		if err != nil {
			return err
		}
		classification := classifyResumeState(sbx, time.Now(), resumeLockStaleTTL)
		if classification.state != resumeStateStartable && classification.state != resumeStateStale {
			s.Sandbox = sbx
			return nil
		}
		copied := sbx.DeepCopy()
		if copied.Annotations == nil {
			copied.Annotations = map[string]string{}
		}
		copied.Spec.Paused = false
		bumpResumeTimeoutProtection(copied, time.Now().Add(resumeTimeoutProtectionDuration))
		copied.Annotations[agentsv1alpha1.AnnotationResumingLock] = ownerID
		copied.Annotations[agentsv1alpha1.AnnotationResumingSince] = time.Now().Format(time.RFC3339Nano)
		if err := s.Cache.GetClient().Update(ctx, copied); err != nil {
			return err
		}
		s.Sandbox = copied
		expectationutils.ResourceVersionExpectationExpect(copied)
		acquired = true
		return nil
	})
	return acquired, err
}

func (s *Sandbox) runResumeOwner(ctx context.Context, ownerID string, opts infra.ResumeOptions) error {
	log := klog.FromContext(ctx).WithValues("sandbox", klog.KObj(s.Sandbox), "resumeOwner", ownerID)
	log.Info("waiting sandbox resume as owner")
	ownerCtx, cancelOwner := context.WithCancel(ctx)
	defer cancelOwner()
	keeperCtx, stopKeeper := context.WithCancel(ownerCtx)
	leaseErrCh := s.startResumeOwnerLeaseKeeper(keeperCtx, ownerID, cancelOwner)
	defer stopKeeper()

	checkLeaseErr := func(err error) error {
		stopKeeper()
		select {
		case leaseErr := <-leaseErrCh:
			if leaseErr != nil {
				return leaseErr
			}
		default:
		}
		return err
	}

	start := time.Now()
	if err := s.waitOwnerResumeStatus(ownerCtx); err != nil {
		return checkLeaseErr(err)
	}
	log.Info("sandbox resume status reached running", "cost", time.Since(start))

	if err := s.retryPostResumeOperations(ownerCtx); err != nil {
		log.Error(err, "post-resume operations did not complete")
		return checkLeaseErr(err)
	}
	if opts.Timeout != nil && !opts.DisablePushTimeout {
		infra.PushTimeout(opts.Timeout, time.Since(start))
	}
	if err := s.finishResumeOwner(ownerCtx, ownerID, opts.Timeout); err != nil {
		log.Error(err, "failed to finish resume owner")
		return checkLeaseErr(err)
	}
	stopKeeper()
	return nil
}

func (s *Sandbox) startResumeOwnerLeaseKeeper(ctx context.Context, ownerID string, cancelOwner context.CancelFunc) <-chan error {
	errCh := make(chan error, 1)
	go func() {
		ticker := time.NewTicker(resumeCompletionRecheckInterval)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
			}
			if _, err := s.renewResumeOwnerLock(ctx, ownerID, time.Now()); err != nil {
				if ctx.Err() != nil {
					return
				}
				select {
				case errCh <- err:
				default:
				}
				cancelOwner()
				return
			}
		}
	}()
	return errCh
}

func (s *Sandbox) renewResumeOwnerLock(ctx context.Context, ownerID string, now time.Time) (bool, error) {
	renewed := false
	objectKey := client.ObjectKeyFromObject(s.Sandbox)
	err := retry.RetryOnConflict(retry.DefaultRetry, func() error {
		latest := &agentsv1alpha1.Sandbox{}
		if err := s.Cache.GetAPIReader().Get(ctx, objectKey, latest); err != nil {
			return err
		}
		if latest.GetAnnotations()[agentsv1alpha1.AnnotationResumingLock] != ownerID {
			return errResumeOwnerLockLost
		}
		resumingSince, err := time.Parse(time.RFC3339Nano, latest.GetAnnotations()[agentsv1alpha1.AnnotationResumingSince])
		if err == nil && resumingSince.Add(resumeLockStaleTTL).Sub(now) > resumeLockRenewBefore {
			s.Sandbox = latest
			return nil
		}
		copied := latest.DeepCopy()
		if copied.Annotations == nil {
			copied.Annotations = map[string]string{}
		}
		copied.Annotations[agentsv1alpha1.AnnotationResumingSince] = now.Format(time.RFC3339Nano)
		if err := s.Cache.GetClient().Update(ctx, copied); err != nil {
			return err
		}
		s.Sandbox = copied
		expectationutils.ResourceVersionExpectationExpect(copied)
		renewed = true
		return nil
	})
	return renewed, err
}

func (s *Sandbox) waitOwnerResumeStatus(ctx context.Context) error {
	for {
		err := s.Cache.NewSandboxResumeTask(ctx, s.Sandbox).Wait(resumeCompletionRecheckInterval)
		if err == nil {
			return nil
		}
		if errors.Is(err, cacheutils.ErrObjectNotSatisfiedDuringDoubleCheck) {
			if ctx.Err() != nil {
				return ctx.Err()
			}
			continue
		}
		return err
	}
}

func (s *Sandbox) waitResumeOwner(ctx context.Context) error {
	err := s.Cache.NewSandboxResumeCompletionTask(ctx, s.Sandbox, resumeLockStaleTTL).Wait(resumeCompletionRecheckInterval)
	if err == nil {
		return s.InplaceRefresh(ctx, false)
	}
	if ctx.Err() != nil && errors.Is(err, cacheutils.ErrObjectNotSatisfiedDuringDoubleCheck) {
		return ctx.Err()
	}
	return err
}

func (s *Sandbox) retryPostResumeOperations(ctx context.Context) error {
	var lastErr error
	for {
		if err := ctx.Err(); err != nil {
			if lastErr != nil {
				return fmt.Errorf("%w: %v", lastErr, err)
			}
			return err
		}
		if err := s.postResumeOperations(ctx); err != nil {
			lastErr = err
			timer := time.NewTimer(postResumeRetryInterval)
			select {
			case <-ctx.Done():
				timer.Stop()
			case <-timer.C:
			}
			continue
		}
		return nil
	}
}

func (s *Sandbox) postResumeOperations(ctx context.Context) error {
	log := klog.FromContext(ctx).WithValues("sandbox", klog.KObj(s.Sandbox))
	if err := s.InplaceRefresh(ctx, false); err != nil {
		return fmt.Errorf("failed to refresh sandbox after resume: %w", err)
	}
	expectationutils.ResourceVersionExpectationExpect(s.Sandbox)

	if s.Labels[agentsv1alpha1.LabelSandboxClaimName] != "" {
		log.Info("sandbox is claimed by SandboxClaim, skipping E2B post-resume initialization",
			"claimName", s.Labels[agentsv1alpha1.LabelSandboxClaimName])
		return nil
	}

	initRuntimeOpts, err := runtime.GetInitRuntimeRequest(s.Sandbox)
	if err != nil {
		return fmt.Errorf("failed to get init runtime request: %w", err)
	}
	if initRuntimeOpts != nil {
		log.Info("will re-init runtime after resume")
		if _, err := runtime.InitRuntime(ctx, s.Sandbox, *initRuntimeOpts, s.refreshFunc()); err != nil {
			return fmt.Errorf("failed to perform ReInit after resume: %w", err)
		}
		log.Info("ReInit completed after resume")
	}

	csiMountConfigRequests, err := runtime.GetCsiMountExtensionRequest(s.Sandbox)
	if err != nil {
		return fmt.Errorf("failed to get csi mount request: %w", err)
	}
	if len(csiMountConfigRequests) == 0 {
		return nil
	}
	log.Info("will re-mount csi storage after resume")
	startTime := time.Now()
	csiClient := csimountutils.NewCSIMountHandler(s.Cache.GetClient(), s.Cache.GetAPIReader(), s.storageRegistry, utils.DefaultSandboxDeployNamespace)
	mountConfigs, resolveErr := resolveCSIMountConfigs(ctx, csiClient, csiMountConfigRequests)
	if resolveErr != nil {
		return resolveErr
	}
	mountOpts := config.CSIMountOptions{MountOptionList: mountConfigs}
	if _, mountErr := runtime.ProcessCSIMounts(ctx, s.Sandbox, mountOpts); mountErr != nil {
		return fmt.Errorf("failed to remount csi storage after resume: %v", mountErr)
	}
	log.Info("remount csi storage completed after resume", "costTime", time.Since(startTime))
	return nil
}

func (s *Sandbox) finishResumeOwner(ctx context.Context, ownerID string, timeout *infra.TimeoutOptions) error {
	log := klog.FromContext(ctx).WithValues("sandbox", klog.KObj(s.Sandbox))
	objectKey := client.ObjectKeyFromObject(s.Sandbox)
	err := retry.RetryOnConflict(retry.DefaultRetry, func() error {
		sbx := &agentsv1alpha1.Sandbox{}
		if err := s.Cache.GetAPIReader().Get(ctx, objectKey, sbx); err != nil {
			return err
		}
		if sbx.GetAnnotations()[agentsv1alpha1.AnnotationResumingLock] != ownerID {
			return errResumeOwnerLockLost
		}
		copied := sbx.DeepCopy()
		if timeout != nil {
			setTimeout(copied, *timeout)
		}
		if copied.Annotations != nil {
			delete(copied.Annotations, agentsv1alpha1.AnnotationResumingLock)
			delete(copied.Annotations, agentsv1alpha1.AnnotationResumingSince)
		}
		if err := s.Cache.GetClient().Update(ctx, copied); err != nil {
			return err
		}
		s.Sandbox = copied
		expectationutils.ResourceVersionExpectationExpect(copied)
		return nil
	})
	if err != nil {
		log.Error(err, "failed to finish resume owner after retries")
	}
	return err
}

func (s *Sandbox) GetState() (string, string) {
	return stateutils.GetSandboxState(s.Sandbox)
}

func (s *Sandbox) GetClaimTime() (time.Time, error) {
	claimTimestamp := s.GetAnnotations()[agentsv1alpha1.AnnotationClaimTime]
	return time.Parse(time.RFC3339, claimTimestamp)
}

// CSIMount creates a dynamic mount point in Sandbox with `sandbox-storage` cli.
// It delegates to the runtime package's CSIMount function to avoid circular dependencies.
func (s *Sandbox) CSIMount(ctx context.Context, driver string, request string) error {
	return runtime.CSIMount(ctx, s.Sandbox, driver, request)
}

func (s *Sandbox) CreateCheckpoint(ctx context.Context, opts infra.CreateCheckpointOptions) (string, error) {
	log := klog.FromContext(ctx)
	opts = ValidateAndInitCheckpointOptions(opts)
	log.Info("create checkpoint options", "options", opts)
	return CreateCheckpoint(ctx, s.Sandbox, s.Cache, opts)
}

var _ infra.Sandbox = &Sandbox{}

// resolveCSIMountConfigs converts CSIMountConfig requests into MountConfig
// by calling CSIMountOptionsConfig for each request sequentially.
func resolveCSIMountConfigs(ctx context.Context, csiClient *csimountutils.CSIMountHandler, requests []agentsv1alpha1.CSIMountConfig) ([]config.MountConfig, error) {
	log := klog.FromContext(ctx)
	results := make([]config.MountConfig, 0, len(requests))
	for _, req := range requests {
		driverName, csiReqConfigRaw, err := csiClient.CSIMountOptionsConfig(ctx, req)
		if err != nil {
			log.Error(err, "failed to generate csi mount options config", "mountConfigRequest", req)
			return nil, fmt.Errorf("failed to generate csi mount options config, err: %v", err)
		}
		results = append(results, config.MountConfig{Driver: driverName, RequestRaw: csiReqConfigRaw})
	}
	return results, nil
}

func AsSandbox(sbx *agentsv1alpha1.Sandbox, cache cache.Provider) *Sandbox {
	return &Sandbox{
		Cache:           cache,
		Sandbox:         sbx,
		storageRegistry: storages.NewStorageProvider(),
	}
}
