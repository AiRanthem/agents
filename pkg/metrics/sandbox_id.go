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

package metrics

import "github.com/prometheus/client_golang/prometheus"

const (
	SandboxIDAssignmentResultSuccess = "success"
	SandboxIDAssignmentResultFailure = "failure"

	// LegacyResolutionSurface* label values for sandbox_id_legacy_resolution_total.

	LegacyResolutionSurfaceE2B     = "e2b"
	LegacyResolutionSurfaceGateway = "gateway"
)

var (
	sandboxIDLegacyResolutionTotal = prometheus.NewCounterVec(prometheus.CounterOpts{
		Name: "sandbox_id_legacy_resolution_total",
		Help: "Total legacy Sandbox ID resolutions by serving surface.",
	}, []string{"surface"})
	sandboxIDAssignmentTotal = prometheus.NewCounterVec(prometheus.CounterOpts{
		Name: "sandbox_id_assignment_total",
		Help: "Total short Sandbox ID assignments by result.",
	}, []string{"result"})
)

// RecordSandboxIDLegacyResolutionE2B records one E2B legacy Sandbox ID resolution.
func RecordSandboxIDLegacyResolutionE2B() {
	sandboxIDLegacyResolutionTotal.WithLabelValues(LegacyResolutionSurfaceE2B).Inc()
}

// RecordSandboxIDLegacyResolutionGateway records one gateway legacy Sandbox ID resolution.
func RecordSandboxIDLegacyResolutionGateway() {
	sandboxIDLegacyResolutionTotal.WithLabelValues(LegacyResolutionSurfaceGateway).Inc()
}

// RecordSandboxIDAssignment records one short Sandbox ID assignment result.
func RecordSandboxIDAssignment(success bool) {
	result := SandboxIDAssignmentResultFailure
	if success {
		result = SandboxIDAssignmentResultSuccess
	}
	sandboxIDAssignmentTotal.WithLabelValues(result).Inc()
}
