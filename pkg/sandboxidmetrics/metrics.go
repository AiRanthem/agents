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

package sandboxidmetrics

import (
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"sigs.k8s.io/controller-runtime/pkg/metrics"
)

var (
	resolvedTotal = prometheus.NewCounterVec(prometheus.CounterOpts{
		Name: "sandbox_id_resolved_total",
		Help: "Total Sandbox ID resolutions by format and serving surface.",
	}, []string{"format", "surface"})
	assignedTotal = prometheus.NewCounterVec(prometheus.CounterOpts{
		Name: "sandbox_id_assigned_total",
		Help: "Total Sandbox ID assignments by format.",
	}, []string{"format"})
	assignmentErrorsTotal = prometheus.NewCounterVec(prometheus.CounterOpts{
		Name: "sandbox_id_assignment_errors_total",
		Help: "Total Sandbox ID assignment errors by reason.",
	}, []string{"reason"})
	assignmentDuration = prometheus.NewHistogram(prometheus.HistogramOpts{
		Name:    "sandbox_id_assignment_duration_seconds",
		Help:    "Duration of Sandbox ID assignment persistence in seconds.",
		Buckets: prometheus.ExponentialBuckets(0.005, 2, 14),
	})
	reservedMutationRejectedTotal = prometheus.NewCounterVec(prometheus.CounterOpts{
		Name: "sandbox_id_reserved_mutation_rejected_total",
		Help: "Total rejected attempts to mutate reserved Sandbox ID metadata.",
	}, []string{"surface"})
	collisionTotal = prometheus.NewCounterVec(prometheus.CounterOpts{
		Name: "sandbox_id_collision_total",
		Help: "Total Sandbox ID collisions by detection surface.",
	}, []string{"surface"})
)

func init() {
	metrics.Registry.MustRegister(resolvedTotal, assignedTotal, assignmentErrorsTotal, assignmentDuration, reservedMutationRejectedTotal, collisionTotal)
}

// RecordResolved records one Sandbox ID resolution.
func RecordResolved(format, surface string) {
	resolvedTotal.WithLabelValues(format, surface).Inc()
}

// RecordAssigned records one short Sandbox ID assignment.
func RecordAssigned() {
	assignedTotal.WithLabelValues("short").Inc()
}

// RecordAssignmentError records one Sandbox ID assignment error.
func RecordAssignmentError(reason string) {
	assignmentErrorsTotal.WithLabelValues(reason).Inc()
}

// ObserveAssignmentDuration records the duration of Sandbox ID assignment persistence.
func ObserveAssignmentDuration(duration time.Duration) {
	assignmentDuration.Observe(duration.Seconds())
}

// RecordReservedMutationRejected records one rejected reserved-label mutation.
func RecordReservedMutationRejected(surface string) {
	reservedMutationRejectedTotal.WithLabelValues(surface).Inc()
}

// RecordCollision records one ambiguous Sandbox ID collision.
func RecordCollision(surface string) {
	collisionTotal.WithLabelValues(surface).Inc()
}
