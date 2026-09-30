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

package core

import (
	"context"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/apimachinery/pkg/types"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	"k8s.io/client-go/tools/record"
	featuregatetesting "k8s.io/component-base/featuregate/testing"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"
	"sigs.k8s.io/controller-runtime/pkg/client/interceptor"

	agentsv1alpha1 "github.com/openkruise/agents/api/v1alpha1"
	"github.com/openkruise/agents/pkg/features"
	"github.com/openkruise/agents/pkg/utils"
	utilfeature "github.com/openkruise/agents/pkg/utils/feature"
	kruiseappsv1alpha1 "github.com/openkruise/kruise-api/apps/v1alpha1"
)

// enableProbeGate turns on AutoPauseControllerGate for tests that exercise the
// probe pipeline; it gates probe injection and condition sync as well as the
// pause/resume decision.
func enableProbeGate(t *testing.T) {
	featuregatetesting.SetFeatureGateDuringTest(t, utilfeature.DefaultFeatureGate, features.AutoPauseControllerGate, true)
}

// enableKruiseGate turns on KruiseIntegrationGate, which is off by default and
// gates all PodProbeMarker API access.
func enableKruiseGate(t *testing.T) {
	featuregatetesting.SetFeatureGateDuringTest(t, utilfeature.DefaultFeatureGate, features.KruiseIntegrationGate, true)
}

func testScheme(t *testing.T) *runtime.Scheme {
	t.Helper()
	s := runtime.NewScheme()
	require.NoError(t, clientgoscheme.AddToScheme(s))
	require.NoError(t, agentsv1alpha1.AddToScheme(s))
	require.NoError(t, kruiseappsv1alpha1.AddToScheme(s))
	return s
}

func virtualNode(name string) *corev1.Node {
	return &corev1.Node{
		ObjectMeta: metav1.ObjectMeta{
			Name:   name,
			Labels: map[string]string{virtualKubeletNodeLabelKey: virtualKubeletNodeLabelValue},
		},
	}
}

func realNode(name string) *corev1.Node {
	return labeledNode(name, nil)
}

func labeledNode(name string, labels map[string]string) *corev1.Node {
	return &corev1.Node{
		ObjectMeta: metav1.ObjectMeta{
			Name:   name,
			Labels: labels,
		},
	}
}

