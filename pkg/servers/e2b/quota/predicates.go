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
	agentsv1alpha1 "github.com/openkruise/agents/api/v1alpha1"
	"github.com/openkruise/agents/pkg/sandbox/lifecycle"
	"github.com/openkruise/agents/pkg/servers/e2b/models"
)

const bytesPerMiB = int64(1024 * 1024)

func IsLiveForQuota(sbx *agentsv1alpha1.Sandbox) bool {
	return lifecycle.IsNotTerminating(sbx)
}

// InRunningScope uses Spec.Paused (pause request), matching current production behavior.
// Design §5 pseudocode uses Status.Phase; §15 leaves the exact transition-phase boundary to
// implementation. Do not change this predicate during the refactor.
func InRunningScope(sbx *agentsv1alpha1.Sandbox) bool {
	return lifecycle.IsNotTerminating(sbx) && !sbx.Spec.Paused
}

func ConditionalScopesOf(sbx *agentsv1alpha1.Sandbox) []models.QuotaScope {
	if !InRunningScope(sbx) {
		return []models.QuotaScope{}
	}
	return []models.QuotaScope{models.ScopeRunning}
}

func FootprintOf(sbx *agentsv1alpha1.Sandbox) map[models.QuotaDimension]int64 {
	footprint := map[models.QuotaDimension]int64{
		models.DimLimitsCPU:    0,
		models.DimLimitsMemory: 0,
	}
	if sbx == nil || sbx.Spec.Template == nil {
		return footprint
	}

	for _, container := range sbx.Spec.Template.Spec.Containers {
		footprint[models.DimLimitsCPU] += container.Resources.Limits.Cpu().MilliValue()
		memoryBytes := container.Resources.Limits.Memory().Value()
		if memoryBytes > 0 {
			footprint[models.DimLimitsMemory] += (memoryBytes + bytesPerMiB - 1) / bytesPerMiB
		}
	}
	return footprint
}
