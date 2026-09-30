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

package e2e

import (
	"context"
	"encoding/json"
	"fmt"
	"os/exec"
	"time"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"

	kruiseappsv1alpha1 "github.com/openkruise/kruise-api/apps/v1alpha1"

	agentsv1alpha1 "github.com/openkruise/agents/api/v1alpha1"
	"github.com/openkruise/agents/pkg/utils"
)

const (
	// virtualNodeLabelKey and virtualNodeLabelValue are the node label the
	// controller reads to tell virtual-kubelet nodes from real ones.
	virtualNodeLabelKey   = "type"
	virtualNodeLabelValue = "virtual-kubelet"

	probeContainerName = "main"

	probeStateName    = "state"
	probeScheduleName = "schedule"

	// stateProbeCommand reports "active" until the test writes "idle" into
	// /tmp/probe-state: that file is the only activity signal the probe has.
	stateProbeCommand = `if [ -f /tmp/probe-state ]; then cat /tmp/probe-state; else printf active; fi`
	// scheduleProbeCommand reports the next scheduled task as a unix timestamp,
	// or 0 when no task is scheduled.
	scheduleProbeCommand = `if [ -f /tmp/probe-schedule ]; then cat /tmp/probe-schedule; else printf 0; fi`

	// probePeriodSeconds is short so the end-to-end flow below stays in the
	// minute range instead of the default 10s kruise would apply to every step.
	probePeriodSeconds = 2

	probeIdleThreshold  = 15 * time.Second
	probeResumeLeadTime = 15 * time.Second
	// probeScheduleAhead is how far ahead of "now" the test schedules the fake
	// task, leaving room for the pause to complete before the resume fires.
	probeScheduleAhead = 90 * time.Second
)

// probeAnnotationItem mirrors the entries written to the kruise.io/podprobe
// annotation (PodProbeMarker Serverless protocol).
type probeAnnotationItem struct {
	ContainerName    string       `json:"containerName"`
	Name             string       `json:"name"`
	PodConditionType string       `json:"podConditionType"`
	Probe            corev1.Probe `json:"probe"`
}