// TestInjectProbe verifies the creation-time rule: the annotation is injected
// unless spec.nodeName or the pod's hard constraints explicitly exclude a
// virtual-kubelet node, so a virtual placement is covered from pod creation.
func TestInjectProbe(t *testing.T) {
	enableProbeGate(t)
	scheme := testScheme(t)

	probeSpec := agentsv1alpha1.SandboxSpec{
		Probes: []agentsv1alpha1.Probe{
			{
				Name: "activity",
				Probe: corev1.Probe{
					ProbeHandler: corev1.ProbeHandler{
						Exec: &corev1.ExecAction{Command: []string{"echo", "test"}},
					},
				},
			},
		},
	}
	expected := buildPodProbeAnnotation(
		&agentsv1alpha1.Sandbox{Spec: probeSpec},
		&corev1.Pod{Spec: corev1.PodSpec{Containers: []corev1.Container{{Name: "main"}}}},
	)
	requiredAffinity := func(terms ...corev1.NodeSelectorTerm) *corev1.Affinity {
		return &corev1.Affinity{NodeAffinity: &corev1.NodeAffinity{
			RequiredDuringSchedulingIgnoredDuringExecution: &corev1.NodeSelector{NodeSelectorTerms: terms},
		}}
	}

	tests := []struct {
		name        string
		box         *agentsv1alpha1.Sandbox
		pod         *corev1.Pod
		nodes       []client.Object
		expectAnnot bool
	}{
		{
			name: "unscheduled pod - annotation injected",
			box:  &agentsv1alpha1.Sandbox{Spec: probeSpec},
			pod: &corev1.Pod{
				ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default"},
				Spec:       corev1.PodSpec{Containers: []corev1.Container{{Name: "main"}}},
			},
			expectAnnot: true,
		},
		{
			name: "pinned to a real node - no annotation",
			box:  &agentsv1alpha1.Sandbox{Spec: probeSpec},
			pod: &corev1.Pod{
				ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default"},
				Spec:       corev1.PodSpec{NodeName: "real-node-1", Containers: []corev1.Container{{Name: "main"}}},
			},
			nodes:       []client.Object{realNode("real-node-1")},
			expectAnnot: false,
		},
		{
			name: "pinned to a virtual node - annotation injected",
			box:  &agentsv1alpha1.Sandbox{Spec: probeSpec},
			pod: &corev1.Pod{
				ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default"},
				Spec:       corev1.PodSpec{NodeName: "vk-node-1", Containers: []corev1.Container{{Name: "main"}}},
			},
			nodes:       []client.Object{virtualNode("vk-node-1")},
			expectAnnot: true,
		},
		{
			name: "node lookup fails - annotation injected",
			box:  &agentsv1alpha1.Sandbox{Spec: probeSpec},
			pod: &corev1.Pod{
				ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default"},
				Spec:       corev1.PodSpec{NodeName: "missing-node", Containers: []corev1.Container{{Name: "main"}}},
			},
			expectAnnot: true,
		},
		{
			name: "node selector explicitly excluding virtual nodes - no annotation",
			box:  &agentsv1alpha1.Sandbox{Spec: probeSpec},
			pod: &corev1.Pod{
				ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default"},
				Spec: corev1.PodSpec{
					NodeSelector: map[string]string{virtualKubeletNodeLabelKey: "normal"},
					Containers:   []corev1.Container{{Name: "main"}},
				},
			},
			expectAnnot: false,
		},
		{
			name: "node selector explicitly allowing virtual nodes - annotation injected",
			box:  &agentsv1alpha1.Sandbox{Spec: probeSpec},
			pod: &corev1.Pod{
				ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default"},
				Spec: corev1.PodSpec{
					NodeSelector: map[string]string{virtualKubeletNodeLabelKey: virtualKubeletNodeLabelValue},
					Containers:   []corev1.Container{{Name: "main"}},
				},
			},
			expectAnnot: true,
		},
		{
			name: "node selector without virtual node constraint - annotation injected",
			box:  &agentsv1alpha1.Sandbox{Spec: probeSpec},
			pod: &corev1.Pod{
				ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default"},
				Spec: corev1.PodSpec{
					NodeSelector: map[string]string{"kubernetes.io/os": "linux"},
					Containers:   []corev1.Container{{Name: "main"}},
				},
			},
			expectAnnot: true,
		},
		{
			name: "required node affinity excluding virtual nodes - no annotation",
			box:  &agentsv1alpha1.Sandbox{Spec: probeSpec},
			pod: &corev1.Pod{
				ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default"},
				Spec: corev1.PodSpec{
					Affinity: &corev1.Affinity{
						NodeAffinity: &corev1.NodeAffinity{
							RequiredDuringSchedulingIgnoredDuringExecution: &corev1.NodeSelector{
								NodeSelectorTerms: []corev1.NodeSelectorTerm{{
									MatchExpressions: []corev1.NodeSelectorRequirement{{
										Key:      virtualKubeletNodeLabelKey,
										Operator: corev1.NodeSelectorOpNotIn,
										Values:   []string{virtualKubeletNodeLabelValue},
									}},
								}},
							},
						},
					},
					Containers: []corev1.Container{{Name: "main"}},
				},
			},
			expectAnnot: false,
		},
		{
			name: "required node affinity allowing virtual nodes - annotation injected",
			box:  &agentsv1alpha1.Sandbox{Spec: probeSpec},
			pod: &corev1.Pod{
				ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default"},
				Spec: corev1.PodSpec{
					Affinity: &corev1.Affinity{
						NodeAffinity: &corev1.NodeAffinity{
							RequiredDuringSchedulingIgnoredDuringExecution: &corev1.NodeSelector{
								NodeSelectorTerms: []corev1.NodeSelectorTerm{{
									MatchExpressions: []corev1.NodeSelectorRequirement{{
										Key:      virtualKubeletNodeLabelKey,
										Operator: corev1.NodeSelectorOpIn,
										Values:   []string{"normal", virtualKubeletNodeLabelValue},
									}},
								}},
							},
						},
					},
					Containers: []corev1.Container{{Name: "main"}},
				},
			},
			expectAnnot: true,
		},
		{
			name: "required node affinity with no virtual value - no annotation",
			box:  &agentsv1alpha1.Sandbox{Spec: probeSpec},
			pod: &corev1.Pod{
				ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default"},
				Spec: corev1.PodSpec{
					Affinity: &corev1.Affinity{NodeAffinity: &corev1.NodeAffinity{RequiredDuringSchedulingIgnoredDuringExecution: &corev1.NodeSelector{NodeSelectorTerms: []corev1.NodeSelectorTerm{{MatchExpressions: []corev1.NodeSelectorRequirement{{
						Key: virtualKubeletNodeLabelKey, Operator: corev1.NodeSelectorOpIn, Values: []string{"normal"},
					}}}}}}},
					Containers: []corev1.Container{{Name: "main"}},
				},
			},
			expectAnnot: false,
		},
		{
			name: "required node affinity with unrelated label - annotation injected",
			box:  &agentsv1alpha1.Sandbox{Spec: probeSpec},
			pod: &corev1.Pod{
				ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default"},
				Spec: corev1.PodSpec{
					Affinity: &corev1.Affinity{NodeAffinity: &corev1.NodeAffinity{RequiredDuringSchedulingIgnoredDuringExecution: &corev1.NodeSelector{NodeSelectorTerms: []corev1.NodeSelectorTerm{{MatchExpressions: []corev1.NodeSelectorRequirement{{
						Key: "kubernetes.io/os", Operator: corev1.NodeSelectorOpIn, Values: []string{"linux"},
					}}}}}}},
					Containers: []corev1.Container{{Name: "main"}},
				},
			},
			expectAnnot: true,
		},
		{
			name: "required node affinity with an unconstrained OR term - annotation injected",
			box:  &agentsv1alpha1.Sandbox{Spec: probeSpec},
			pod: &corev1.Pod{
				ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default"},
				Spec: corev1.PodSpec{
					Affinity: &corev1.Affinity{NodeAffinity: &corev1.NodeAffinity{RequiredDuringSchedulingIgnoredDuringExecution: &corev1.NodeSelector{NodeSelectorTerms: []corev1.NodeSelectorTerm{
						{MatchExpressions: []corev1.NodeSelectorRequirement{{
							Key: virtualKubeletNodeLabelKey, Operator: corev1.NodeSelectorOpNotIn, Values: []string{virtualKubeletNodeLabelValue},
						}}},
						{MatchExpressions: []corev1.NodeSelectorRequirement{{
							Key: "kubernetes.io/os", Operator: corev1.NodeSelectorOpIn, Values: []string{"linux"},
						}}},
					}}}},
					Containers: []corev1.Container{{Name: "main"}},
				},
			},
			expectAnnot: true,
		},
		{
			name: "empty required node affinity - annotation injected",
			box:  &agentsv1alpha1.Sandbox{Spec: probeSpec},
			pod: &corev1.Pod{
				ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default"},
				Spec: corev1.PodSpec{
					Affinity:   &corev1.Affinity{NodeAffinity: &corev1.NodeAffinity{RequiredDuringSchedulingIgnoredDuringExecution: &corev1.NodeSelector{}}},
					Containers: []corev1.Container{{Name: "main"}},
				},
			},
			expectAnnot: true,
		},
		{
			name: "required node affinity requiring type to exist - annotation injected",
			box:  &agentsv1alpha1.Sandbox{Spec: probeSpec},
			pod: &corev1.Pod{
				ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default"},
				Spec: corev1.PodSpec{
					Affinity: requiredAffinity(corev1.NodeSelectorTerm{MatchExpressions: []corev1.NodeSelectorRequirement{{
						Key: virtualKubeletNodeLabelKey, Operator: corev1.NodeSelectorOpExists,
					}}}),
					Containers: []corev1.Container{{Name: "main"}},
				},
			},
			expectAnnot: true,
		},
		{
			name: "required node affinity requiring type absent - no annotation",
			box:  &agentsv1alpha1.Sandbox{Spec: probeSpec},
			pod: &corev1.Pod{
				ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default"},
				Spec: corev1.PodSpec{
					Affinity: requiredAffinity(corev1.NodeSelectorTerm{MatchExpressions: []corev1.NodeSelectorRequirement{{
						Key: virtualKubeletNodeLabelKey, Operator: corev1.NodeSelectorOpDoesNotExist,
					}}}),
					Containers: []corev1.Container{{Name: "main"}},
				},
			},
			expectAnnot: false,
		},
		{
			name: "required node affinity with numeric type comparison - no annotation",
			box:  &agentsv1alpha1.Sandbox{Spec: probeSpec},
			pod: &corev1.Pod{
				ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default"},
				Spec: corev1.PodSpec{
					Affinity: requiredAffinity(corev1.NodeSelectorTerm{MatchExpressions: []corev1.NodeSelectorRequirement{{
						Key: virtualKubeletNodeLabelKey, Operator: corev1.NodeSelectorOpGt, Values: []string{"1"},
					}}}),
					Containers: []corev1.Container{{Name: "main"}},
				},
			},
			expectAnnot: false,
		},
		{
			name: "required node affinity with conflicting type requirements - no annotation",
			box:  &agentsv1alpha1.Sandbox{Spec: probeSpec},
			pod: &corev1.Pod{
				ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default"},
				Spec: corev1.PodSpec{
					Affinity: requiredAffinity(corev1.NodeSelectorTerm{MatchExpressions: []corev1.NodeSelectorRequirement{
						{Key: virtualKubeletNodeLabelKey, Operator: corev1.NodeSelectorOpIn, Values: []string{virtualKubeletNodeLabelValue}},
						{Key: virtualKubeletNodeLabelKey, Operator: corev1.NodeSelectorOpNotIn, Values: []string{virtualKubeletNodeLabelValue}},
					}}),
					Containers: []corev1.Container{{Name: "main"}},
				},
			},
			expectAnnot: false,
		},
		{
			name: "node selector and required affinity excluding virtual nodes - no annotation",
			box:  &agentsv1alpha1.Sandbox{Spec: probeSpec},
			pod: &corev1.Pod{
				ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default"},
				Spec: corev1.PodSpec{
					NodeSelector: map[string]string{virtualKubeletNodeLabelKey: virtualKubeletNodeLabelValue},
					Affinity: requiredAffinity(corev1.NodeSelectorTerm{MatchExpressions: []corev1.NodeSelectorRequirement{{
						Key: virtualKubeletNodeLabelKey, Operator: corev1.NodeSelectorOpNotIn, Values: []string{virtualKubeletNodeLabelValue},
					}}}),
					Containers: []corev1.Container{{Name: "main"}},
				},
			},
			expectAnnot: false,
		},
		{
			name: "invalid required node affinity - annotation injected",
			box:  &agentsv1alpha1.Sandbox{Spec: probeSpec},
			pod: &corev1.Pod{
				ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default"},
				Spec: corev1.PodSpec{
					Affinity: &corev1.Affinity{
						NodeAffinity: &corev1.NodeAffinity{
							RequiredDuringSchedulingIgnoredDuringExecution: &corev1.NodeSelector{
								NodeSelectorTerms: []corev1.NodeSelectorTerm{{
									MatchExpressions: []corev1.NodeSelectorRequirement{{
										Key:      "kubernetes.io/os",
										Operator: corev1.NodeSelectorOpIn,
									}},
								}},
							},
						},
					},
					Containers: []corev1.Container{{Name: "main"}},
				},
			},
			expectAnnot: true,
		},
		{
			name: "preferred node affinity only - annotation injected",
			box:  &agentsv1alpha1.Sandbox{Spec: probeSpec},
			pod: &corev1.Pod{
				ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default"},
				Spec: corev1.PodSpec{
					Affinity: &corev1.Affinity{
						NodeAffinity: &corev1.NodeAffinity{
							PreferredDuringSchedulingIgnoredDuringExecution: []corev1.PreferredSchedulingTerm{{
								Weight: 1,
								Preference: corev1.NodeSelectorTerm{
									MatchExpressions: []corev1.NodeSelectorRequirement{{
										Key:      virtualKubeletNodeLabelKey,
										Operator: corev1.NodeSelectorOpNotIn,
										Values:   []string{virtualKubeletNodeLabelValue},
									}},
								},
							}},
						},
					},
					Containers: []corev1.Container{{Name: "main"}},
				},
			},
			expectAnnot: true,
		},
		{
			name: "stale template annotation - refreshed with the current probes",
			box:  &agentsv1alpha1.Sandbox{Spec: probeSpec},
			pod: &corev1.Pod{
				ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default", Annotations: map[string]string{
					agentsv1alpha1.AnnotationPodProbe: `[{"name":"stale"}]`,
				}},
				Spec: corev1.PodSpec{Containers: []corev1.Container{{Name: "main"}}},
			},
			expectAnnot: true,
		},
		{
			// A serverless platform consumes the annotation as soon as the pod is
			// created and there is no way to take it back, so an unsupported probe
			// must never be written to it; EnsureProbe reports it on ProbeValid.
			name: "invalid probe handler - no annotation",
			box: &agentsv1alpha1.Sandbox{Spec: agentsv1alpha1.SandboxSpec{Probes: []agentsv1alpha1.Probe{{
				Name:  "activity",
				Probe: corev1.Probe{ProbeHandler: corev1.ProbeHandler{HTTPGet: &corev1.HTTPGetAction{Path: "/health"}}},
			}}}},
			pod: &corev1.Pod{
				ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default"},
				Spec:       corev1.PodSpec{Containers: []corev1.Container{{Name: "main"}}},
			},
			expectAnnot: false,
		},
		{
			// The policy is invalid but the probes themselves are executable, so a
			// dangling rule must not cost the pod its probes.
			name: "invalid auto-pause policy - annotation still injected",
			box: &agentsv1alpha1.Sandbox{Spec: agentsv1alpha1.SandboxSpec{
				Probes: probeSpec.Probes,
				AutoPausePolicy: &agentsv1alpha1.AutoPausePolicy{
					Pause: &agentsv1alpha1.PausePolicy{
						WhenProbedIdleState: &agentsv1alpha1.ProbedIdleStateRule{
							Probe:             "undefined-probe",
							MessageRegex:      "^idle$",
							ThresholdDuration: &metav1.Duration{Duration: time.Minute},
						},
					},
				},
			}},
			pod: &corev1.Pod{
				ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default"},
				Spec:       corev1.PodSpec{Containers: []corev1.Container{{Name: "main"}}},
			},
			expectAnnot: true,
		},
		{
			name: "no probes - no annotation",
			box:  &agentsv1alpha1.Sandbox{},
			pod: &corev1.Pod{
				ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default"},
				Spec:       corev1.PodSpec{Containers: []corev1.Container{{Name: "main"}}},
			},
			expectAnnot: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			builder := fake.NewClientBuilder().WithScheme(scheme)
			if len(tt.nodes) > 0 {
				builder = builder.WithObjects(tt.nodes...)
			}
			manager := NewPodProbeManager(builder.Build(), record.NewFakeRecorder(10))

			manager.InjectProbe(context.Background(), tt.box, tt.pod)

			actual, exists := tt.pod.Annotations[agentsv1alpha1.AnnotationPodProbe]
			if !tt.expectAnnot {
				assert.False(t, exists)
				return
			}
			assert.True(t, exists, "annotation should be injected")
			if len(tt.box.Spec.Probes) > 0 {
				assert.Equal(t, expected, actual)
			}
		})
	}
}

