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

package cache_test

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	agentsv1alpha1 "github.com/openkruise/agents/api/v1alpha1"
	"github.com/openkruise/agents/pkg/cache/cachetest"
	cacheutils "github.com/openkruise/agents/pkg/cache/utils"
)

func makePausedSandbox(name string, paused corev1.ConditionStatus) *agentsv1alpha1.Sandbox {
	return &agentsv1alpha1.Sandbox{
		ObjectMeta: metav1.ObjectMeta{Namespace: "default", Name: name},
		Status: agentsv1alpha1.SandboxStatus{
			Conditions: []metav1.Condition{
				{
					Type:   string(agentsv1alpha1.SandboxConditionPaused),
					Status: metav1.ConditionStatus(paused),
				},
			},
		},
	}
}

func TestNewSandboxPauseTask_BoundAction(t *testing.T) {
	sbx := makePausedSandbox("sbx-pause-1", corev1.ConditionTrue)
	c, _, err := cachetest.NewTestCache(t, sbx)
	require.NoError(t, err)
	task := c.NewSandboxPauseTask(context.Background(), sbx)
	assert.Equal(t, cacheutils.WaitActionPause, task.Action())
	assert.Same(t, sbx, task.Object())
	// Already paused → Wait returns nil immediately.
	assert.NoError(t, task.Wait(100*time.Millisecond))
}

func TestNewSandboxResumeTask_BoundAction(t *testing.T) {
	sbx := &agentsv1alpha1.Sandbox{
		ObjectMeta: metav1.ObjectMeta{Namespace: "default", Name: "sbx-resume-1"},
		Status: agentsv1alpha1.SandboxStatus{
			Phase: agentsv1alpha1.SandboxRunning,
			Conditions: []metav1.Condition{
				{
					Type:   string(agentsv1alpha1.SandboxConditionReady),
					Status: metav1.ConditionTrue,
					Reason: agentsv1alpha1.SandboxReadyReasonPodReady,
				},
				{
					Type:   string(agentsv1alpha1.SandboxConditionResumed),
					Status: metav1.ConditionTrue,
				},
			},
		},
	}
	c, _, err := cachetest.NewTestCache(t, sbx)
	require.NoError(t, err)
	task := c.NewSandboxResumeTask(context.Background(), sbx)
	assert.Equal(t, cacheutils.WaitActionResume, task.Action())
	// Running state → satisfied fast path.
	assert.NoError(t, task.Wait(100*time.Millisecond))
}

func TestNewSandboxResumeCompletionTask(t *testing.T) {
	now := time.Now()
	tests := []struct {
		name        string
		init        func(*agentsv1alpha1.Sandbox)
		waitTimeout time.Duration
		staleTTL    time.Duration
		expectError error
	}{
		{
			name: "completed when lock cleared running ready and resumed",
			init: func(sbx *agentsv1alpha1.Sandbox) {
				sbx.Status.Phase = agentsv1alpha1.SandboxRunning
				sbx.Status.Conditions = []metav1.Condition{
					{Type: string(agentsv1alpha1.SandboxConditionReady), Status: metav1.ConditionTrue},
					{Type: string(agentsv1alpha1.SandboxConditionResumed), Status: metav1.ConditionTrue},
				}
			},
		},
		{
			name: "stale lock returns typed error",
			init: func(sbx *agentsv1alpha1.Sandbox) {
				sbx.Annotations = map[string]string{
					agentsv1alpha1.AnnotationResumingLock:  "owner-a",
					agentsv1alpha1.AnnotationResumingSince: now.Add(-2 * time.Minute).Format(time.RFC3339Nano),
				}
			},
			staleTTL:    time.Minute,
			expectError: cacheutils.ErrSandboxResumeLockStale,
		},
		{
			name: "lock cleared without completed status returns typed owner finished error",
			init: func(sbx *agentsv1alpha1.Sandbox) {
				sbx.Spec.Paused = false
				sbx.Status.Phase = agentsv1alpha1.SandboxRunning
			},
			expectError: cacheutils.ErrSandboxResumeOwnerFinished,
		},
		{
			name: "terminal sandbox returns typed unresumable error",
			init: func(sbx *agentsv1alpha1.Sandbox) {
				sbx.Status.Phase = agentsv1alpha1.SandboxFailed
				sbx.Annotations = map[string]string{
					agentsv1alpha1.AnnotationResumingLock:  "owner-a",
					agentsv1alpha1.AnnotationResumingSince: now.Format(time.RFC3339Nano),
				}
			},
			expectError: cacheutils.ErrSandboxResumeUnresumable,
		},
		{
			name: "periodic timeout returns typed not satisfied error",
			init: func(sbx *agentsv1alpha1.Sandbox) {
				sbx.Status.Phase = agentsv1alpha1.SandboxRunning
				sbx.Annotations = map[string]string{
					agentsv1alpha1.AnnotationResumingLock:  "owner-a",
					agentsv1alpha1.AnnotationResumingSince: now.Format(time.RFC3339Nano),
				}
			},
			waitTimeout: 10 * time.Millisecond,
			staleTTL:    time.Hour,
			expectError: cacheutils.ErrObjectNotSatisfiedDuringDoubleCheck,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			sbx := &agentsv1alpha1.Sandbox{
				ObjectMeta: metav1.ObjectMeta{
					Namespace:   "default",
					Name:        "sbx-resume-completion",
					Annotations: map[string]string{},
				},
				Spec: agentsv1alpha1.SandboxSpec{Paused: true},
				Status: agentsv1alpha1.SandboxStatus{
					Phase: agentsv1alpha1.SandboxPaused,
				},
			}
			if tt.init != nil {
				tt.init(sbx)
			}
			if tt.staleTTL == 0 {
				tt.staleTTL = time.Minute
			}
			if tt.waitTimeout == 0 {
				tt.waitTimeout = 100 * time.Millisecond
			}
			c, _, err := cachetest.NewTestCache(t, sbx)
			require.NoError(t, err)
			task := c.NewSandboxResumeCompletionTask(context.Background(), sbx, tt.staleTTL)
			assert.Equal(t, cacheutils.WaitActionResumeCompletion, task.Action())

			err = task.Wait(tt.waitTimeout)
			if tt.expectError != nil {
				require.Error(t, err)
				assert.True(t, errors.Is(err, tt.expectError), "got %v, want errors.Is(..., %v)", err, tt.expectError)
				return
			}
			assert.NoError(t, err)
		})
	}
}

