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

package autopause

import (
	"reflect"
	"testing"

	corev1 "k8s.io/api/core/v1"

	agentsv1alpha1 "github.com/openkruise/agents/api/v1alpha1"
)

func TestPolicyProbeNames(t *testing.T) {
	tests := []struct {
		name   string
		policy *agentsv1alpha1.AutoPausePolicy
		want   []string
	}{
		{name: "nil policy"},
		{name: "no rules", policy: &agentsv1alpha1.AutoPausePolicy{}},
		{
			name: "ingress traffic rule references no probe",
			policy: &agentsv1alpha1.AutoPausePolicy{
				Resume: &agentsv1alpha1.ResumePolicy{OnIngressTraffic: &agentsv1alpha1.IngressTrafficRule{}},
			},
		},
		{
			name: "pause rule",
			policy: &agentsv1alpha1.AutoPausePolicy{
				Pause: &agentsv1alpha1.PausePolicy{WhenProbedIdleState: &agentsv1alpha1.ProbedIdleStateRule{Probe: "idle"}},
			},
			want: []string{"idle"},
		},
		{
			name: "pause and distinct resume rules",
			policy: &agentsv1alpha1.AutoPausePolicy{
				Pause:  &agentsv1alpha1.PausePolicy{WhenProbedIdleState: &agentsv1alpha1.ProbedIdleStateRule{Probe: "idle"}},
				Resume: &agentsv1alpha1.ResumePolicy{WhenProbedScheduleTime: &agentsv1alpha1.ProbedScheduleTimeRule{Probe: "schedule"}},
			},
			want: []string{"idle", "schedule"},
		},
		{
			name: "both rules reference the same probe",
			policy: &agentsv1alpha1.AutoPausePolicy{
				Pause:  &agentsv1alpha1.PausePolicy{WhenProbedIdleState: &agentsv1alpha1.ProbedIdleStateRule{Probe: "active"}},
				Resume: &agentsv1alpha1.ResumePolicy{WhenProbedScheduleTime: &agentsv1alpha1.ProbedScheduleTimeRule{Probe: "active"}},
			},
			want: []string{"active"},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := PolicyProbeNames(tt.policy); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("PolicyProbeNames() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestRequiredProbeNames(t *testing.T) {
	idleAndCron := &agentsv1alpha1.AutoPausePolicy{
		Pause:  &agentsv1alpha1.PausePolicy{WhenProbedIdleState: &agentsv1alpha1.ProbedIdleStateRule{Probe: "Active"}},
		Resume: &agentsv1alpha1.ResumePolicy{WhenProbedScheduleTime: &agentsv1alpha1.ProbedScheduleTimeRule{Probe: "Cron"}},
	}
	tests := []struct {
		name        string
		policy      *agentsv1alpha1.AutoPausePolicy
		claimProbes []agentsv1alpha1.Probe
		want        []string
	}{
		{name: "nil policy", claimProbes: []agentsv1alpha1.Probe{{Name: "Active"}}},
		{
			name:   "no claim probes keeps the policy names",
			policy: idleAndCron,
			want:   []string{"Active", "Cron"},
		},
		{
			name:        "claim-carried names are subtracted",
			policy:      idleAndCron,
			claimProbes: []agentsv1alpha1.Probe{{Name: "Active"}},
			want:        []string{"Cron"},
		},
		{
			name:        "fully carried policy requires nothing",
			policy:      idleAndCron,
			claimProbes: []agentsv1alpha1.Probe{{Name: "Active"}, {Name: "Cron"}},
		},
		{
			name:        "unrelated claim probes change nothing",
			policy:      idleAndCron,
			claimProbes: []agentsv1alpha1.Probe{{Name: "Other"}},
			want:        []string{"Active", "Cron"},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := RequiredProbeNames(tt.policy, tt.claimProbes); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("RequiredProbeNames() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestMergeProbes(t *testing.T) {
	probe := func(name, command string) agentsv1alpha1.Probe {
		return agentsv1alpha1.Probe{
			Name: name,
			Probe: corev1.Probe{
				ProbeHandler: corev1.ProbeHandler{
					Exec: &corev1.ExecAction{Command: []string{command}},
				},
			},
		}
	}
	tests := []struct {
		name  string
		pool  []agentsv1alpha1.Probe
		claim []agentsv1alpha1.Probe
		want  []agentsv1alpha1.Probe
	}{
		{name: "both empty"},
		{
			name: "empty claim returns the pool probes",
			pool: []agentsv1alpha1.Probe{probe("Active", "pool-cmd")},
			want: []agentsv1alpha1.Probe{probe("Active", "pool-cmd")},
		},
		{
			name:  "same-name claim probe replaces the pool version in place",
			pool:  []agentsv1alpha1.Probe{probe("Active", "pool-cmd"), probe("Audit", "audit-cmd")},
			claim: []agentsv1alpha1.Probe{probe("Active", "claim-cmd")},
			want:  []agentsv1alpha1.Probe{probe("Active", "claim-cmd"), probe("Audit", "audit-cmd")},
		},
		{
			name:  "new-name claim probes append in claim order",
			pool:  []agentsv1alpha1.Probe{probe("Active", "pool-cmd")},
			claim: []agentsv1alpha1.Probe{probe("Cron", "cron-cmd"), probe("Audit", "audit-cmd")},
			want:  []agentsv1alpha1.Probe{probe("Active", "pool-cmd"), probe("Cron", "cron-cmd"), probe("Audit", "audit-cmd")},
		},
		{
			name:  "empty pool takes the claim probes as-is",
			claim: []agentsv1alpha1.Probe{probe("Cron", "cron-cmd")},
			want:  []agentsv1alpha1.Probe{probe("Cron", "cron-cmd")},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := MergeProbes(tt.pool, tt.claim)
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("MergeProbes() = %v, want %v", got, tt.want)
			}
			// The result must never alias the inputs: mutating it cannot leak
			// back into the pool or claim specs.
			for i := range got {
				got[i].Name = "mutated"
			}
			for _, src := range [][]agentsv1alpha1.Probe{tt.pool, tt.claim} {
				for i := range src {
					if src[i].Name == "mutated" {
						t.Fatalf("merged result aliases the input probe %v", src[i])
					}
				}
			}
		})
	}
}
