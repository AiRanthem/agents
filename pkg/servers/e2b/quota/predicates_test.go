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
	"testing"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	agentsv1alpha1 "github.com/openkruise/agents/api/v1alpha1"
	"github.com/openkruise/agents/pkg/servers/e2b/models"

	"github.com/stretchr/testify/assert"
)

func TestScopePredicates(t *testing.T) {
	sbx := func(phase agentsv1alpha1.SandboxPhase, paused, deleting bool) *agentsv1alpha1.Sandbox {
		s := &agentsv1alpha1.Sandbox{}
		s.Status.Phase = phase
		s.Spec.Paused = paused
		if deleting {
			now := metav1.Now()
			s.DeletionTimestamp = &now
		}
		return s
	}

	tests := []struct {
		name        string
		sbx         *agentsv1alpha1.Sandbox
		wantLive    bool
		wantRunning bool
		wantScopes  []models.QuotaScope
	}{
		{
			name:        "running not paused",
			sbx:         sbx(agentsv1alpha1.SandboxRunning, false, false),
			wantLive:    true,
			wantRunning: true,
			wantScopes:  []models.QuotaScope{models.ScopeRunning},
		},
		{
			name:        "running paused",
			sbx:         sbx(agentsv1alpha1.SandboxPaused, true, false),
			wantLive:    true,
			wantRunning: false,
			wantScopes:  []models.QuotaScope{},
		},
		{
			name:        "pending live and running",
			sbx:         sbx(agentsv1alpha1.SandboxPending, false, false),
			wantLive:    true,
			wantRunning: true,
			wantScopes:  []models.QuotaScope{models.ScopeRunning},
		},
		{
			name:        "failed still live",
			sbx:         sbx(agentsv1alpha1.SandboxFailed, false, false),
			wantLive:    true,
			wantRunning: true,
			wantScopes:  []models.QuotaScope{models.ScopeRunning},
		},
		{
			name:        "terminating freed",
			sbx:         sbx(agentsv1alpha1.SandboxTerminating, false, false),
			wantLive:    false,
			wantRunning: false,
			wantScopes:  []models.QuotaScope{},
		},
		{
			name:        "deletion requested freed",
			sbx:         sbx(agentsv1alpha1.SandboxRunning, false, true),
			wantLive:    false,
			wantRunning: false,
			wantScopes:  []models.QuotaScope{},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.wantLive, IsLiveForQuota(tt.sbx))
			assert.Equal(t, tt.wantRunning, InRunningScope(tt.sbx))
			assert.Equal(t, tt.wantScopes, ConditionalScopesOf(tt.sbx))
		})
	}
}

func TestFootprintOf(t *testing.T) {
	sbx := &agentsv1alpha1.Sandbox{
		Spec: agentsv1alpha1.SandboxSpec{
			EmbeddedSandboxTemplate: agentsv1alpha1.EmbeddedSandboxTemplate{
				Template: &corev1.PodTemplateSpec{
					Spec: corev1.PodSpec{
						Containers: []corev1.Container{
							{
								Resources: corev1.ResourceRequirements{
									Requests: corev1.ResourceList{
										corev1.ResourceCPU:    resource.MustParse("500m"),
										corev1.ResourceMemory: resource.MustParse("1Gi"),
									},
									Limits: corev1.ResourceList{
										corev1.ResourceCPU:    resource.MustParse("2000m"),
										corev1.ResourceMemory: resource.MustParse("4Gi"),
									},
								},
							},
						},
					},
				},
			},
		},
	}

	assert.Equal(t, map[models.QuotaDimension]int64{
		models.DimLimitsCPU:    2000,
		models.DimLimitsMemory: 4096,
	}, FootprintOf(sbx))
}