func TestInjectPodProbeAnnotationGateDisabled(t *testing.T) {
	manager := &PodProbeManager{}
	box := &agentsv1alpha1.Sandbox{
		Spec: agentsv1alpha1.SandboxSpec{
			Probes: []agentsv1alpha1.Probe{
				{
					Name: "activity",
					Probe: corev1.Probe{
						ProbeHandler: corev1.ProbeHandler{
							Exec: &corev1.ExecAction{Command: []string{"echo", "ok"}},
						},
					},
				},
			},
		},
	}
	pod := &corev1.Pod{Spec: corev1.PodSpec{Containers: []corev1.Container{{Name: "main"}}}}

	// A rollback must leave the pod exactly as it was, not inject probes that
	// nothing will consume.
	featuregatetesting.SetFeatureGateDuringTest(t, utilfeature.DefaultFeatureGate, features.AutoPauseControllerGate, false)
	manager.InjectProbe(context.Background(), box, pod)

	_, exists := pod.Annotations[agentsv1alpha1.AnnotationPodProbe]
	assert.False(t, exists)
}

func TestEnsureProbeGateDisabledDoesNotRequirePodProbeMarker(t *testing.T) {
	featuregatetesting.SetFeatureGateDuringTest(t, utilfeature.DefaultFeatureGate, features.AutoPauseControllerGate, false)
	scheme := runtime.NewScheme()
	require.NoError(t, clientgoscheme.AddToScheme(scheme))

	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default"},
		Spec:       corev1.PodSpec{NodeName: "real-node-1", Containers: []corev1.Container{{Name: "main"}}},
	}
	box := &agentsv1alpha1.Sandbox{Spec: agentsv1alpha1.SandboxSpec{Probes: []agentsv1alpha1.Probe{{
		Name: "activity",
		Probe: corev1.Probe{ProbeHandler: corev1.ProbeHandler{
			Exec: &corev1.ExecAction{Command: []string{"echo", "ok"}},
		}},
	}}}}
	fakeClient := fake.NewClientBuilder().WithScheme(scheme).WithObjects(pod, realNode("real-node-1")).Build()
	manager := NewPodProbeManager(fakeClient, record.NewFakeRecorder(10))

	require.NoError(t, manager.EnsureProbe(context.Background(), box, pod, &agentsv1alpha1.SandboxStatus{}))
}

// With AutoPauseController on but KruiseIntegration off, EnsureProbe performs no
// PodProbeMarker API access: the scheme deliberately lacks the kruise types, so
// any access would fail, yet a real-node reconcile succeeds. The pod is left
// untouched and its probe condition mirrors as Unknown, which fails closed.
func TestEnsureProbe_KruiseGateDisabledDoesNotAccessPodProbeMarker(t *testing.T) {
	enableProbeGate(t)
	scheme := runtime.NewScheme()
	require.NoError(t, clientgoscheme.AddToScheme(scheme))
	require.NoError(t, agentsv1alpha1.AddToScheme(scheme))

	const nodeName = "real-node-1"
	box := &agentsv1alpha1.Sandbox{
		ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default"},
		Spec: agentsv1alpha1.SandboxSpec{Probes: []agentsv1alpha1.Probe{{
			Name: "activity",
			Probe: corev1.Probe{ProbeHandler: corev1.ProbeHandler{
				Exec: &corev1.ExecAction{Command: []string{"echo", "test"}},
			}},
		}}},
	}
	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:        "box",
			Namespace:   "default",
			Annotations: map[string]string{agentsv1alpha1.AnnotationPodProbe: `[{"name":"stale"}]`},
		},
		Spec: corev1.PodSpec{NodeName: nodeName, Containers: []corev1.Container{{Name: "main"}}},
	}

	fakeClient := fake.NewClientBuilder().
		WithScheme(scheme).
		WithObjects(pod, realNode(nodeName)).
		Build()
	manager := NewPodProbeManager(fakeClient, record.NewFakeRecorder(10))

	newStatus := &agentsv1alpha1.SandboxStatus{}
	require.NoError(t, manager.EnsureProbe(context.Background(), box, pod, newStatus))

	updated := &corev1.Pod{}
	require.NoError(t, fakeClient.Get(context.Background(), client.ObjectKeyFromObject(pod), updated))
	assert.Equal(t, `[{"name":"stale"}]`, updated.Annotations[agentsv1alpha1.AnnotationPodProbe],
		"the annotation is inert on a real node, so it must not cost a Patch")

	cond := utils.GetSandboxCondition(newStatus, string(agentsv1alpha1.ProbeConditionType("activity")))
	require.NotNil(t, cond, "probe condition should mirror as pending")
	assert.Equal(t, metav1.ConditionUnknown, cond.Status)
	assert.Equal(t, agentsv1alpha1.ProbeReasonPending, cond.Reason)
}

// TestEnsureProbe_KruiseCRDMissingIsReported covers the gate being on while the
// cluster has no PodProbeMarker CRD: the reconcile must keep failing, and say why
// in a Warning event, rather than silently skip real-node probe delivery.
func TestEnsureProbe_KruiseCRDMissingIsReported(t *testing.T) {
	enableProbeGate(t)
	enableKruiseGate(t)
	scheme := testScheme(t)

	const nodeName = "real-node-1"
	activityProbe := agentsv1alpha1.Probe{
		Name: "activity",
		Probe: corev1.Probe{ProbeHandler: corev1.ProbeHandler{
			Exec: &corev1.ExecAction{Command: []string{"echo", "test"}},
		}},
	}

	tests := []struct {
		name   string
		probes []agentsv1alpha1.Probe
	}{
		{
			name:   "marker sync reports the missing CRD",
			probes: []agentsv1alpha1.Probe{activityProbe},
		},
		{
			name:   "marker deletion reports the missing CRD",
			probes: nil,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			box := &agentsv1alpha1.Sandbox{
				ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default"},
				Spec:       agentsv1alpha1.SandboxSpec{Probes: tt.probes},
			}
			pod := &corev1.Pod{
				ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default"},
				Spec:       corev1.PodSpec{NodeName: nodeName, Containers: []corev1.Container{{Name: "main"}}},
			}
			noMatch := &meta.NoKindMatchError{
				GroupKind: schema.GroupKind{Group: "apps.kruise.io", Kind: "PodProbeMarker"},
			}
			fakeClient := fake.NewClientBuilder().
				WithScheme(scheme).
				WithObjects(pod, realNode(nodeName)).
				WithInterceptorFuncs(interceptor.Funcs{
					Get: func(ctx context.Context, c client.WithWatch, key client.ObjectKey, obj client.Object, opts ...client.GetOption) error {
						if _, ok := obj.(*kruiseappsv1alpha1.PodProbeMarker); ok {
							return noMatch
						}
						return c.Get(ctx, key, obj, opts...)
					},
				}).
				Build()
			recorder := record.NewFakeRecorder(10)
			manager := NewPodProbeManager(fakeClient, recorder)

			err := manager.EnsureProbe(context.Background(), box, pod, &agentsv1alpha1.SandboxStatus{})
			require.Error(t, err, "a missing CRD must not degrade into silent no-delivery")
			assert.True(t, meta.IsNoMatchError(err), "the no-match cause must stay classifiable, got %v", err)

			select {
			case event := <-recorder.Events:
				assert.Contains(t, event, corev1.EventTypeWarning)
				assert.Contains(t, event, "PodProbeMarkerCRDMissing")
				assert.Contains(t, event, "install OpenKruise or disable the KruiseIntegration feature gate")
			default:
				t.Fatal("expected a Warning event reporting the missing PodProbeMarker CRD")
			}
		})
	}
}

