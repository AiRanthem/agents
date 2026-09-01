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

package wake

import (
	"context"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	ctrl "sigs.k8s.io/controller-runtime/pkg/client"

	agentsv1alpha1 "github.com/openkruise/agents/api/v1alpha1"
	"github.com/openkruise/agents/pkg/cache/cachetest"
	"github.com/openkruise/agents/pkg/utils/timeout"
)

func TestInitWakerAndGetWaker(t *testing.T) {
	// Reset before test
	defaultWaker.Store(nil)
	t.Cleanup(func() { defaultWaker.Store(nil) })

	// Before init, GetWaker returns nil
	if w := GetWaker(); w != nil {
		t.Error("GetWaker() should return nil before InitWaker is called")
	}

	// InitWaker(nil) clears the waker, so GetWaker keeps returning nil
	InitWaker(nil)
	if w := GetWaker(); w != nil {
		t.Error("GetWaker() should return nil after InitWaker(nil)")
	}
}

func TestWakeEnabled(t *testing.T) {
	tests := []struct {
		name        string
		sandboxName string
		sandboxNS   string
		withRule    bool
		createSbx   bool
		wakerNil    bool
		want        bool
	}{
		{
			name:        "rule present",
			sandboxName: "sbx-wake",
			sandboxNS:   "default",
			withRule:    true,
			createSbx:   true,
			want:        true,
		},
		{
			name:        "rule absent",
			sandboxName: "sbx-no-wake",
			sandboxNS:   "default",
			createSbx:   true,
			want:        false,
		},
		{
			name:        "sandbox not found",
			sandboxName: "sbx-missing",
			sandboxNS:   "default",
			createSbx:   false,
			want:        false,
		},
		{
			name:     "nil waker returns false",
			wakerNil: true,
			want:     false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if tt.wakerNil {
				var nilWaker *Waker
				assert.False(t, nilWaker.WakeEnabled(context.Background(), "default", "sbx"))
				return
			}

			var initObjs []ctrl.Object
			if tt.createSbx {
				sbx := &agentsv1alpha1.Sandbox{
					ObjectMeta: metav1.ObjectMeta{
						Name:      tt.sandboxName,
						Namespace: tt.sandboxNS,
					},
				}
				if tt.withRule {
					sbx.Spec.AutoPausePolicy = &agentsv1alpha1.AutoPausePolicy{
						Resume: &agentsv1alpha1.ResumePolicy{
							OnIngressTraffic: &agentsv1alpha1.IngressTrafficRule{},
						},
					}
				}
				initObjs = append(initObjs, sbx)
			}

			cacheProvider, _, err := cachetest.NewTestCache(t, initObjs...)
			require.NoError(t, err)

			waker := &Waker{cache: cacheProvider}
			got := waker.WakeEnabled(context.Background(), tt.sandboxNS, tt.sandboxName)
			assert.Equal(t, tt.want, got)
		})
	}
}

// newPausedSandbox creates a Sandbox CR in Paused state with Paused condition True.
func newPausedSandbox(name, namespace string, shutdownTime *metav1.Time) *agentsv1alpha1.Sandbox {
	sbx := &agentsv1alpha1.Sandbox{
		ObjectMeta: metav1.ObjectMeta{
			Name:      name,
			Namespace: namespace,
			UID:       types.UID("uid-" + name),
			Labels: map[string]string{
				agentsv1alpha1.LabelSandboxIsClaimed: "true",
			},
		},
		Spec: agentsv1alpha1.SandboxSpec{
			Paused:       true,
			ShutdownTime: shutdownTime,
		},
		Status: agentsv1alpha1.SandboxStatus{
			Phase: agentsv1alpha1.SandboxPaused,
			Conditions: []metav1.Condition{
				{
					Type:   string(agentsv1alpha1.SandboxConditionPaused),
					Status: metav1.ConditionTrue,
				},
			},
			PodInfo: agentsv1alpha1.PodInfo{
				PodIP: "10.0.0.1",
			},
		},
	}
	return sbx
}