func TestNewSandboxWaitReadyTask_BoundAction(t *testing.T) {
	sbx := &agentsv1alpha1.Sandbox{
		ObjectMeta: metav1.ObjectMeta{Namespace: "default", Name: "sbx-wait-1", Generation: 1},
		Status: agentsv1alpha1.SandboxStatus{
			ObservedGeneration: 1,
			Phase:              agentsv1alpha1.SandboxRunning,
			PodInfo:            agentsv1alpha1.PodInfo{PodIP: "10.0.0.1"},
			Conditions: []metav1.Condition{
				{
					Type:   string(agentsv1alpha1.SandboxConditionReady),
					Status: metav1.ConditionTrue,
					Reason: agentsv1alpha1.SandboxReadyReasonPodReady,
				},
			},
		},
	}
	c, _, err := cachetest.NewTestCache(t, sbx)
	require.NoError(t, err)
	task := c.NewSandboxWaitReadyTask(context.Background(), sbx)
	assert.Equal(t, cacheutils.WaitActionWaitReady, task.Action())
	// Ready → satisfied fast path.
	assert.NoError(t, task.Wait(100*time.Millisecond))
}

func TestNewSandboxWaitReadyTask_StartContainerFailed_ReturnsError(t *testing.T) {
	sbx := &agentsv1alpha1.Sandbox{
		ObjectMeta: metav1.ObjectMeta{Namespace: "default", Name: "sbx-wait-2", Generation: 1},
		Status: agentsv1alpha1.SandboxStatus{
			ObservedGeneration: 1,
			Conditions: []metav1.Condition{
				{
					Type:    string(agentsv1alpha1.SandboxConditionReady),
					Status:  metav1.ConditionFalse,
					Reason:  agentsv1alpha1.SandboxReadyReasonStartContainerFailed,
					Message: "OCI create failed",
				},
			},
		},
	}
	c, _, err := cachetest.NewTestCache(t, sbx)
	require.NoError(t, err)
	task := c.NewSandboxWaitReadyTask(context.Background(), sbx)
	err = task.Wait(100 * time.Millisecond)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "start container failed")
}

func TestNewCheckpointTask_Succeeded(t *testing.T) {
	cp := &agentsv1alpha1.Checkpoint{
		ObjectMeta: metav1.ObjectMeta{Namespace: "default", Name: "cp-1"},
		Status: agentsv1alpha1.CheckpointStatus{
			Phase:        agentsv1alpha1.CheckpointSucceeded,
			CheckpointId: "ckpt-abc",
		},
	}
	c, _, err := cachetest.NewTestCache(t, cp)
	require.NoError(t, err)
	task := c.NewCheckpointTask(context.Background(), cp)
	assert.Equal(t, cacheutils.WaitActionCheckpoint, task.Action())
	assert.NoError(t, task.Wait(100*time.Millisecond))
}

func TestNewCheckpointTask_Failed_ReturnsError(t *testing.T) {
	cp := &agentsv1alpha1.Checkpoint{
		ObjectMeta: metav1.ObjectMeta{Namespace: "default", Name: "cp-2"},
		Status: agentsv1alpha1.CheckpointStatus{
			Phase:   agentsv1alpha1.CheckpointFailed,
			Message: "disk full",
		},
	}
	c, _, err := cachetest.NewTestCache(t, cp)
	require.NoError(t, err)
	task := c.NewCheckpointTask(context.Background(), cp)
	err = task.Wait(100 * time.Millisecond)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "checkpoint default/cp-2 failed")
	assert.Contains(t, err.Error(), "disk full")
}