// TestEnsureProbe_VirtualNodeNeverRewritesAnnotation covers the serverless
// contract: the platform does not re-read kruise.io/podprobe after creation, so
// EnsureProbe leaves the annotation as InjectProbe wrote it and only logs drift.
func TestEnsureProbe_VirtualNodeNeverRewritesAnnotation(t *testing.T) {
	enableProbeGate(t)
	scheme := testScheme(t)

	const nodeName = "vk-node-1"

	probeSpec := agentsv1alpha1.SandboxSpec{
		Probes: []agentsv1alpha1.Probe{
			{
				Name: "activity",
				Probe: corev1.Probe{
					ProbeHandler: corev1.ProbeHandler{
						Exec: &corev1.ExecAction{Command: []string{"echo", "test"}},
					},
				},
			},
		},
	}

	expectedAnnotation := buildPodProbeAnnotation(
		&agentsv1alpha1.Sandbox{Spec: probeSpec},
		&corev1.Pod{Spec: corev1.PodSpec{Containers: []corev1.Container{{Name: "main"}}}},
	)

	tests := []struct {
		name        string
		spec        agentsv1alpha1.SandboxSpec
		annotations map[string]string
	}{
		{
			name:        "annotation matches the probes - left alone",
			spec:        probeSpec,
			annotations: map[string]string{agentsv1alpha1.AnnotationPodProbe: expectedAnnotation},
		},
		{
			name:        "annotation outdated - left alone",
			spec:        probeSpec,
			annotations: map[string]string{agentsv1alpha1.AnnotationPodProbe: `[{"name":"old"}]`},
		},
		{
			name:        "annotation missing - not added",
			spec:        probeSpec,
			annotations: nil,
		},
		{
			name:        "probes removed - annotation left alone",
			spec:        agentsv1alpha1.SandboxSpec{},
			annotations: map[string]string{agentsv1alpha1.AnnotationPodProbe: expectedAnnotation},
		},
		{
			name:        "no probes and no annotation - no-op",
			spec:        agentsv1alpha1.SandboxSpec{},
			annotations: nil,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			box := &agentsv1alpha1.Sandbox{
				ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default"},
				Spec:       tt.spec,
			}
			pod := &corev1.Pod{
				ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default", Annotations: tt.annotations},
				Spec:       corev1.PodSpec{NodeName: nodeName, Containers: []corev1.Container{{Name: "main"}}},
			}
			fakeClient := fake.NewClientBuilder().
				WithScheme(scheme).
				WithObjects(pod, virtualNode(nodeName)).
				Build()
			manager := NewPodProbeManager(fakeClient, record.NewFakeRecorder(10))

			require.NoError(t, manager.EnsureProbe(context.Background(), box, pod, &agentsv1alpha1.SandboxStatus{}))

			updated := &corev1.Pod{}
			require.NoError(t, fakeClient.Get(context.Background(), client.ObjectKeyFromObject(pod), updated))
			assert.Equal(t, tt.annotations, updated.Annotations,
				"the annotation is the platform's creation-time input and must not be rewritten")
		})
	}
}

// TestEnsureProbe_UnscheduledPodDoesNothing verifies that EnsureProbe is a no-op
// when the Pod has not been scheduled yet, because the node type is unknown.
func TestEnsureProbe_UnscheduledPodDoesNothing(t *testing.T) {
	enableProbeGate(t)
	enableKruiseGate(t)
	scheme := testScheme(t)

	box := &agentsv1alpha1.Sandbox{
		ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default"},
		Spec: agentsv1alpha1.SandboxSpec{
			Probes: []agentsv1alpha1.Probe{
				{
					Name: "activity",
					Probe: corev1.Probe{
						ProbeHandler: corev1.ProbeHandler{
							Exec: &corev1.ExecAction{Command: []string{"echo", "test"}},
						},
					},
				},
			},
		},
	}
	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default"},
		Spec:       corev1.PodSpec{Containers: []corev1.Container{{Name: "main"}}},
	}

	fakeClient := fake.NewClientBuilder().WithScheme(scheme).WithObjects(pod).Build()
	manager := NewPodProbeManager(fakeClient, record.NewFakeRecorder(10))

	require.NoError(t, manager.EnsureProbe(context.Background(), box, pod, &agentsv1alpha1.SandboxStatus{}))

	updated := &corev1.Pod{}
	require.NoError(t, fakeClient.Get(context.Background(), client.ObjectKeyFromObject(pod), updated))
	_, exists := updated.Annotations[agentsv1alpha1.AnnotationPodProbe]
	assert.False(t, exists, "unscheduled pod should not be patched")

	ppm := &kruiseappsv1alpha1.PodProbeMarker{}
	err := fakeClient.Get(context.Background(), client.ObjectKey{Name: "box", Namespace: "default"}, ppm)
	require.True(t, errors.IsNotFound(err), "unscheduled pod should not create PodProbeMarker")
}

// TestEnsureProbeMarker_RealNode verifies that on non-virtual nodes,
// EnsureProbe creates a PodProbeMarker CRD instead of using annotations.
func TestEnsureProbeMarker_RealNode(t *testing.T) {
	enableProbeGate(t)
	enableKruiseGate(t)
	scheme := testScheme(t)

	const nodeName = "real-node-1"
	probes := []agentsv1alpha1.Probe{
		{
			Name: "activity",
			Probe: corev1.Probe{
				ProbeHandler: corev1.ProbeHandler{
					Exec: &corev1.ExecAction{Command: []string{"echo", "test"}},
				},
			},
		},
	}

	const sandboxUID = "0f4c2d63-9c37-4f6b-b3a1-2a8e5d94c7b6"
	box := &agentsv1alpha1.Sandbox{
		ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default", UID: types.UID(sandboxUID)},
		Spec:       agentsv1alpha1.SandboxSpec{Probes: probes},
	}
	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "box",
			Namespace: "default",
			Labels:    map[string]string{agentsv1alpha1.LabelSandboxUID: sandboxUID},
		},
		Spec: corev1.PodSpec{NodeName: nodeName, Containers: []corev1.Container{{Name: "main"}}},
	}

	fakeClient := fake.NewClientBuilder().
		WithScheme(scheme).
		WithObjects(pod, realNode(nodeName)).
		Build()
	manager := NewPodProbeManager(fakeClient, record.NewFakeRecorder(10))

	require.NoError(t, manager.EnsureProbe(context.Background(), box, pod, &agentsv1alpha1.SandboxStatus{}))

	ppm := &kruiseappsv1alpha1.PodProbeMarker{}
	require.NoError(t, fakeClient.Get(context.Background(), client.ObjectKey{Name: "box", Namespace: "default"}, ppm))
	assert.Len(t, ppm.Spec.Probes, 1)
	assert.Equal(t, "activity", ppm.Spec.Probes[0].Name)
	assert.Equal(t, "main", ppm.Spec.Probes[0].ContainerName)
	assert.Equal(t, agentsv1alpha1.ProbeConditionType("activity"), ppm.Spec.Probes[0].PodConditionType)

	require.NotNil(t, ppm.Spec.Selector)
	assert.Equal(t, sandboxUID, ppm.Spec.Selector.MatchLabels[agentsv1alpha1.LabelSandboxUID])
	assert.NotContains(t, ppm.Spec.Selector.MatchLabels, agentsv1alpha1.LabelSandboxName,
		"UID-labeled pod must not require the name label: selector requirements are ANDed")

	require.Len(t, ppm.OwnerReferences, 1)
	assert.Equal(t, "Pod", ppm.OwnerReferences[0].Kind)
	assert.Equal(t, pod.Name, ppm.OwnerReferences[0].Name)

	// EnsureProbe writes nothing to the pod: a real node is served by the marker.
	updated := &corev1.Pod{}
	require.NoError(t, fakeClient.Get(context.Background(), client.ObjectKeyFromObject(pod), updated))
	_, exists := updated.Annotations[agentsv1alpha1.AnnotationPodProbe]
	assert.False(t, exists, "non-virtual node should not use annotation")
}