var _ = Describe("PodProbeMarker probe delivery", func() {
	var (
		ctx       = context.Background()
		namespace string
	)

	BeforeEach(func() {
		if !podProbeMarkerCRDInstalled(ctx) {
			Skip("PodProbeMarker CRD is not installed; these specs need a cluster running OpenKruise with AutoPauseController and KruiseIntegration enabled")
		}
		namespace = createNamespace(ctx)
	})

	AfterEach(func() {
		ns := &corev1.Namespace{}
		if err := k8sClient.Get(ctx, types.NamespacedName{Name: namespace}, ns); err == nil {
			_ = k8sClient.Delete(ctx, ns)
		}
	})

	Context("on a real node", func() {
		It("should deliver probes through a PodProbeMarker and pause/resume the sandbox end to end", func() {
			sandbox := newProbeSandbox(namespace)
			sandbox.Spec.AutoPausePolicy = probeAutoPausePolicy()
			nn := types.NamespacedName{Name: sandbox.Name, Namespace: namespace}

			By("Creating a Sandbox with activity and schedule probes")
			Expect(k8sClient.Create(ctx, sandbox)).To(Succeed())
			waitForSandboxPhase(ctx, nn, agentsv1alpha1.SandboxRunning, 5*time.Minute)

			By("Verifying a PodProbeMarker is created for the sandbox pod")
			var ppm *kruiseappsv1alpha1.PodProbeMarker
			Eventually(func() error {
				ppm = &kruiseappsv1alpha1.PodProbeMarker{}
				return k8sClient.Get(ctx, nn, ppm)
			}, time.Minute, time.Second).Should(Succeed())

			By("Verifying the marker selects the pod by the sandbox uid label")
			// Re-fetch the persisted Sandbox: the UID is assigned by the API
			// server after creation and is what the pod's sandbox-uid label and
			// the marker selector carry.
			persisted := &agentsv1alpha1.Sandbox{}
			Expect(k8sClient.Get(ctx, nn, persisted)).To(Succeed())
			pod := getPodOrFail(ctx, nn)
			Expect(pod.Labels).To(
				HaveKeyWithValue(agentsv1alpha1.LabelSandboxUID, string(persisted.UID)))
			Expect(ppm.Spec.Selector).NotTo(BeNil())
			Expect(ppm.Spec.Selector.MatchLabels).To(
				HaveKeyWithValue(agentsv1alpha1.LabelSandboxUID, string(persisted.UID)))
			Expect(ppm.Spec.Selector.MatchLabels).To(
				HaveLen(1), "selector requirements are ANDed, so it must not also require the name label")
			Expect(ppm.Spec.Probes).To(HaveLen(2))

			probesByName := map[string]kruiseappsv1alpha1.PodContainerProbe{}
			for _, probe := range ppm.Spec.Probes {
				probesByName[probe.Name] = probe
			}
			stateProbe, ok := probesByName[probeStateName]
			Expect(ok).To(BeTrue())
			Expect(stateProbe.ContainerName).To(Equal(probeContainerName))
			Expect(stateProbe.PodConditionType).To(Equal(agentsv1alpha1.ProbeConditionType(probeStateName)))
			Expect(stateProbe.Probe.Exec).NotTo(BeNil())
			Expect(stateProbe.Probe.Exec.Command).To(Equal([]string{"sh", "-c", stateProbeCommand}))
			scheduleProbe, ok := probesByName[probeScheduleName]
			Expect(ok).To(BeTrue())
			Expect(scheduleProbe.PodConditionType).To(Equal(agentsv1alpha1.ProbeConditionType(probeScheduleName)))

			By("Verifying the PodProbeMarker is owned by the sandbox pod so it is garbage collected with it")
			pod = getPodOrFail(ctx, nn)
			Expect(ppm.OwnerReferences).To(HaveLen(1))
			Expect(ppm.OwnerReferences[0].Kind).To(Equal("Pod"))
			Expect(ppm.OwnerReferences[0].Name).To(Equal(pod.Name))
			Expect(ppm.OwnerReferences[0].UID).To(Equal(pod.UID))

			By("Verifying the creation-time annotation is left in place: on a real node it is inert, kruise-daemon runs the marker instead")
			Expect(pod.Annotations).To(HaveKey(agentsv1alpha1.AnnotationPodProbe))

			By("Waiting for the kruise-daemon probe results to reach the pod and the sandbox status")
			Eventually(func() string {
				return probeResult(ctx, nn, sandbox.Name, probeStateName)
			}, 2*time.Minute, time.Second).Should(Equal("True:active"))
			Eventually(func() string {
				return probeResult(ctx, nn, sandbox.Name, probeScheduleName)
			}, 2*time.Minute, time.Second).Should(Equal("True:0"))

			By("Publishing a future task time so the resume decision is recorded before the pause")
			scheduledAt := time.Now().Add(probeScheduleAhead).Truncate(time.Second)
			execInPod(namespace, sandbox.Name,
				fmt.Sprintf("printf %%s %d > /tmp/probe-schedule", scheduledAt.Unix()))

			var nextResumeTime *metav1.Time
			Eventually(func() *metav1.Time {
				sbx := getSandbox(ctx, nn)
				for i := range sbx.Status.Schedules {
					if sbx.Status.Schedules[i].Reason != agentsv1alpha1.ScheduleReasonProbedSchedule {
						continue
					}
					nextResumeTime = sbx.Status.Schedules[i].NextResumeTime
					return nextResumeTime
				}
				return nil
			}, time.Minute, time.Second).ShouldNot(BeNil())
			Expect(nextResumeTime.Time).To(BeTemporally("~", scheduledAt.Add(-probeResumeLeadTime), 5*time.Second))

			By("Reporting the agent as idle through the probe")
			execInPod(namespace, sandbox.Name, "printf %s idle > /tmp/probe-state")

			By("Waiting for the idle probe result to schedule a pause")
			Eventually(func() *metav1.Time {
				sbx := getSandbox(ctx, nn)
				for i := range sbx.Status.Schedules {
					if sbx.Status.Schedules[i].Reason == agentsv1alpha1.ScheduleReasonProbedIdle {
						return sbx.Status.Schedules[i].NextPauseTime
					}
				}
				return nil
			}, 2*time.Minute, time.Second).ShouldNot(BeNil())

			By("Waiting for the sandbox to auto-pause after the idle threshold")
			waitForSandboxPhase(ctx, nn, agentsv1alpha1.SandboxPaused, 3*time.Minute)
			Expect(getSandbox(ctx, nn).Spec.Paused).To(BeTrue())

			By("Waiting for the pause to complete: the pod is deleted and Paused becomes true")
			Eventually(func() metav1.ConditionStatus {
				cond := getPausedCondition(getSandbox(ctx, nn))
				if cond == nil {
					return ""
				}
				return cond.Status
			}, 3*time.Minute, time.Second).Should(Equal(metav1.ConditionTrue))

			By("Verifying the pause deleted the pod and garbage collected its PodProbeMarker")
			Eventually(func() bool {
				return apierrors.IsNotFound(k8sClient.Get(ctx, nn, &corev1.Pod{}))
			}, 2*time.Minute, time.Second).Should(BeTrue())
			Eventually(func() bool {
				return apierrors.IsNotFound(k8sClient.Get(ctx, nn, &kruiseappsv1alpha1.PodProbeMarker{}))
			}, 2*time.Minute, time.Second).Should(BeTrue())

			By("Waiting for the sandbox to auto-resume at the recorded schedule time")
			waitForSandboxPhase(ctx, nn, agentsv1alpha1.SandboxRunning, 3*time.Minute)
			resumed := getSandbox(ctx, nn)
			Expect(resumed.Spec.Paused).To(BeFalse())

			By("Verifying the resumed sandbox runs a fresh pod whose probes report again")
			Eventually(func() types.UID {
				resumedPod := &corev1.Pod{}
				if err := k8sClient.Get(ctx, nn, resumedPod); err != nil {
					return ""
				}
				return resumedPod.UID
			}, 2*time.Minute, time.Second).ShouldNot(Equal(pod.UID))
			Eventually(func() string {
				return probeResult(ctx, nn, sandbox.Name, probeStateName)
			}, 2*time.Minute, time.Second).Should(Equal("True:active"))
		})
	})

	Context("on a virtual-kubelet node", func() {
		It("should deliver probes through the kruise.io/podprobe annotation instead of a PodProbeMarker", func() {
			By("Labeling a node as virtual-kubelet")
			nodeName := pickNodeForVirtualKubelet(ctx).Name
			DeferCleanup(func() {
				patchNodeLabel(ctx, nodeName, virtualNodeLabelKey, "")
			})
			patchNodeLabel(ctx, nodeName, virtualNodeLabelKey, virtualNodeLabelValue)

			By("Creating a Sandbox that can only be scheduled on the virtual-kubelet node")
			sandbox := newProbeSandbox(namespace)
			sandbox.Spec.Template.Spec.NodeSelector = map[string]string{
				virtualNodeLabelKey: virtualNodeLabelValue,
			}
			sandbox.Spec.Template.Spec.Tolerations = []corev1.Toleration{{
				Key:      "node-role.kubernetes.io/control-plane",
				Operator: corev1.TolerationOpExists,
				Effect:   corev1.TaintEffectNoSchedule,
			}}

			Expect(k8sClient.Create(ctx, sandbox)).To(Succeed())
			nn := types.NamespacedName{Name: sandbox.Name, Namespace: namespace}
			waitForSandboxPhase(ctx, nn, agentsv1alpha1.SandboxRunning, 5*time.Minute)

			By("Verifying the pod carries the kruise.io/podprobe annotation")
			var annotation string
			Eventually(func() string {
				pod := &corev1.Pod{}
				if err := k8sClient.Get(ctx, nn, pod); err != nil {
					return ""
				}
				annotation = pod.Annotations[agentsv1alpha1.AnnotationPodProbe]
				return annotation
			}, 2*time.Minute, time.Second).ShouldNot(BeEmpty())

			var items []probeAnnotationItem
			Expect(json.Unmarshal([]byte(annotation), &items)).To(Succeed())
			Expect(items).To(HaveLen(2))

			itemsByName := map[string]probeAnnotationItem{}
			for _, item := range items {
				itemsByName[item.Name] = item
			}
			stateItem, ok := itemsByName[probeStateName]
			Expect(ok).To(BeTrue())
			Expect(stateItem.ContainerName).To(Equal(probeContainerName))
			Expect(stateItem.PodConditionType).To(Equal(agentsv1alpha1.ProbeConditionType(probeStateName)))
			Expect(stateItem.Probe.Exec).NotTo(BeNil())
			Expect(stateItem.Probe.Exec.Command).To(Equal([]string{"sh", "-c", stateProbeCommand}))
			scheduleItem, ok := itemsByName[probeScheduleName]
			Expect(ok).To(BeTrue())
			Expect(scheduleItem.PodConditionType).To(Equal(agentsv1alpha1.ProbeConditionType(probeScheduleName)))

			By("Verifying no PodProbeMarker is created on a virtual-kubelet node")
			Consistently(func() bool {
				return apierrors.IsNotFound(k8sClient.Get(ctx, nn, &kruiseappsv1alpha1.PodProbeMarker{}))
			}, 10*time.Second, time.Second).Should(BeTrue())
		})
	})

	Context("before the pod is scheduled", func() {
		It("should carry the podprobe annotation because the node type is not known yet", func() {
			By("Creating a Sandbox whose pod cannot be scheduled")
			sandbox := newProbeSandbox(namespace)
			sandbox.Spec.Template.Spec.NodeSelector = map[string]string{"agents.kruise.io/e2e-unschedulable": "true"}

			Expect(k8sClient.Create(ctx, sandbox)).To(Succeed())
			nn := types.NamespacedName{Name: sandbox.Name, Namespace: namespace}

			By("Verifying the pending pod already carries the kruise.io/podprobe annotation")
			Eventually(func() string {
				pending := &corev1.Pod{}
				if err := k8sClient.Get(ctx, nn, pending); err != nil {
					return ""
				}
				return pending.Annotations[agentsv1alpha1.AnnotationPodProbe]
			}, time.Minute, time.Second).ShouldNot(BeEmpty())

			By("Verifying no PodProbeMarker is created while the pod is unscheduled")
			Consistently(func() bool {
				return apierrors.IsNotFound(k8sClient.Get(ctx, nn, &kruiseappsv1alpha1.PodProbeMarker{}))
			}, 10*time.Second, time.Second).Should(BeTrue())
		})

		It("should skip the annotation when the node selector excludes virtual nodes", func() {
			By("Selecting a non-virtual node type and a unique nonexistent label, so the pod stays pending")
			impossibleSelectorKey := fmt.Sprintf("agents.kruise.io/e2e-unschedulable-%d", time.Now().UnixNano())
			sandbox := newProbeSandbox(namespace)
			sandbox.Spec.Template.Spec.NodeSelector = map[string]string{
				virtualNodeLabelKey:   "not-virtual-kubelet",
				impossibleSelectorKey: "true",
			}

			Expect(k8sClient.Create(ctx, sandbox)).To(Succeed())
			nn := types.NamespacedName{Name: sandbox.Name, Namespace: namespace}

			// The pod must stay unscheduled: EnsureProbe only acts once spec.nodeName
			// is set, so the annotation reflects the creation-time decision alone.
			By("Verifying the pod stays pending")
			Eventually(func() corev1.PodPhase {
				pending := &corev1.Pod{}
				if err := k8sClient.Get(ctx, nn, pending); err != nil {
					return ""
				}
				return pending.Status.Phase
			}, time.Minute, time.Second).Should(Equal(corev1.PodPending))
			Consistently(func() string {
				pending := &corev1.Pod{}
				if err := k8sClient.Get(ctx, nn, pending); err != nil {
					return "pod gone"
				}
				return pending.Spec.NodeName
			}, 10*time.Second, time.Second).Should(BeEmpty())

			By("Verifying the pod never got the kruise.io/podprobe annotation or a PodProbeMarker")
			Consistently(func() string {
				pending := &corev1.Pod{}
				if err := k8sClient.Get(ctx, nn, pending); err != nil {
					return "pod gone"
				}
				return pending.Annotations[agentsv1alpha1.AnnotationPodProbe]
			}, 15*time.Second, time.Second).Should(BeEmpty())
			Consistently(func() bool {
				return apierrors.IsNotFound(k8sClient.Get(ctx, nn, &kruiseappsv1alpha1.PodProbeMarker{}))
			}, 10*time.Second, time.Second).Should(BeTrue())
		})
	})
})