func TestWake(t *testing.T) {
	shutdownTime := time.Now().Add(2 * time.Hour)
	pauseTime := time.Now().Add(1 * time.Hour)

	tests := []struct {
		name         string
		sandboxName  string
		sandboxNS    string
		wakeRule     *agentsv1alpha1.IngressTrafficRule
		shutdownTime *metav1.Time
		pauseTime    *metav1.Time
		// wantPauseSeconds, when > 0, asserts the fresh PauseTime written by
		// the wake is now + wantPauseSeconds (i.e. the resume timeout floor
		// has been applied to the effective value).
		wantPauseSeconds int
		// wantNoPauseTime asserts the wake left no PauseTime behind, i.e.
		// auto-pause was not re-armed (and the stale PauseTime was cleared).
		wantNoPauseTime bool
		skipCreate      bool
		simulateResume  bool
		expectError     string
	}{
		{
			name:        "sandbox not found returns error",
			sandboxName: "nonexistent",
			sandboxNS:   "default",
			skipCreate:  true,
			expectError: "not found",
		},
		{
			// The rule carries no PauseTimeout and none is defaulted: the wake
			// must clear the stale PauseTime so the controller does not
			// re-pause immediately.
			name:            "wake without rule pause timeout does not re-arm auto-pause",
			sandboxName:     "sbx-no-rearm",
			sandboxNS:       "default",
			wakeRule:        &agentsv1alpha1.IngressTrafficRule{},
			shutdownTime:    &metav1.Time{Time: shutdownTime},
			pauseTime:       &metav1.Time{Time: pauseTime},
			wantNoPauseTime: true,
			simulateResume:  true,
		},
		{
			// A sandbox without any wake rule behaves the same way: the wake
			// (driven by the registry flag) does not re-arm auto-pause.
			name:            "wake without wake rule does not re-arm auto-pause",
			sandboxName:     "sbx-no-rule",
			sandboxNS:       "default",
			shutdownTime:    &metav1.Time{Time: shutdownTime},
			pauseTime:       &metav1.Time{Time: pauseTime},
			wantNoPauseTime: true,
			simulateResume:  true,
		},
		{
			name:        "wake with rule pause timeout below resume floor is raised to floor",
			sandboxName: "sbx-rule-below-floor",
			sandboxNS:   "default",
			wakeRule: &agentsv1alpha1.IngressTrafficRule{
				// The create API allows wake timeouts as short as 30s; the
				// written PauseTime must not expire mid-resume.
				PauseTimeout: &metav1.Duration{Duration: 30 * time.Second},
			},
			shutdownTime:     &metav1.Time{Time: shutdownTime},
			pauseTime:        &metav1.Time{Time: pauseTime},
			wantPauseSeconds: 300,
			simulateResume:   true,
		},
		{
			name:        "wake with rule pause timeout above resume floor unchanged",
			sandboxName: "sbx-rule-above-floor",
			sandboxNS:   "default",
			wakeRule: &agentsv1alpha1.IngressTrafficRule{
				PauseTimeout: &metav1.Duration{Duration: 600 * time.Second},
			},
			shutdownTime:     &metav1.Time{Time: shutdownTime},
			pauseTime:        &metav1.Time{Time: pauseTime},
			wantPauseSeconds: 600,
			simulateResume:   true,
		},
		{
			name:        "non-positive rule pause timeout does not re-arm auto-pause",
			sandboxName: "sbx-rule-non-positive",
			sandboxNS:   "default",
			wakeRule: &agentsv1alpha1.IngressTrafficRule{
				PauseTimeout: &metav1.Duration{Duration: -5 * time.Second},
			},
			shutdownTime:    &metav1.Time{Time: shutdownTime},
			pauseTime:       &metav1.Time{Time: pauseTime},
			wantNoPauseTime: true,
			simulateResume:  true,
		},
		{
			name:           "wake preserves nil ShutdownTime",
			sandboxName:    "sbx-nil-shutdown",
			sandboxNS:      "default",
			shutdownTime:   nil,
			pauseTime:      nil,
			simulateResume: true,
		},
		{
			// Shutdown-only sandbox (no PauseTime): wake must not inject a
			// PauseTime that would convert it into auto-pause mode.
			name:            "wake shutdown-only sandbox preserves nil PauseTime",
			sandboxName:     "sbx-shutdown-only",
			sandboxNS:       "default",
			shutdownTime:    &metav1.Time{Time: shutdownTime},
			pauseTime:       nil,
			wantNoPauseTime: true,
			simulateResume:  true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if tt.skipCreate {
				// Test with no sandbox in the cluster
				cacheProvider, _, err := cachetest.NewTestCache(t)
				require.NoError(t, err)
				require.NoError(t, cacheProvider.Run(t.Context()))
				t.Cleanup(func() { cacheProvider.Stop(t.Context()) })

				waker := &Waker{cache: cacheProvider}
				ctx, cancel := context.WithTimeout(t.Context(), 5*time.Second)
				defer cancel()
				err = waker.Wake(ctx, tt.sandboxNS, tt.sandboxName)
				require.Error(t, err)
				assert.Contains(t, err.Error(), tt.expectError)
				return
			}

			sbx := newPausedSandbox(tt.sandboxName, tt.sandboxNS, tt.shutdownTime)
			if tt.pauseTime != nil {
				sbx.Spec.PauseTime = tt.pauseTime
			}
			if tt.wakeRule != nil {
				sbx.Spec.AutoPausePolicy = &agentsv1alpha1.AutoPausePolicy{
					Resume: &agentsv1alpha1.ResumePolicy{
						OnIngressTraffic: tt.wakeRule,
					},
				}
			}

			cacheProvider, fc, err := cachetest.NewTestCache(t)
			require.NoError(t, err)
			require.NoError(t, cacheProvider.Run(t.Context()))
			t.Cleanup(func() { cacheProvider.Stop(t.Context()) })

			// Create sandbox with status
			require.NoError(t, fc.Create(t.Context(), sbx))
			require.NoError(t, fc.Status().Update(t.Context(), sbx))
			time.Sleep(10 * time.Millisecond)

			waker := &Waker{cache: cacheProvider}

			if tt.simulateResume {
				mockMgr := cacheProvider.GetMockManager()
				mockMgr.AddWaitReconcileKey(sbx)

				modified := sbx.DeepCopy()
				mergeFrom := ctrl.MergeFrom(sbx)
				time.AfterFunc(20*time.Millisecond, func() {
					modified.Status.Phase = agentsv1alpha1.SandboxRunning
					modified.Status.Conditions = []metav1.Condition{
						{Type: string(agentsv1alpha1.SandboxConditionReady), Status: metav1.ConditionTrue, Reason: "Resume"},
					}
					_ = fc.Status().Patch(t.Context(), modified, mergeFrom)
				})
			}

			ctx, cancel := context.WithTimeout(t.Context(), 5*time.Second)
			defer cancel()

			err = waker.Wake(ctx, tt.sandboxNS, tt.sandboxName)
			if tt.expectError != "" {
				require.Error(t, err)
				assert.Contains(t, err.Error(), tt.expectError)
				return
			}
			require.NoError(t, err)

			// Verify the sandbox was unpaused
			var updated agentsv1alpha1.Sandbox
			require.NoError(t, fc.Get(t.Context(), ctrl.ObjectKey{Namespace: tt.sandboxNS, Name: tt.sandboxName}, &updated))
			assert.False(t, updated.Spec.Paused, "sandbox should be unpaused after wake")

			// Auto-pause wakes overwrite ShutdownTime with the "forever"
			// retention horizon (now + 100 years); other modes leave it
			// untouched.
			if tt.pauseTime != nil && tt.shutdownTime != nil {
				require.NotNil(t, updated.Spec.ShutdownTime, "ShutdownTime should be set for auto-pause wakes")
				wantShutdown := time.Now().Add(timeout.ForeverReservePausedSandboxDuration)
				assert.WithinDuration(t, wantShutdown, updated.Spec.ShutdownTime.Time, 10*time.Second,
					"auto-pause wake must set ShutdownTime to the forever retention horizon")
			} else if tt.shutdownTime != nil {
				require.NotNil(t, updated.Spec.ShutdownTime, "ShutdownTime should be preserved")
				assert.WithinDuration(t, tt.shutdownTime.Time, updated.Spec.ShutdownTime.Time, time.Second)
			}

			// Verify PauseTime is not injected for never-timeout or shutdown-only sandboxes
			if tt.pauseTime == nil {
				assert.Nil(t, updated.Spec.PauseTime, "PauseTime should not be injected for non-auto-pause sandboxes")
			}

			// Without a positive rule PauseTimeout the wake must not leave a
			// PauseTime behind, otherwise the controller would re-pause the
			// sandbox immediately.
			if tt.wantNoPauseTime {
				assert.Nil(t, updated.Spec.PauseTime, "wake without PauseTimeout must clear the stale PauseTime")
			}

			// Verify the fresh PauseTime carries the floored effective timeout
			if tt.wantPauseSeconds > 0 {
				require.NotNil(t, updated.Spec.PauseTime, "PauseTime should be written for auto-pause sandboxes")
				wantPauseTime := time.Now().Add(time.Duration(tt.wantPauseSeconds) * time.Second)
				assert.WithinDuration(t, wantPauseTime, updated.Spec.PauseTime.Time, 10*time.Second,
					"fresh PauseTime must reflect the effective (floored) wake timeout")
			}
		})
	}
}