// TestEnsureProbeMarker_RealNode_MarkerLifecycle covers the marker write paths
// beyond creation: a stale spec is rewritten, a matching one is left untouched,
// removing spec.probes deletes the marker, invalid probes write nothing, a stale
// cache miss converges through the AlreadyExists tolerance, and a recreated pod
// re-points the marker's owner.
func TestEnsureProbeMarker_RealNode_MarkerLifecycle(t *testing.T) {
	enableProbeGate(t)
	enableKruiseGate(t)
	scheme := testScheme(t)
	ctx := context.Background()

	const nodeName = "real-node-1"
	activityProbe := agentsv1alpha1.Probe{
		Name: "activity",
		Probe: corev1.Probe{
			ProbeHandler: corev1.ProbeHandler{
				Exec: &corev1.ExecAction{Command: []string{"echo", "test"}},
			},
		},
	}

	tests := []struct {
		name           string
		probes         []agentsv1alpha1.Probe
		existing       func(box *agentsv1alpha1.Sandbox, pod *corev1.Pod) *kruiseappsv1alpha1.PodProbeMarker
		podAnnotations map[string]string
		wantProbeNames []string
		// wantUntouched asserts the matching marker was not rewritten at all.
		wantUntouched bool
		// podUID sets the UID of the pod handed to EnsureProbe, standing in
		// for a recreated pod with a fresh UID.
		podUID string
		// wantOwnerUID asserts the marker's owner UID after the sync.
		wantOwnerUID string
		// missCacheOnce simulates a stale informer cache: EnsureProbe's marker
		// Get returns NotFound for a marker that exists, so Create hits
		// AlreadyExists and the reconcile must converge through the re-Get.
		missCacheOnce bool
	}{
		{
			name:   "existing marker with a stale spec - rewritten",
			probes: []agentsv1alpha1.Probe{activityProbe},
			existing: func(box *agentsv1alpha1.Sandbox, pod *corev1.Pod) *kruiseappsv1alpha1.PodProbeMarker {
				marker := buildPodProbeMarker(box, pod)
				marker.Spec.Probes = []kruiseappsv1alpha1.PodContainerProbe{
					{Name: "stale", ContainerName: "main", PodConditionType: "agents.kruise.io/stale"},
				}
				return marker
			},
			wantProbeNames: []string{"activity"},
		},
		{
			name:   "existing marker with extra probes - rewritten",
			probes: []agentsv1alpha1.Probe{activityProbe},
			existing: func(box *agentsv1alpha1.Sandbox, pod *corev1.Pod) *kruiseappsv1alpha1.PodProbeMarker {
				marker := buildPodProbeMarker(box, pod)
				marker.Spec.Probes = []kruiseappsv1alpha1.PodContainerProbe{
					{Name: "stale-1", ContainerName: "main", PodConditionType: "agents.kruise.io/stale-1"},
					{Name: "stale-2", ContainerName: "main", PodConditionType: "agents.kruise.io/stale-2"},
				}
				return marker
			},
			wantProbeNames: []string{"activity"},
		},
		{
			name:   "existing marker already matching - left untouched",
			probes: []agentsv1alpha1.Probe{activityProbe},
			existing: func(box *agentsv1alpha1.Sandbox, pod *corev1.Pod) *kruiseappsv1alpha1.PodProbeMarker {
				return buildPodProbeMarker(box, pod)
			},
			wantProbeNames: []string{"activity"},
			wantUntouched:  true,
		},
		{
			name:   "cache misses an existing marker - converged via AlreadyExists",
			probes: []agentsv1alpha1.Probe{activityProbe},
			existing: func(box *agentsv1alpha1.Sandbox, pod *corev1.Pod) *kruiseappsv1alpha1.PodProbeMarker {
				return buildPodProbeMarker(box, pod)
			},
			wantProbeNames: []string{"activity"},
			missCacheOnce:  true,
			wantUntouched:  true,
		},
		{
			name:   "pod recreated with a new UID - owner re-pointed",
			probes: []agentsv1alpha1.Probe{activityProbe},
			podUID: "new-pod-uid",
			existing: func(box *agentsv1alpha1.Sandbox, pod *corev1.Pod) *kruiseappsv1alpha1.PodProbeMarker {
				marker := buildPodProbeMarker(box, pod)
				marker.OwnerReferences[0].UID = "old-pod-uid"
				return marker
			},
			wantProbeNames: []string{"activity"},
			wantOwnerUID:   "new-pod-uid",
		},
		{
			name:           "unrelated pod annotations - left untouched",
			probes:         []agentsv1alpha1.Probe{activityProbe},
			podAnnotations: map[string]string{"agents.kruise.io/other": "x"},
			wantProbeNames: []string{"activity"},
		},
		{
			// The annotation InjectProbe wrote before the placement was known is
			// inert on a real node — only the serverless platform reads it, while
			// kruise-daemon runs the marker — so stripping it would cost a Patch
			// per pod and change nothing.
			name:           "creation-time podprobe annotation on a real node - left in place",
			probes:         []agentsv1alpha1.Probe{activityProbe},
			podAnnotations: map[string]string{agentsv1alpha1.AnnotationPodProbe: `[{"name":"stale"}]`},
			wantProbeNames: []string{"activity"},
		},
		{
			name:   "probes removed - marker deleted",
			probes: nil,
			existing: func(box *agentsv1alpha1.Sandbox, pod *corev1.Pod) *kruiseappsv1alpha1.PodProbeMarker {
				return buildPodProbeMarker(box, pod)
			},
			wantProbeNames: nil,
		},
		{
			name:           "probes removed and no marker - no error",
			probes:         nil,
			wantProbeNames: nil,
		},
		{
			name: "invalid probes - nothing written",
			probes: []agentsv1alpha1.Probe{{
				Name:  "activity",
				Probe: corev1.Probe{ProbeHandler: corev1.ProbeHandler{HTTPGet: &corev1.HTTPGetAction{Path: "/health"}}},
			}},
			wantProbeNames: nil,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			box := &agentsv1alpha1.Sandbox{
				ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default"},
				Spec:       agentsv1alpha1.SandboxSpec{Probes: tt.probes},
			}
			pod := &corev1.Pod{
				ObjectMeta: metav1.ObjectMeta{
					Name:        "box",
					Namespace:   "default",
					UID:         types.UID(tt.podUID),
					Annotations: tt.podAnnotations,
				},
				Spec: corev1.PodSpec{NodeName: nodeName, Containers: []corev1.Container{{Name: "main"}}},
			}
			objs := []client.Object{pod, realNode(nodeName)}
			if tt.existing != nil {
				objs = append(objs, tt.existing(box, pod))
			}
			builder := fake.NewClientBuilder().WithScheme(scheme).WithObjects(objs...)
			if tt.missCacheOnce {
				// Marker Get #1 is this test's seed read below; #2 is
				// EnsureProbe's cache read, which must miss so Create returns
				// AlreadyExists; #3 is the post-AlreadyExists re-Get.
				markerGets := 0
				builder = builder.WithInterceptorFuncs(interceptor.Funcs{
					Get: func(ctx context.Context, c client.WithWatch, key client.ObjectKey, obj client.Object, opts ...client.GetOption) error {
						if _, ok := obj.(*kruiseappsv1alpha1.PodProbeMarker); ok {
							markerGets++
							if markerGets == 2 {
								return errors.NewNotFound(schema.GroupResource{Group: "apps.kruise.io", Resource: "podprobemarkers"}, key.Name)
							}
						}
						return c.Get(ctx, key, obj, opts...)
					},
				})
			}
			fakeClient := builder.Build()
			rvBefore := ""
			if tt.existing != nil {
				existing := &kruiseappsv1alpha1.PodProbeMarker{}
				require.NoError(t, fakeClient.Get(ctx, client.ObjectKey{Name: "box", Namespace: "default"}, existing))
				rvBefore = existing.ResourceVersion
			}
			manager := NewPodProbeManager(fakeClient, record.NewFakeRecorder(10))

			require.NoError(t, manager.EnsureProbe(ctx, box, pod, &agentsv1alpha1.SandboxStatus{}))

			updatedPod := &corev1.Pod{}
			require.NoError(t, fakeClient.Get(ctx, client.ObjectKeyFromObject(pod), updatedPod))
			assert.Equal(t, tt.podAnnotations, updatedPod.Annotations,
				"the real-node path delivers probes through the marker and must not rewrite the pod")

			marker := &kruiseappsv1alpha1.PodProbeMarker{}
			err := fakeClient.Get(ctx, client.ObjectKey{Name: "box", Namespace: "default"}, marker)
			if tt.wantProbeNames == nil {
				assert.True(t, errors.IsNotFound(err), "marker should be absent")
				return
			}
			require.NoError(t, err)
			names := make([]string, 0, len(marker.Spec.Probes))
			for _, probe := range marker.Spec.Probes {
				names = append(names, probe.Name)
			}
			assert.Equal(t, tt.wantProbeNames, names)
			if tt.wantOwnerUID != "" {
				require.Len(t, marker.OwnerReferences, 1)
				assert.Equal(t, tt.wantOwnerUID, string(marker.OwnerReferences[0].UID))
			}
			if tt.wantUntouched {
				assert.Equal(t, rvBefore, marker.ResourceVersion, "matching marker should not be rewritten")
			}
		})
	}
}