// newProbeSandbox builds a sandbox whose pod runs a single container with an
// activity probe and a schedule probe. The sandbox name doubles as the pod name.
func newProbeSandbox(namespace string) *agentsv1alpha1.Sandbox {
	return &agentsv1alpha1.Sandbox{
		ObjectMeta: metav1.ObjectMeta{
			Name:      fmt.Sprintf("probe-e2e-%d", time.Now().UnixNano()),
			Namespace: namespace,
		},
		Spec: agentsv1alpha1.SandboxSpec{
			EmbeddedSandboxTemplate: agentsv1alpha1.EmbeddedSandboxTemplate{
				Template: &corev1.PodTemplateSpec{
					Spec: corev1.PodSpec{
						Containers: []corev1.Container{
							{
								Name:  probeContainerName,
								Image: "nginx:stable-alpine3.20",
							},
						},
						RestartPolicy: corev1.RestartPolicyNever,
					},
				},
			},
			Probes: []agentsv1alpha1.Probe{
				{
					Name: probeStateName,
					Probe: corev1.Probe{
						ProbeHandler: corev1.ProbeHandler{
							Exec: &corev1.ExecAction{Command: []string{"sh", "-c", stateProbeCommand}},
						},
						PeriodSeconds: probePeriodSeconds,
					},
				},
				{
					Name: probeScheduleName,
					Probe: corev1.Probe{
						ProbeHandler: corev1.ProbeHandler{
							Exec: &corev1.ExecAction{Command: []string{"sh", "-c", scheduleProbeCommand}},
						},
						PeriodSeconds: probePeriodSeconds,
					},
				},
			},
		},
	}
}

