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
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	"github.com/openkruise/agents/api/v1alpha1"
)

func TestClassifyResumeState(t *testing.T) {
	now := time.Now()
	tests := []struct {
		name      string
		init      func(*v1alpha1.Sandbox)
		wantState resumeState
	}{
		{
			name: "startable paused sandbox",
			init: func(sbx *v1alpha1.Sandbox) {
				sbx.Spec.Paused = true
				sbx.Status.Phase = v1alpha1.SandboxPaused
				sbx.Status.Conditions = []metav1.Condition{
					{Type: string(v1alpha1.SandboxConditionPaused), Status: metav1.ConditionTrue},
				}
			},
			wantState: resumeStateStartable,
		},
		{
			name: "pausing sandbox is blocked",
			init: func(sbx *v1alpha1.Sandbox) {
				sbx.Spec.Paused = true
				sbx.Status.Phase = v1alpha1.SandboxPaused
				sbx.Status.Conditions = []metav1.Condition{
					{Type: string(v1alpha1.SandboxConditionPaused), Status: metav1.ConditionFalse},
				}
			},
			wantState: resumeStateBlocked,
		},
		{
			name: "non stale lock is in progress",
			init: func(sbx *v1alpha1.Sandbox) {
				sbx.Spec.Paused = false
				sbx.Status.Phase = v1alpha1.SandboxRunning
				sbx.Annotations[v1alpha1.AnnotationResumingLock] = "owner-a"
				sbx.Annotations[v1alpha1.AnnotationResumingSince] = now.Format(time.RFC3339Nano)
			},
			wantState: resumeStateInProgress,
		},
		{
			name: "stale lock is stale",
			init: func(sbx *v1alpha1.Sandbox) {
				sbx.Spec.Paused = false
				sbx.Status.Phase = v1alpha1.SandboxRunning
				sbx.Annotations[v1alpha1.AnnotationResumingLock] = "owner-a"
				sbx.Annotations[v1alpha1.AnnotationResumingSince] = now.Add(-10 * time.Minute).Format(time.RFC3339Nano)
			},
			wantState: resumeStateStale,
		},
		{
			name: "completed running ready resumed",
			init: func(sbx *v1alpha1.Sandbox) {
				sbx.Spec.Paused = false
				sbx.Status.Phase = v1alpha1.SandboxRunning
				sbx.Status.Conditions = []metav1.Condition{
					{Type: string(v1alpha1.SandboxConditionReady), Status: metav1.ConditionTrue},
					{Type: string(v1alpha1.SandboxConditionResumed), Status: metav1.ConditionTrue},
				}
			},
			wantState: resumeStateCompleted,
		},
		{
			name: "lock cleared but not completed is blocked",
			init: func(sbx *v1alpha1.Sandbox) {
				sbx.Spec.Paused = false
				sbx.Status.Phase = v1alpha1.SandboxRunning
			},
			wantState: resumeStateBlocked,
		},
		{
			name: "failed sandbox is blocked",
			init: func(sbx *v1alpha1.Sandbox) {
				sbx.Spec.Paused = true
				sbx.Status.Phase = v1alpha1.SandboxFailed
			},
			wantState: resumeStateBlocked,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			sbx := &v1alpha1.Sandbox{
				ObjectMeta: metav1.ObjectMeta{
					Namespace:   "default",
					Name:        "sbx",
					Annotations: map[string]string{},
				},
			}
			tt.init(sbx)
			got := classifyResumeState(sbx, now, 5*time.Minute)
			assert.Equal(t, tt.wantState, got.state)
		})
	}
}
