/*
Copyright 2025.

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

package sandboxset

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"reflect"
	"time"

	"github.com/google/uuid"
	agentsv1alpha1 "github.com/openkruise/agents/api/v1alpha1"
	"github.com/openkruise/agents/pkg/sandbox-manager/consts"
	"github.com/openkruise/agents/pkg/utils"
	"github.com/openkruise/agents/pkg/utils/expectations"
	"github.com/openkruise/agents/pkg/utils/fieldindex"
	managerutils "github.com/openkruise/agents/pkg/utils/sandbox-manager"
	stateutils "github.com/openkruise/agents/pkg/utils/sandboxutils"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/serializer"
	"k8s.io/client-go/tools/record"
	"k8s.io/klog/v2"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller"
	"sigs.k8s.io/controller-runtime/pkg/handler"
	logf "sigs.k8s.io/controller-runtime/pkg/log"
	"sigs.k8s.io/controller-runtime/pkg/manager"
)

func init() {
	flag.IntVar(&concurrentReconciles, "sandboxset-workers", concurrentReconciles, "Max concurrent workers for SandboxSet controller.")
	flag.IntVar(&initialBatchSize, "sandboxset-initial-batch-size", initialBatchSize, "The initial batch size to use for the api-server operation")
}

var (
	concurrentReconciles = 3
	initialBatchSize     = 16
)

func Add(mgr manager.Manager) error {
	err := (&Reconciler{
		Client: mgr.GetClient(),
		Scheme: mgr.GetScheme(),
	}).SetupWithManager(mgr)
	if err != nil {
		return err
	}
	klog.Infof("start SandboxSetReconciler success")
	return nil
}

// Reconciler reconciles a Sandbox object
type Reconciler struct {
	client.Client
	Scheme   *runtime.Scheme
	Recorder record.EventRecorder
	Codec    runtime.Codec
}

const (
	EventSandboxCreated       = "SandboxCreated"
	EventSandboxScaledDown    = "SandboxScaledDown"
	EventFailedSandboxDeleted = "FailedSandboxDeleted"
)

// +kubebuilder:rbac:groups=agents.kruise.io,resources=sandboxsets,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=agents.kruise.io,resources=sandboxsets/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=agents.kruise.io,resources=sandboxsets/finalizers,verbs=update

func (r *Reconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	totalStart := time.Now()
	log := logf.FromContext(ctx).WithValues("sandboxset", req.NamespacedName)
	ctx = logf.IntoContext(ctx, log)
	sbs := &agentsv1alpha1.SandboxSet{}
	if err := r.Get(ctx, req.NamespacedName, sbs); err != nil {
		if apierrors.IsNotFound(err) {
			scaleUpExpectation.DeleteExpectations(req.String())
			scaleDownExpectation.DeleteExpectations(req.String())
			return ctrl.Result{}, nil
		}
		return ctrl.Result{}, err
	}

	// Preparation
	newStatus, err := r.initNewStatus(sbs)
	if err != nil {
		log.Error(err, "failed to init new status")
		return ctrl.Result{}, err
	}
	groups, err := r.groupAllSandboxes(ctx, sbs)
	if err != nil {
		log.Error(err, "failed to group sandboxes")
		return ctrl.Result{}, err
	}
	actualReplicas := saveStatusFromGroup(newStatus, groups)

	var allErrors error

	// Step 1: perform scale
	var successes int
	var requeueAfter time.Duration
	start := time.Now()
	offset := int(sbs.Spec.Replicas - actualReplicas)
	if offset > 0 {
		successes, requeueAfter, err = r.scaleUp(ctx, offset, sbs, newStatus.UpdateRevision)
		log.Info("sandboxes created", "successes", successes, "fails", offset-successes)
	} else if offset < 0 {
		successes, requeueAfter, err = r.scaleDown(ctx, offset, sbs, groups)
		log.Info("sandboxes locked and deleted", "successes", successes, "fails", -offset-successes)
	}
	if err != nil {
		log.Error(err, "failed to perform scale", "cost", time.Since(start))
		allErrors = errors.Join(allErrors, err)
	} else {
		log.Info("scale finished", "cost", time.Since(start))
	}

	// Step 2: delete dead sandboxes
	start = time.Now()
	if err = r.deleteDeadSandboxes(ctx, groups.Dead); err != nil {
		log.Error(err, "failed to perform garbage collection")
		allErrors = errors.Join(allErrors, err)
	} else {
		log.Info("all failed sandboxes deleted", "cost", time.Since(start))
	}
	log.Info("reconcile done", "totalCost", time.Since(totalStart))
	if err = r.updateSandboxSetStatus(ctx, *newStatus, sbs); err != nil {
		log.Error(err, "failed to update sandboxset status")
		allErrors = errors.Join(allErrors, err)
	}
	return ctrl.Result{RequeueAfter: requeueAfter}, allErrors
}

// scaleUp is allowed when scaleUpExpectation is satisfied
func (r *Reconciler) scaleUp(ctx context.Context, offset int, sbs *agentsv1alpha1.SandboxSet, revision string) (int, time.Duration, error) {
	log := logf.FromContext(ctx)
	if ok, requeueAfter := scaleExpectationSatisfied(ctx, scaleUpExpectation, GetControllerKey(sbs)); !ok {
		return 0, requeueAfter, nil
	}
	log.Info("scale up", "offset", offset)
	successes, err := utils.DoItSlowly(offset, initialBatchSize, func() error {
		created, err := r.createSandbox(ctx, sbs, revision)
		if err != nil {
			log.Error(err, "failed to create sandbox")
			return err
		}
		log.V(consts.DebugLogLevel).Info("sandbox created", "sandbox", klog.KObj(created))
		return nil
	})
	return successes, 0, err
}

// scaleDown is allowed when both scaleUpExpectation and scaleDownExpectation are satisfied
func (r *Reconciler) scaleDown(ctx context.Context, offset int, sbs *agentsv1alpha1.SandboxSet, groups GroupedSandboxes) (int, time.Duration, error) {
	log := logf.FromContext(ctx)
	controllerKey := GetControllerKey(sbs)
	if ok, requeueAfter := scaleExpectationSatisfied(ctx, scaleDownExpectation, controllerKey); !ok {
		return 0, requeueAfter, nil
	}
	if ok, requeueAfter := scaleExpectationSatisfied(ctx, scaleUpExpectation, controllerKey); !ok {
		return 0, requeueAfter, nil
	}
	lock := uuid.New().String()
	log.Info("scale down", "offset", offset)
	var successes int
	for _, snapshot := range append(groups.Creating, groups.Available...) {
		if offset >= 0 {
			break
		}
		deleted, err := r.scaleDownSandbox(ctx, client.ObjectKeyFromObject(snapshot), controllerKey, lock)
		if err != nil {
			log.Error(err, "failed to scale down sandbox")
			return successes, 0, err
		}
		if deleted {
			successes++
			offset++
		}
	}
	return successes, 0, nil

}

func (r *Reconciler) createSandbox(ctx context.Context, sbs *agentsv1alpha1.SandboxSet, revision string) (*agentsv1alpha1.Sandbox, error) {
	generateName := fmt.Sprintf("%s-", sbs.Name)
	template := sbs.Spec.Template.DeepCopy()
	sbx := &agentsv1alpha1.Sandbox{
		ObjectMeta: metav1.ObjectMeta{
			GenerateName: generateName,
			Namespace:    sbs.Namespace,
			Labels:       template.Labels,
			Annotations:  template.Annotations,
		},
		Spec: agentsv1alpha1.SandboxSpec{
			Template:           *template,
			PersistentContents: sbs.Spec.PersistentContents,
		},
	}
	sbx.Annotations = clearAndInitInnerKeys(sbx.Annotations)
	sbx.Labels = clearAndInitInnerKeys(sbx.Labels)
	sbx.Labels[agentsv1alpha1.LabelSandboxPool] = sbs.Name
	sbx.Labels[agentsv1alpha1.LabelTemplateHash] = revision
	if err := ctrl.SetControllerReference(sbs, sbx, r.Scheme); err != nil {
		return nil, err
	}
	if err := r.Create(ctx, sbx); err != nil {
		return nil, err
	}
	scaleUpExpectation.ExpectScale(GetControllerKey(sbs), expectations.Create, sbx.Name)
	r.Recorder.Eventf(sbs, corev1.EventTypeNormal, EventSandboxCreated, "Sandbox %s created", klog.KObj(sbx))
	return sbx, nil
}

func (r *Reconciler) scaleDownSandbox(ctx context.Context, key client.ObjectKey, controllerKey string, lock string) (deleted bool, err error) {
	log := logf.FromContext(ctx).WithValues("sandbox", key).V(consts.DebugLogLevel)
	sbx := &agentsv1alpha1.Sandbox{}
	log.Info("try to scale down sandbox")
	if err = r.Get(ctx, key, sbx); err != nil {
		return false, client.IgnoreNotFound(err)
	}
	if sbx.Annotations[agentsv1alpha1.AnnotationLock] != "" && sbx.Annotations[agentsv1alpha1.AnnotationOwner] != consts.OwnerManagerScaleDown {
		log.Info("sandbox to be scaled down claimed before performed, skip")
		return false, nil
	}
	managerutils.LockSandbox(sbx, lock, consts.OwnerManagerScaleDown)
	if err = r.Update(ctx, sbx); err != nil {
		if apierrors.IsConflict(err) {
			return false, nil // skip
		}
		return false, fmt.Errorf("failed to lock sandbox when scaling down: %s", err)
	}
	scaleDownExpectation.ExpectScale(controllerKey, expectations.Delete, sbx.Name)
	if err = r.Delete(ctx, sbx); err != nil {
		scaleDownExpectation.ObserveScale(controllerKey, expectations.Delete, sbx.Name)
		log.Error(err, "failed to delete sandbox")
		return false, err
	}
	log.Info("sandbox locked and deleted")
	r.Recorder.Eventf(sbx, corev1.EventTypeNormal, EventSandboxScaledDown, "Sandbox %s locked and deleted", klog.KObj(sbx))
	return true, nil
}

func (r *Reconciler) deleteDeadSandboxes(ctx context.Context, failed []*agentsv1alpha1.Sandbox) error {
	log := logf.FromContext(ctx).V(consts.DebugLogLevel)
	failNum := 0
	for _, sbx := range failed {
		if sbx.DeletionTimestamp != nil {
			continue
		}
		if err := r.Delete(ctx, sbx); err != nil {
			log.Error(err, "failed to delete sandbox")
			failNum++
		}
		log.Info("sandbox deleted", "sandbox", klog.KObj(sbx))
		r.Recorder.Eventf(sbx, corev1.EventTypeNormal, EventFailedSandboxDeleted, "Sandbox %s deleted", klog.KObj(sbx))
	}
	if failNum > 0 {
		return fmt.Errorf("failed to delete %d sandboxes", failNum)
	}
	return nil
}

func (r *Reconciler) updateSandboxSetStatus(ctx context.Context, newStatus agentsv1alpha1.SandboxSetStatus, sbs *agentsv1alpha1.SandboxSet) error {
	log := logf.FromContext(ctx).V(consts.DebugLogLevel)
	clone := sbs.DeepCopy()
	if err := r.Get(ctx, client.ObjectKey{Namespace: sbs.Namespace, Name: sbs.Name}, clone); err != nil {
		log.Error(err, "failed to get updated sandboxset from client")
		return client.IgnoreNotFound(err)
	}
	if reflect.DeepEqual(clone.Status, newStatus) {
		return nil
	}
	clone.Status = newStatus
	err := r.Status().Update(ctx, clone)
	if err == nil {
		log.Info("update sandboxset status success", "status", utils.DumpJson(newStatus))
	} else {
		log.Error(err, "update sandboxset status failed")
	}
	return err
}

func (r *Reconciler) groupAllSandboxes(ctx context.Context, sbs *agentsv1alpha1.SandboxSet) (GroupedSandboxes, error) {
	log := logf.FromContext(ctx)
	sandboxList := &agentsv1alpha1.SandboxList{}
	if err := r.List(ctx, sandboxList,
		client.InNamespace(sbs.Namespace),
		client.MatchingFields{fieldindex.IndexNameForOwnerRefUID: string(sbs.UID)},
		client.UnsafeDisableDeepCopy,
	); err != nil {
		return GroupedSandboxes{}, err
	}
	groups := GroupedSandboxes{}
	for i := range sandboxList.Items {
		sbx := &sandboxList.Items[i]
		scaleUpExpectation.ObserveScale(GetControllerKey(sbs), expectations.Create, sbx.Name)
		debugLog := log.V(consts.DebugLogLevel).WithValues("sandbox", sbx.Name)
		state, reason := stateutils.GetSandboxState(sbx)
		switch state {
		case agentsv1alpha1.SandboxStateCreating:
			groups.Creating = append(groups.Creating, sbx)
		case agentsv1alpha1.SandboxStateAvailable:
			groups.Available = append(groups.Available, sbx)
		case agentsv1alpha1.SandboxStateRunning:
			fallthrough
		case agentsv1alpha1.SandboxStatePaused:
			groups.Used = append(groups.Used, sbx)
		case agentsv1alpha1.SandboxStateDead:
			groups.Dead = append(groups.Dead, sbx)
		default: // unknown, impossible, just in case
			return GroupedSandboxes{}, fmt.Errorf("cannot find state for sandbox %s", sbx.Name)
		}
		debugLog.Info("sandbox is grouped", "state", state, "reason", reason)
	}
	log.Info("sandbox group done", "total", len(sandboxList.Items), "creating", len(groups.Creating),
		"available", len(groups.Available), "used", len(groups.Used), "failed", len(groups.Dead))
	return groups, nil
}

// SetupWithManager sets up the controller with the Manager.
func (r *Reconciler) SetupWithManager(mgr ctrl.Manager) error {
	controllerName := "sandboxset-controller"
	r.Recorder = mgr.GetEventRecorderFor(controllerName)
	r.Codec = serializer.NewCodecFactory(mgr.GetScheme()).LegacyCodec(agentsv1alpha1.SchemeGroupVersion)
	return ctrl.NewControllerManagedBy(mgr).
		Named(controllerName).
		WithOptions(controller.Options{MaxConcurrentReconciles: concurrentReconciles}).
		Watches(&agentsv1alpha1.SandboxSet{}, &handler.EnqueueRequestForObject{}).
		Watches(&agentsv1alpha1.Sandbox{}, &SandboxEventHandler{}).
		Complete(r)
}