func probeAutoPausePolicy() *agentsv1alpha1.AutoPausePolicy {
	return &agentsv1alpha1.AutoPausePolicy{
		Pause: &agentsv1alpha1.PausePolicy{
			WhenProbedIdleState: &agentsv1alpha1.ProbedIdleStateRule{
				Probe:             probeStateName,
				MessageRegex:      "^idle$",
				ThresholdDuration: &metav1.Duration{Duration: probeIdleThreshold},
			},
		},
		Resume: &agentsv1alpha1.ResumePolicy{
			WhenProbedScheduleTime: &agentsv1alpha1.ProbedScheduleTimeRule{
				Probe:      probeScheduleName,
				TimeFormat: agentsv1alpha1.ProbeTimeFormatUnix,
				LeadTime:   &metav1.Duration{Duration: probeResumeLeadTime},
			},
		},
	}
}

// probeResult returns "<status>:<message>" for the probe condition mirrored
// into the sandbox status, or "" while the condition is missing.
func probeResult(ctx context.Context, nn types.NamespacedName, name, probeName string) string {
	sbx := &agentsv1alpha1.Sandbox{}
	if err := k8sClient.Get(ctx, nn, sbx); err != nil {
		return ""
	}
	cond := utils.GetSandboxCondition(&sbx.Status, agentsv1alpha1.ProbeConditionType(probeName))
	if cond == nil {
		return ""
	}
	return string(cond.Status) + ":" + cond.Message
}