// A policy left behind after spec.probes is removed is invalid, but the probes
// are not: EnsureProbe must still run so the stale probe condition is cleared
// instead of frozen with a timestamp that never moves again. The annotation
// stays — the platform consumed it at creation and would not re-read a patch.
func TestEnsureProbe_DanglingPolicyClearsStaleState(t *testing.T) {
	enableProbeGate(t)
	scheme := testScheme(t)

	const nodeName = "vk-node-1"
	condType := agentsv1alpha1.ProbeConditionType("activity")
	box := &agentsv1alpha1.Sandbox{
		ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default"},
		Spec: agentsv1alpha1.SandboxSpec{
			// spec.probes is gone; the policy still references the probe it defined.
			AutoPausePolicy: &agentsv1alpha1.AutoPausePolicy{
				Pause: &agentsv1alpha1.PausePolicy{
					WhenProbedIdleState: &agentsv1alpha1.ProbedIdleStateRule{
						Probe:             "activity",
						MessageRegex:      "^idle$",
						ThresholdDuration: &metav1.Duration{Duration: time.Minute},
					},
				},
			},
		},
	}
	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default", Annotations: map[string]string{
			agentsv1alpha1.AnnotationPodProbe: `[{"name":"activity"}]`,
		}},
		Spec: corev1.PodSpec{NodeName: nodeName, Containers: []corev1.Container{{Name: "main"}}},
	}
	newStatus := &agentsv1alpha1.SandboxStatus{
		Conditions: []metav1.Condition{{
			Type:               condType,
			Status:             metav1.ConditionTrue,
			Reason:             agentsv1alpha1.ProbeReasonSucceeded,
			Message:            "idle",
			LastTransitionTime: metav1.NewTime(time.Now().Add(-time.Hour)),
		}},
	}

	fakeClient := fake.NewClientBuilder().WithScheme(scheme).WithObjects(pod, virtualNode(nodeName)).Build()
	manager := NewPodProbeManager(fakeClient, record.NewFakeRecorder(10))
	require.NoError(t, manager.EnsureProbe(context.Background(), box, pod, newStatus))

	updated := &corev1.Pod{}
	require.NoError(t, fakeClient.Get(context.Background(), client.ObjectKeyFromObject(pod), updated))
	assert.Equal(t, `[{"name":"activity"}]`, updated.Annotations[agentsv1alpha1.AnnotationPodProbe],
		"the annotation is the platform's creation-time input and is never rewritten")

	assert.Nil(t, utils.GetSandboxCondition(newStatus, condType), "stale probe condition should be removed")

	cond := utils.GetSandboxCondition(newStatus, string(agentsv1alpha1.SandboxConditionProbeValid))
	require.NotNil(t, cond)
	assert.Equal(t, metav1.ConditionFalse, cond.Status, "the dangling policy is still reported as invalid")
}

// TestEnsureProbe_UnclaimedPoolSandboxHoldsResults verifies the warm-pool
// contract: while a pool Sandbox is unclaimed its probe results are cleared and
// the Pod keeps being probed, but the results must not be mirrored into the
// status yet, or a claim would inherit warm-up history and pause immediately.
func TestEnsureProbe_UnclaimedPoolSandboxHoldsResults(t *testing.T) {
	enableProbeGate(t)
	scheme := testScheme(t)

	const nodeName = "vk-node-1"
	condType := agentsv1alpha1.ProbeConditionType("activity")
	nextPause := metav1.NewTime(time.Now().Add(time.Minute))
	nextResume := metav1.NewTime(time.Now().Add(2 * time.Minute))
	box := &agentsv1alpha1.Sandbox{
		ObjectMeta: metav1.ObjectMeta{
			Name: "box", Namespace: "default",
			Labels: map[string]string{agentsv1alpha1.LabelSandboxIsClaimed: agentsv1alpha1.False},
		},
		Spec: agentsv1alpha1.SandboxSpec{
			Probes: []agentsv1alpha1.Probe{
				{
					Name: "activity",
					Probe: corev1.Probe{
						ProbeHandler: corev1.ProbeHandler{
							Exec: &corev1.ExecAction{Command: []string{"echo", "test"}},
						},
					},
				},
			},
		},
	}
	// InjectProbe wrote the annotation when this pool pod was created, and the
	// platform keeps running those probes while the sandbox warms.
	warmAnnotation := buildPodProbeAnnotation(box,
		&corev1.Pod{Spec: corev1.PodSpec{Containers: []corev1.Container{{Name: "main"}}}})
	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name: "box", Namespace: "default",
			Annotations: map[string]string{agentsv1alpha1.AnnotationPodProbe: warmAnnotation},
		},
		Spec: corev1.PodSpec{NodeName: nodeName, Containers: []corev1.Container{{Name: "main"}}},
		Status: corev1.PodStatus{
			Conditions: []corev1.PodCondition{{
				Type:               corev1.PodConditionType(condType),
				Status:             corev1.ConditionTrue,
				Message:            "idle",
				LastTransitionTime: metav1.Now(),
			}},
		},
	}
	newStatus := &agentsv1alpha1.SandboxStatus{
		Conditions: []metav1.Condition{{
			Type:               condType,
			Status:             metav1.ConditionTrue,
			Reason:             agentsv1alpha1.ProbeReasonSucceeded,
			Message:            "idle",
			LastTransitionTime: metav1.NewTime(time.Now().Add(-time.Hour)),
		}},
		Schedules: []agentsv1alpha1.Schedule{
			{Reason: agentsv1alpha1.ScheduleReasonProbedIdle, NextPauseTime: &nextPause},
			{Reason: agentsv1alpha1.ScheduleReasonProbedSchedule, NextResumeTime: &nextResume},
		},
	}

	fakeClient := fake.NewClientBuilder().WithScheme(scheme).WithObjects(pod, virtualNode(nodeName)).Build()
	manager := NewPodProbeManager(fakeClient, record.NewFakeRecorder(10))
	require.NoError(t, manager.EnsureProbe(context.Background(), box, pod, newStatus))

	assert.Nil(t, utils.GetSandboxCondition(newStatus, condType), "warm-up result should be cleared and not mirrored")
	for i := range newStatus.Schedules {
		assert.Nil(t, newStatus.Schedules[i].NextPauseTime)
		assert.Nil(t, newStatus.Schedules[i].NextResumeTime)
	}

	updated := &corev1.Pod{}
	require.NoError(t, fakeClient.Get(context.Background(), client.ObjectKeyFromObject(pod), updated))
	assert.Equal(t, warmAnnotation, updated.Annotations[agentsv1alpha1.AnnotationPodProbe],
		"the pod keeps being probed while warming")
}

// TestValidateProbeConfiguration covers the controller-side reporting path. The
// probe and policy rules themselves are covered by pkg/autopause, so this only
// checks that both are validated and surfaced on the ProbeValid condition.
func TestValidateProbeConfiguration(t *testing.T) {
	validProbes := []agentsv1alpha1.Probe{
		{
			Name: "activity",
			Probe: corev1.Probe{
				ProbeHandler: corev1.ProbeHandler{
					Exec: &corev1.ExecAction{Command: []string{"echo", "test"}},
				},
			},
		},
	}
	idlePolicy := func(probe string) *agentsv1alpha1.AutoPausePolicy {
		return &agentsv1alpha1.AutoPausePolicy{
			Pause: &agentsv1alpha1.PausePolicy{
				WhenProbedIdleState: &agentsv1alpha1.ProbedIdleStateRule{
					Probe:             probe,
					MessageRegex:      "^idle$",
					ThresholdDuration: &metav1.Duration{Duration: time.Minute},
				},
			},
		}
	}

	tests := []struct {
		name string
		spec agentsv1alpha1.SandboxSpec
		// staleProbeValid seeds a ProbeValid=False left over from an earlier spec,
		// to check whether validate still reports on a configuration that is gone.
		staleProbeValid bool
		// expectProbesUsable is validate's return value: whether the probes can
		// still be applied to the Pod. A policy-only error keeps it true.
		expectProbesUsable bool
		expectCondition    metav1.ConditionStatus
		expectMessage      string
	}{
		{
			name:               "no probes and no policy - nothing to validate",
			spec:               agentsv1alpha1.SandboxSpec{},
			expectProbesUsable: true,
		},
		{
			// The user fixed the failure by deleting the configuration, so the
			// verdict on it must go too instead of staying on the status forever.
			name:               "probes and policy removed - stale verdict is dropped",
			spec:               agentsv1alpha1.SandboxSpec{},
			staleProbeValid:    true,
			expectProbesUsable: true,
		},
		{
			name:               "valid probes and policy",
			spec:               agentsv1alpha1.SandboxSpec{Probes: validProbes, AutoPausePolicy: idlePolicy("activity")},
			expectProbesUsable: true,
			expectCondition:    metav1.ConditionTrue,
		},
		{
			name: "ingress traffic resume rule without probes",
			spec: agentsv1alpha1.SandboxSpec{AutoPausePolicy: &agentsv1alpha1.AutoPausePolicy{
				Resume: &agentsv1alpha1.ResumePolicy{
					OnIngressTraffic: &agentsv1alpha1.IngressTrafficRule{},
				},
			}},
			expectProbesUsable: true,
			expectCondition:    metav1.ConditionTrue,
		},
		{
			name: "invalid probe handler",
			spec: agentsv1alpha1.SandboxSpec{Probes: []agentsv1alpha1.Probe{{
				Name:  "activity",
				Probe: corev1.Probe{ProbeHandler: corev1.ProbeHandler{HTTPGet: &corev1.HTTPGetAction{Path: "/health"}}},
			}}},
			expectCondition: metav1.ConditionFalse,
			expectMessage:   "Unsupported value",
		},
		{
			name:               "policy references undefined probe - probes stay usable",
			spec:               agentsv1alpha1.SandboxSpec{Probes: validProbes, AutoPausePolicy: idlePolicy("missing")},
			expectProbesUsable: true,
			expectCondition:    metav1.ConditionFalse,
			expectMessage:      "must reference a probe name defined in spec.probes",
		},
		{
			// Removing spec.probes but leaving the policy behind must not stop the
			// sync that clears the stale Pod annotation and probe conditions.
			name:               "probes removed while policy remains - probes stay usable",
			spec:               agentsv1alpha1.SandboxSpec{AutoPausePolicy: idlePolicy("activity")},
			expectProbesUsable: true,
			expectCondition:    metav1.ConditionFalse,
			expectMessage:      "must reference a probe name defined in spec.probes",
		},
		{
			name:               "policy carries no rule",
			spec:               agentsv1alpha1.SandboxSpec{Probes: validProbes, AutoPausePolicy: &agentsv1alpha1.AutoPausePolicy{}},
			expectProbesUsable: true,
			expectCondition:    metav1.ConditionFalse,
			expectMessage:      "at least one of pause.whenProbedIdleState, resume.whenProbedScheduleTime, or resume.onIngressTraffic is required",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			box := &agentsv1alpha1.Sandbox{
				ObjectMeta: metav1.ObjectMeta{Name: "box", Namespace: "default"},
				Spec:       tt.spec,
			}
			manager := NewPodProbeManager(nil, record.NewFakeRecorder(10))
			newStatus := &agentsv1alpha1.SandboxStatus{}
			if tt.staleProbeValid {
				utils.SetSandboxCondition(newStatus, metav1.Condition{
					Type:               string(agentsv1alpha1.SandboxConditionProbeValid),
					Status:             metav1.ConditionFalse,
					Reason:             agentsv1alpha1.SandboxProbeValidReasonValidationFailed,
					Message:            "probe validation failed",
					LastTransitionTime: metav1.Now(),
				})
			}

			assert.Equal(t, tt.expectProbesUsable, manager.validate(context.Background(), box, newStatus))

			cond := utils.GetSandboxCondition(newStatus, string(agentsv1alpha1.SandboxConditionProbeValid))
			if tt.expectCondition == "" {
				assert.Nil(t, cond)
				return
			}
			require.NotNil(t, cond)
			assert.Equal(t, tt.expectCondition, cond.Status)
			if tt.expectMessage != "" {
				assert.Contains(t, cond.Message, tt.expectMessage)
			}
		})
	}
}

