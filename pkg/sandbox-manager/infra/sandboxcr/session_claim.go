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

package sandboxcr

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"sync/atomic"
	"time"

	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/util/validation"
	"k8s.io/apimachinery/pkg/util/wait"
	"k8s.io/klog/v2"
	"k8s.io/utils/ptr"
	"sigs.k8s.io/controller-runtime/pkg/client"

	"github.com/openkruise/agents/api/v1alpha1"
	managererrors "github.com/openkruise/agents/pkg/sandbox-manager/errors"
	"github.com/openkruise/agents/pkg/sandbox-manager/infra"
	"github.com/openkruise/agents/pkg/utils/expectations"
)

var claimScaleExpectations = expectations.NewScaleExpectations()
var claimScaleObserverReady atomic.Bool

func sessionClaimName(sessionID string) string {
	if errs := validation.IsDNS1123Label(sessionID); len(errs) == 0 {
		return sessionID
	}
	sum := sha256.Sum256([]byte(sessionID))
	return "sess-" + hex.EncodeToString(sum[:16])
}

func IsSessionClaim(claim *v1alpha1.SandboxClaim) bool {
	return claim != nil && claim.Labels[v1alpha1.LabelSandboxSession] == v1alpha1.True
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

func (i *Infra) claimSandboxWithKey(ctx context.Context, opts infra.ClaimSandboxOptions) (infra.Sandbox, infra.ClaimMetrics, error) {
	metrics := infra.ClaimMetrics{}
	key := opts.Idempotency.Key
	if key == "" {
		return nil, metrics, managererrors.NewError(managererrors.ErrorBadRequest, "idempotency key is required")
	}
	if opts.Namespace == "" {
		return nil, metrics, managererrors.NewError(managererrors.ErrorBadRequest, "namespace is required")
	}

	claim, created, err := i.ensureSessionClaim(ctx, opts)
	if err != nil {
		return nil, metrics, err
	}

	delivered, deliveredErr := i.sessionDeliveredSandbox(ctx, claim)
	switch {
	case deliveredErr != nil:
		return nil, metrics, deliveredErr
	case delivered != nil:
		// Existing delivery: do not close Accepted here. Activate delays
		// accept until this call's Connect write is persisted.
		return delivered, metrics, nil
	case sessionClaimFailed(claim):
		return nil, metrics, sessionClaimFailure(claim)
	default:
		notifyAccepted(opts.Idempotency.Accepted)
	}

	waitCtx := ctx
	if opts.ClaimTimeout > 0 {
		var cancel context.CancelFunc
		waitCtx, cancel = context.WithTimeout(ctx, opts.ClaimTimeout)
		defer cancel()
	}
	log := klog.FromContext(ctx).WithValues("sessionID", key, "claim", klog.KObj(claim), "created", created)
	log.Info("waiting for session claim delivery")
	sbx, err := i.waitSessionDelivery(waitCtx, claim)
	return sbx, metrics, err
}

func (i *Infra) ensureSessionClaim(ctx context.Context, opts infra.ClaimSandboxOptions) (*v1alpha1.SandboxClaim, bool, error) {
	name := sessionClaimName(opts.Idempotency.Key)
	existing, err := i.getSessionClaim(ctx, opts.Namespace, name)
	if err == nil {
		if err := validateSessionClaimIdentity(existing, opts.Idempotency.Key); err != nil {
			return nil, false, err
		}
		return existing, false, nil
	}
	if !apierrors.IsNotFound(err) {
		return nil, false, managererrors.WrapError(managererrors.ErrorInternal, err, "get session claim %s", name)
	}

	claim := newSessionClaim(opts)
	if err := i.Cache.GetClient().Create(ctx, claim); err != nil {
		if !apierrors.IsAlreadyExists(err) {
			return nil, false, managererrors.WrapError(managererrors.ErrorInternal, err, "create session claim %s", name)
		}
		existing, getErr := i.getSessionClaim(ctx, opts.Namespace, name)
		if getErr != nil {
			return nil, false, managererrors.WrapError(managererrors.ErrorInternal, getErr, "get session claim %s after create conflict", name)
		}
		if err := validateSessionClaimIdentity(existing, opts.Idempotency.Key); err != nil {
			return nil, false, err
		}
		return existing, false, nil
	}
	return claim, true, nil
}

func newSessionClaim(opts infra.ClaimSandboxOptions) *v1alpha1.SandboxClaim {
	claimTimeout := opts.ClaimTimeout
	if claimTimeout <= 0 {
		claimTimeout = DefaultClaimTimeout
	}
	claim := &v1alpha1.SandboxClaim{
		ObjectMeta: metav1.ObjectMeta{
			Name:      sessionClaimName(opts.Idempotency.Key),
			Namespace: opts.Namespace,
			Labels: map[string]string{
				v1alpha1.LabelSandboxSession: v1alpha1.True,
			},
			Annotations: map[string]string{
				v1alpha1.AnnotationSandboxSessionID: opts.Idempotency.Key,
			},
		},
		Spec: v1alpha1.SandboxClaimSpec{
			TemplateName:      opts.Template,
			Replicas:          ptr.To(int32(1)),
			TTLAfterCompleted: &metav1.Duration{Duration: -1 * time.Second},
			ClaimTimeout:      &metav1.Duration{Duration: claimTimeout},
			CreateOnNoStock:   true,
		},
	}
	if opts.PostClaim != nil {
		claim.Spec.PostClaim = postClaimToSpec(opts.PostClaim)
	}
	return claim
}

func postClaimToSpec(run *infra.PostClaimRun) *v1alpha1.SandboxClaimPostClaim {
	if run == nil || len(run.Command) == 0 {
		return nil
	}
	out := &v1alpha1.SandboxClaimPostClaim{
		Run: &v1alpha1.SandboxClaimPostClaimRun{Command: append([]string(nil), run.Command...)},
	}
	if run.Timeout > 0 {
		out.Run.Timeout = &metav1.Duration{Duration: run.Timeout}
	}
	return out
}

func PostClaimFromSpec(claim *v1alpha1.SandboxClaim) *infra.PostClaimRun {
	if claim == nil || claim.Spec.PostClaim == nil || claim.Spec.PostClaim.Run == nil {
		return nil
	}
	run := claim.Spec.PostClaim.Run
	out := &infra.PostClaimRun{Command: append([]string(nil), run.Command...)}
	if run.Timeout != nil {
		out.Timeout = run.Timeout.Duration
	}
	return out
}

func validateSessionClaimIdentity(claim *v1alpha1.SandboxClaim, sessionID string) error {
	if !IsSessionClaim(claim) {
		return managererrors.NewError(managererrors.ErrorConflict, "session key name %s collides with a non-session claim", claim.Name)
	}
	got := claim.Annotations[v1alpha1.AnnotationSandboxSessionID]
	if got != sessionID {
		return managererrors.NewError(managererrors.ErrorConflict, "session key name %s is bound to a different session", claim.Name)
	}
	return nil
}

func (i *Infra) getSessionClaim(ctx context.Context, namespace, name string) (*v1alpha1.SandboxClaim, error) {
	claim := &v1alpha1.SandboxClaim{}
	err := i.Cache.GetClient().Get(ctx, client.ObjectKey{Namespace: namespace, Name: name}, claim)
	if err != nil {
		return nil, err
	}
	return claim, nil
}

func (i *Infra) waitSessionDelivery(ctx context.Context, claim *v1alpha1.SandboxClaim) (infra.Sandbox, error) {
	var delivered infra.Sandbox
	err := wait.PollUntilContextCancel(ctx, RetryInterval, true, func(pollCtx context.Context) (bool, error) {
		current, getErr := i.getSessionClaim(pollCtx, claim.Namespace, claim.Name)
		if getErr != nil {
			if apierrors.IsNotFound(getErr) {
				return false, managererrors.NewError(managererrors.ErrorNotFound, "session claim %s was deleted", claim.Name)
			}
			if pollCtx.Err() != nil {
				return false, pollCtx.Err()
			}
			return false, nil
		}
		sbx, deliveredErr := i.sessionDeliveredSandbox(pollCtx, current)
		if deliveredErr != nil {
			return false, deliveredErr
		}
		if sbx != nil {
			delivered = sbx
			return true, nil
		}
		if sessionClaimFailed(current) {
			return false, sessionClaimFailure(current)
		}
		return false, nil
	})
	if err != nil {
		return nil, err
	}
	return delivered, nil
}

func sessionClaimFailed(claim *v1alpha1.SandboxClaim) bool {
	if claim.Status.Phase != v1alpha1.SandboxClaimPhaseCompleted {
		return false
	}
	if meta.IsStatusConditionTrue(claim.Status.Conditions, string(v1alpha1.SandboxClaimConditionTimedOut)) {
		return true
	}
	return claim.Status.ClaimedReplicas == 0
}

func sessionClaimFailure(claim *v1alpha1.SandboxClaim) error {
	msg := claim.Status.Message
	if msg == "" {
		msg = "session claim completed without a delivered sandbox"
	}
	return managererrors.NewError(managererrors.ErrorInternal, "%s", msg)
}

func (i *Infra) sessionDeliveredSandbox(ctx context.Context, claim *v1alpha1.SandboxClaim) (infra.Sandbox, error) {
	list := &v1alpha1.SandboxList{}
	if err := i.Cache.GetClient().List(ctx, list, client.InNamespace(claim.Namespace), client.MatchingLabels{
		v1alpha1.LabelSandboxClaimName: claim.Name,
	}); err != nil {
		return nil, managererrors.WrapError(managererrors.ErrorInternal, err, "list sandboxes for session claim %s", claim.Name)
	}
	var delivered *v1alpha1.Sandbox
	for idx := range list.Items {
		sbx := &list.Items[idx]
		if sbx.Annotations[v1alpha1.AnnotationClaimDeliveryComplete] != v1alpha1.True {
			continue
		}
		if delivered != nil {
			return nil, managererrors.NewError(managererrors.ErrorInternal, "session claim %s has more than one delivered sandbox", claim.Name)
		}
		delivered = sbx
	}
	if delivered != nil {
		return AsSandbox(delivered.DeepCopy(), i.Cache), nil
	}
	if claim.Status.Phase == v1alpha1.SandboxClaimPhaseCompleted && claim.Status.ClaimedReplicas > 0 {
		return nil, fmt.Errorf("%w: session %s", infra.ErrSessionSandboxMissing, claim.Annotations[v1alpha1.AnnotationSandboxSessionID])
	}
	return nil, nil
}

func (i *Infra) lookupSessionSandbox(ctx context.Context, opts infra.GetSandboxOptions) (infra.Sandbox, error) {
	name := sessionClaimName(opts.SessionID)
	claim, err := i.getSessionClaim(ctx, opts.Namespace, name)
	if err != nil {
		if apierrors.IsNotFound(err) {
			return nil, fmt.Errorf("%w: session %s", infra.ErrSandboxNotFound, opts.SessionID)
		}
		return nil, err
	}
	if err := validateSessionClaimIdentity(claim, opts.SessionID); err != nil {
		return nil, err
	}
	sbx, err := i.sessionDeliveredSandbox(ctx, claim)
	if err != nil {
		return nil, err
	}
	if sbx == nil {
		if sessionClaimFailed(claim) {
			return nil, sessionClaimFailure(claim)
		}
		return nil, fmt.Errorf("%w: session %s", infra.ErrSandboxNotFound, opts.SessionID)
	}
	return sbx, nil
}

func (i *Infra) ListSessionKeys(ctx context.Context, opts infra.ListSessionKeysOptions) ([]infra.SessionKeyInfo, error) {
	list := &v1alpha1.SandboxClaimList{}
	if err := i.Cache.GetClient().List(ctx, list, client.InNamespace(opts.Namespace), client.MatchingLabels{
		v1alpha1.LabelSandboxSession: v1alpha1.True,
	}); err != nil {
		return nil, managererrors.WrapError(managererrors.ErrorInternal, err, "list session claims")
	}
	out := make([]infra.SessionKeyInfo, 0, len(list.Items))
	for idx := range list.Items {
		claim := &list.Items[idx]
		sessionID := claim.Annotations[v1alpha1.AnnotationSandboxSessionID]
		if sessionID == "" {
			continue
		}
		info := infra.SessionKeyInfo{SessionID: sessionID, Failed: sessionClaimFailed(claim)}
		out = append(out, info)
	}
	return out, nil
}

func (i *Infra) DeleteSessionKey(ctx context.Context, opts infra.DeleteSessionKeyOptions) error {
	if opts.SessionID == "" {
		return managererrors.NewError(managererrors.ErrorBadRequest, "session id is required")
	}
	name := sessionClaimName(opts.SessionID)
	claim, err := i.getSessionClaim(ctx, opts.Namespace, name)
	if err != nil {
		if apierrors.IsNotFound(err) {
			return nil
		}
		return managererrors.WrapError(managererrors.ErrorInternal, err, "get session claim %s", name)
	}
	if err := validateSessionClaimIdentity(claim, opts.SessionID); err != nil {
		return err
	}
	uid := claim.UID
	policy := metav1.DeletePropagationBackground
	err = i.Cache.GetClient().Delete(ctx, claim, &client.DeleteOptions{
		Preconditions:     &metav1.Preconditions{UID: &uid},
		PropagationPolicy: &policy,
	})
	if apierrors.IsNotFound(err) {
		return nil
	}
	if err != nil {
		return managererrors.WrapError(managererrors.ErrorInternal, err, "delete session claim %s", name)
	}
	return nil
}

func (i *Infra) registerClaimScaleObserver() error {
	if i.Cache == nil {
		return nil
	}
	defer func() {
		if rec := recover(); rec != nil {
			klog.ErrorS(fmt.Errorf("%v", rec), "failed to register claim scale observer")
		}
	}()
	_, err := i.Cache.AddSandboxEventHandler(context.Background(), newClaimScaleHandler())
	if err != nil {
		klog.ErrorS(err, "failed to register claim scale observer")
		return nil
	}
	claimScaleObserverReady.Store(true)
	return nil
}

func newClaimScaleHandler() *claimScaleHandler {
	return &claimScaleHandler{}
}

type claimScaleHandler struct{}

func (h *claimScaleHandler) OnAdd(obj interface{}, _ bool) {
	observeClaimScale(obj, expectations.Create)
}

func (h *claimScaleHandler) OnUpdate(_, newObj interface{}) {
	observeClaimScale(newObj, expectations.Create)
}

func (h *claimScaleHandler) OnDelete(obj interface{}) {
	observeClaimScale(obj, expectations.Delete)
}

func observeClaimScale(obj interface{}, action expectations.ScaleAction) {
	sbx, ok := obj.(*v1alpha1.Sandbox)
	if !ok {
		return
	}
	uid := claimUIDFromOwner(sbx)
	if uid == "" {
		return
	}
	claimScaleExpectations.ObserveScale(uid, action, sbx.Name)
}

func claimUIDFromOwner(sbx *v1alpha1.Sandbox) string {
	for _, ref := range sbx.GetOwnerReferences() {
		if ref.Kind == v1alpha1.SandboxClaimControllerKind.Kind && ref.UID != "" {
			return string(ref.UID)
		}
	}
	return ""
}

func claimScaleExpectationUnsatisfied(claimUID string) bool {
	if !claimScaleObserverReady.Load() || claimUID == "" {
		return false
	}
	satisfied, _, _ := claimScaleExpectations.SatisfiedExpectations(claimUID)
	return !satisfied
}

func expectClaimScale(claimUID string, action expectations.ScaleAction, name string) {
	if !claimScaleObserverReady.Load() || claimUID == "" || name == "" {
		return
	}
	claimScaleExpectations.ExpectScale(claimUID, action, name)
}