// podProbeMarkerCRDInstalled reports whether the cluster serves the kruise
// PodProbeMarker CRD. Suites that run without installing OpenKruise have no
// such CRD and no way to deliver the probes these specs exercise.
func podProbeMarkerCRDInstalled(ctx context.Context) bool {
	return k8sClient.List(ctx, &kruiseappsv1alpha1.PodProbeMarkerList{}, client.Limit(1)) == nil
}

// getPodOrFail returns the sandbox pod, which has the same name as the sandbox.
func getPodOrFail(ctx context.Context, nn types.NamespacedName) *corev1.Pod {
	pod := &corev1.Pod{}
	ExpectWithOffset(1, k8sClient.Get(ctx, nn, pod)).To(Succeed())
	return pod
}

// execInPod runs a shell command inside the sandbox pod through kubectl exec.
// The probes are file-based, so the test drives their results by writing the
// files the probe commands read.
func execInPod(namespace, podName, command string) {
	cmd := exec.Command("kubectl", "exec", "-n", namespace, podName, "-c", probeContainerName, "--", "sh", "-c", command)
	output, err := cmd.CombinedOutput()
	ExpectWithOffset(1, err).NotTo(HaveOccurred(), "kubectl exec failed: %s", string(output))
}

// pickNodeForVirtualKubelet returns a Ready node to relabel as virtual-kubelet.
// A worker (a node without the control-plane role label) is preferred, but a
// control-plane node is accepted as well: the pod template tolerates its taint,
// so single-node clusters work too.
func pickNodeForVirtualKubelet(ctx context.Context) *corev1.Node {
	nodeList := &corev1.NodeList{}
	ExpectWithOffset(1, k8sClient.List(ctx, nodeList)).To(Succeed())

	var worker, controlPlane *corev1.Node
	for i := range nodeList.Items {
		node := &nodeList.Items[i]
		if _, labeled := node.Labels[virtualNodeLabelKey]; labeled {
			continue
		}
		if !isNodeReady(node) {
			continue
		}
		if _, isControlPlane := node.Labels["node-role.kubernetes.io/control-plane"]; isControlPlane {
			if controlPlane == nil {
				controlPlane = node
			}
			continue
		}
		if worker == nil {
			worker = node
		}
	}

	candidate := worker
	if candidate == nil {
		candidate = controlPlane
	}
	ExpectWithOffset(1, candidate).NotTo(BeNil(), "no Ready node found to relabel as virtual-kubelet")
	return candidate
}

func isNodeReady(node *corev1.Node) bool {
	for _, cond := range node.Status.Conditions {
		if cond.Type == corev1.NodeReady {
			return cond.Status == corev1.ConditionTrue
		}
	}
	return false
}

// patchNodeLabel sets a node label, or removes it when value is empty.
func patchNodeLabel(ctx context.Context, nodeName, key, value string) {
	original := &corev1.Node{}
	ExpectWithOffset(1, k8sClient.Get(ctx, types.NamespacedName{Name: nodeName}, original)).To(Succeed())
	patched := original.DeepCopy()
	if patched.Labels == nil {
		patched.Labels = map[string]string{}
	}
	if value == "" {
		delete(patched.Labels, key)
	} else {
		patched.Labels[key] = value
	}
	ExpectWithOffset(1, k8sClient.Patch(ctx, patched, client.MergeFrom(original))).To(Succeed())
}