func TestFindPodCondition(t *testing.T) {
	pod := &corev1.Pod{
		Status: corev1.PodStatus{
			Conditions: []corev1.PodCondition{
				{Type: corev1.PodReady, Status: corev1.ConditionTrue},
				{Type: corev1.PodConditionType(agentsv1alpha1.ProbeConditionPrefix + "activity"), Status: corev1.ConditionTrue},
			},
		},
	}

	tests := []struct {
		name     string
		condType string
		wantNil  bool
	}{
		{
			name:     "existing probe condition",
			condType: agentsv1alpha1.ProbeConditionPrefix + "activity",
			wantNil:  false,
		},
		{
			name:     "non-existing condition",
			condType: agentsv1alpha1.ProbeConditionPrefix + "nonexistent",
			wantNil:  true,
		},
		{
			name:     "built-in PodReady condition",
			condType: string(corev1.PodReady),
			wantNil:  false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := findPodCondition(pod, tt.condType)
			if tt.wantNil {
				assert.Nil(t, result)
			} else {
				assert.NotNil(t, result)
				assert.Equal(t, tt.condType, string(result.Type))
			}
		})
	}
}

func TestSyncConditions(t *testing.T) {
	condType := agentsv1alpha1.ProbeConditionPrefix + "activity"
	lastTransition := metav1.NewTime(time.Now().Add(-5 * time.Minute))
	newerTransition := metav1.NewTime(time.Now().Add(-1 * time.Minute))
	claimTime := metav1.NewTime(time.Now().Add(-2 * time.Minute).Truncate(time.Second))

	validProbe := agentsv1alpha1.Probe{
		Name: "activity",
		Probe: corev1.Probe{
			ProbeHandler: corev1.ProbeHandler{
				Exec: &corev1.ExecAction{Command: []string{"echo", "test"}},
			},
		},
	}

	makeBox := func(probes []agentsv1alpha1.Probe) *agentsv1alpha1.Sandbox {
		return &agentsv1alpha1.Sandbox{
			ObjectMeta: metav1.ObjectMeta{Name: "test-sandbox", Namespace: "default"},
			Spec:       agentsv1alpha1.SandboxSpec{Probes: probes},
		}
	}

	makeClaimedBox := func(probes []agentsv1alpha1.Probe, claimTime string) *agentsv1alpha1.Sandbox {
		box := makeBox(probes)
		box.Labels = map[string]string{agentsv1alpha1.LabelSandboxIsClaimed: agentsv1alpha1.True}
		if claimTime != "" {
			box.Annotations = map[string]string{agentsv1alpha1.AnnotationClaimTime: claimTime}
		}
		return box
	}

	podWithConditionAt := func(condType string, status corev1.ConditionStatus, reason, message string, transition metav1.Time) *corev1.Pod {
		return &corev1.Pod{
			ObjectMeta: metav1.ObjectMeta{Name: "test-pod", Namespace: "default"},
			Status: corev1.PodStatus{
				Phase: corev1.PodRunning,
				Conditions: []corev1.PodCondition{
					{
						Type:               corev1.PodConditionType(condType),
						Status:             status,
						Reason:             reason,
						Message:            message,
						LastTransitionTime: transition,
					},
				},
			},
		}
	}

	podWithCondition := func(condType string, status corev1.ConditionStatus, reason, message string) *corev1.Pod {
		return podWithConditionAt(condType, status, reason, message, lastTransition)
	}

	barePod := &corev1.Pod{ObjectMeta: metav1.ObjectMeta{Name: "test-pod", Namespace: "default"}}

	tests := []struct {
		name                  string
		box                   *agentsv1alpha1.Sandbox
		pod                   *corev1.Pod
		existingCond          []metav1.Condition
		wantCondCnt           int
		wantStatus            metav1.ConditionStatus
		wantReason            string
		wantMessage           string
		wantCondAbsent        string
		wantTransition        *metav1.Time
		wantTransitionAfter   *metav1.Time
		wantTransitionNonZero bool
	}{
		{
			name:        "new probe - pod condition not yet available, set Unknown",
			box:         makeBox([]agentsv1alpha1.Probe{validProbe}),
			pod:         barePod,
			wantCondCnt: 1,
			wantStatus:  metav1.ConditionUnknown,
			wantReason:  agentsv1alpha1.ProbeReasonPending,
			wantMessage: "probe result not yet available",
		},
		{
			name:        "normal sync from pod condition",
			box:         makeBox([]agentsv1alpha1.Probe{validProbe}),
			pod:         podWithCondition(condType, corev1.ConditionTrue, agentsv1alpha1.ProbeReasonSucceeded, "inactive"),
			wantCondCnt: 1,
			wantStatus:  metav1.ConditionTrue,
			wantReason:  agentsv1alpha1.ProbeReasonSucceeded,
			wantMessage: "inactive",
		},
		{
			name: "probe removed - condition removed",
			box:  makeBox(nil),
			pod:  podWithCondition(condType, corev1.ConditionTrue, agentsv1alpha1.ProbeReasonSucceeded, "inactive"),
			existingCond: []metav1.Condition{
				{
					Type:               condType,
					Status:             metav1.ConditionTrue,
					Reason:             agentsv1alpha1.ProbeReasonSucceeded,
					Message:            "inactive",
					LastTransitionTime: lastTransition,
				},
			},
			wantCondCnt:    0,
			wantCondAbsent: condType,
		},
		{
			name: "skip when condition unchanged",
			box:  makeBox([]agentsv1alpha1.Probe{validProbe}),
			pod:  podWithCondition(condType, corev1.ConditionTrue, agentsv1alpha1.ProbeReasonSucceeded, "inactive"),
			existingCond: []metav1.Condition{
				{
					Type:               condType,
					Status:             metav1.ConditionTrue,
					Reason:             agentsv1alpha1.ProbeReasonSucceeded,
					Message:            "inactive",
					LastTransitionTime: lastTransition,
				},
			},
			wantCondCnt: 1,
			wantStatus:  metav1.ConditionTrue,
			wantReason:  agentsv1alpha1.ProbeReasonSucceeded,
			wantMessage: "inactive",
		},
		{
			name: "update existing condition when changed",
			box:  makeBox([]agentsv1alpha1.Probe{validProbe}),
			pod:  podWithCondition(condType, corev1.ConditionTrue, agentsv1alpha1.ProbeReasonSucceeded, "inactive"),
			existingCond: []metav1.Condition{
				{
					Type:               condType,
					Status:             metav1.ConditionFalse,
					Reason:             agentsv1alpha1.ProbeReasonError,
					Message:            "old message",
					LastTransitionTime: lastTransition,
				},
			},
			wantCondCnt: 1,
			wantStatus:  metav1.ConditionTrue,
			wantReason:  agentsv1alpha1.ProbeReasonSucceeded,
			wantMessage: "inactive",
		},
		{
			name: "new probe with existing Unknown - not overwritten",
			box:  makeBox([]agentsv1alpha1.Probe{validProbe}),
			pod:  barePod,
			existingCond: []metav1.Condition{
				{
					Type:               condType,
					Status:             metav1.ConditionUnknown,
					Reason:             agentsv1alpha1.ProbeReasonPending,
					Message:            "probe result not yet available",
					LastTransitionTime: lastTransition,
				},
			},
			wantCondCnt: 1,
			wantStatus:  metav1.ConditionUnknown,
			wantReason:  agentsv1alpha1.ProbeReasonPending,
			wantMessage: "probe result not yet available",
		},
		{
			name:           "empty pod reason on healthy probe - defaults to Succeeded",
			box:            makeBox([]agentsv1alpha1.Probe{validProbe}),
			pod:            podWithCondition(condType, corev1.ConditionTrue, "", "inactive"),
			wantCondCnt:    1,
			wantStatus:     metav1.ConditionTrue,
			wantReason:     agentsv1alpha1.ProbeReasonSucceeded,
			wantMessage:    "inactive",
			wantTransition: &lastTransition,
		},
		{
			name:        "empty pod reason on failed probe - defaults to Error",
			box:         makeBox([]agentsv1alpha1.Probe{validProbe}),
			pod:         podWithCondition(condType, corev1.ConditionFalse, "", "probe failed"),
			wantCondCnt: 1,
			wantStatus:  metav1.ConditionFalse,
			wantReason:  agentsv1alpha1.ProbeReasonError,
			wantMessage: "probe failed",
		},
		{
			name:                  "zero pod transition time - filled in",
			box:                   makeBox([]agentsv1alpha1.Probe{validProbe}),
			pod:                   podWithConditionAt(condType, corev1.ConditionTrue, "", "active", metav1.Time{}),
			wantCondCnt:           1,
			wantStatus:            metav1.ConditionTrue,
			wantReason:            agentsv1alpha1.ProbeReasonSucceeded,
			wantMessage:           "active",
			wantTransitionNonZero: true,
		},
		{
			name: "message-only change advances LastTransitionTime",
			box:  makeBox([]agentsv1alpha1.Probe{validProbe}),
			pod:  podWithConditionAt(condType, corev1.ConditionTrue, "", "inactive", newerTransition),
			existingCond: []metav1.Condition{
				{
					Type:               condType,
					Status:             metav1.ConditionTrue,
					Reason:             agentsv1alpha1.ProbeReasonSucceeded,
					Message:            "active",
					LastTransitionTime: lastTransition,
				},
			},
			wantCondCnt:    1,
			wantStatus:     metav1.ConditionTrue,
			wantReason:     agentsv1alpha1.ProbeReasonSucceeded,
			wantMessage:    "inactive",
			wantTransition: &newerTransition,
		},
		{
			// Without a pod timestamp to mirror, the recorded one has to stay put:
			// auto-pause measures its idle threshold from it, and a timestamp that
			// advances every reconcile keeps the threshold permanently in the future.
			name: "zero pod transition time, unchanged result - existing timestamp preserved",
			box:  makeBox([]agentsv1alpha1.Probe{validProbe}),
			pod:  podWithConditionAt(condType, corev1.ConditionTrue, "", "inactive", metav1.Time{}),
			existingCond: []metav1.Condition{
				{
					Type:               condType,
					Status:             metav1.ConditionTrue,
					Reason:             agentsv1alpha1.ProbeReasonSucceeded,
					Message:            "inactive",
					LastTransitionTime: lastTransition,
				},
			},
			wantCondCnt:    1,
			wantStatus:     metav1.ConditionTrue,
			wantReason:     agentsv1alpha1.ProbeReasonSucceeded,
			wantMessage:    "inactive",
			wantTransition: &lastTransition,
		},
		{
			name: "zero pod transition time, changed result - timestamp advances",
			box:  makeBox([]agentsv1alpha1.Probe{validProbe}),
			pod:  podWithConditionAt(condType, corev1.ConditionTrue, "", "inactive", metav1.Time{}),
			existingCond: []metav1.Condition{
				{
					Type:               condType,
					Status:             metav1.ConditionTrue,
					Reason:             agentsv1alpha1.ProbeReasonSucceeded,
					Message:            "active",
					LastTransitionTime: lastTransition,
				},
			},
			wantCondCnt:         1,
			wantStatus:          metav1.ConditionTrue,
			wantReason:          agentsv1alpha1.ProbeReasonSucceeded,
			wantMessage:         "inactive",
			wantTransitionAfter: &newerTransition,
		},
		{
			name:        "unknown pod condition - reason defaults to pending",
			box:         makeBox([]agentsv1alpha1.Probe{validProbe}),
			pod:         podWithCondition(condType, corev1.ConditionUnknown, "", "probe result not yet available"),
			wantCondCnt: 1,
			wantStatus:  metav1.ConditionUnknown,
			wantReason:  agentsv1alpha1.ProbeReasonPending,
			wantMessage: "probe result not yet available",
		},
		{
			// The result predates the claim, so it was accumulated while warming and
			// must not consume the idle threshold from before the claim.
			name:           "claimed pool sandbox - warm-up transition clamped to claim time",
			box:            makeClaimedBox([]agentsv1alpha1.Probe{validProbe}, claimTime.Format(time.RFC3339)),
			pod:            podWithConditionAt(condType, corev1.ConditionTrue, "", "active", lastTransition),
			wantCondCnt:    1,
			wantStatus:     metav1.ConditionTrue,
			wantReason:     agentsv1alpha1.ProbeReasonSucceeded,
			wantMessage:    "active",
			wantTransition: &claimTime,
		},
		{
			name:           "claimed pool sandbox - post-claim transition kept",
			box:            makeClaimedBox([]agentsv1alpha1.Probe{validProbe}, claimTime.Format(time.RFC3339)),
			pod:            podWithConditionAt(condType, corev1.ConditionTrue, "", "active", newerTransition),
			wantCondCnt:    1,
			wantStatus:     metav1.ConditionTrue,
			wantReason:     agentsv1alpha1.ProbeReasonSucceeded,
			wantMessage:    "active",
			wantTransition: &newerTransition,
		},
		{
			name:                  "claimed pool sandbox without claim time - starts at first observation",
			box:                   makeClaimedBox([]agentsv1alpha1.Probe{validProbe}, ""),
			pod:                   podWithConditionAt(condType, corev1.ConditionTrue, "", "active", metav1.Time{}),
			wantCondCnt:           1,
			wantStatus:            metav1.ConditionTrue,
			wantReason:            agentsv1alpha1.ProbeReasonSucceeded,
			wantMessage:           "active",
			wantTransitionNonZero: true,
		},
		{
			name: "claimed pool sandbox without claim time, unchanged result - existing timestamp preserved",
			box:  makeClaimedBox([]agentsv1alpha1.Probe{validProbe}, ""),
			pod:  podWithConditionAt(condType, corev1.ConditionTrue, "", "inactive", metav1.Time{}),
			existingCond: []metav1.Condition{
				{
					Type:               condType,
					Status:             metav1.ConditionTrue,
					Reason:             agentsv1alpha1.ProbeReasonSucceeded,
					Message:            "inactive",
					LastTransitionTime: lastTransition,
				},
			},
			wantCondCnt:    1,
			wantStatus:     metav1.ConditionTrue,
			wantReason:     agentsv1alpha1.ProbeReasonSucceeded,
			wantMessage:    "inactive",
			wantTransition: &lastTransition,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			newStatus := &agentsv1alpha1.SandboxStatus{
				Conditions: tt.existingCond,
			}
			manager := &PodProbeManager{}
			manager.syncConditions(tt.box, tt.pod, newStatus)

			if tt.wantCondCnt == 0 {
				if tt.wantCondAbsent != "" {
					cond := utils.GetSandboxCondition(newStatus, tt.wantCondAbsent)
					assert.Nil(t, cond)
				}
				return
			}
			cond := utils.GetSandboxCondition(newStatus, condType)
			assert.NotNil(t, cond)
			assert.Equal(t, tt.wantStatus, cond.Status)
			assert.Equal(t, tt.wantReason, cond.Reason)
			assert.Equal(t, tt.wantMessage, cond.Message)
			if tt.wantTransition != nil {
				// Normalize to UTC: the clamped transition is built by parsing the
				// claim-time annotation, whose location differs from a time.Now()-
				// derived expectation when the test runs in a UTC timezone.
				assert.Equal(t, tt.wantTransition.UTC(), cond.LastTransitionTime.UTC())
			}
			if tt.wantTransitionAfter != nil {
				assert.True(t, cond.LastTransitionTime.After(tt.wantTransitionAfter.Time),
					"expected LastTransitionTime %v to be after %v", cond.LastTransitionTime, *tt.wantTransitionAfter)
			}
			if tt.wantTransitionNonZero {
				assert.False(t, cond.LastTransitionTime.IsZero())
			}
		})
	}
}
