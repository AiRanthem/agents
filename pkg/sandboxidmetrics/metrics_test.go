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
	"testing"
	"time"

	dto "github.com/prometheus/client_model/go"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"sigs.k8s.io/controller-runtime/pkg/metrics"
)

func TestRecordersRegisterBoundedMetrics(t *testing.T) {
	tests := []struct {
		name           string
		record         func()
		metricName     string
		metricType     dto.MetricType
		expectedLabels map[string]string
	}{
		{name: "resolution", record: func() { RecordResolved("short", "e2b") }, metricName: "sandbox_id_resolved_total", metricType: dto.MetricType_COUNTER, expectedLabels: map[string]string{"format": "short", "surface": "e2b"}},
		{name: "assignment", record: RecordAssigned, metricName: "sandbox_id_assigned_total", metricType: dto.MetricType_COUNTER, expectedLabels: map[string]string{"format": "short"}},
		{name: "assignment error", record: func() { RecordAssignmentError("invalid_uid") }, metricName: "sandbox_id_assignment_errors_total", metricType: dto.MetricType_COUNTER, expectedLabels: map[string]string{"reason": "invalid_uid"}},
		{name: "assignment duration", record: func() { ObserveAssignmentDuration(25 * time.Millisecond) }, metricName: "sandbox_id_assignment_duration_seconds", metricType: dto.MetricType_HISTOGRAM, expectedLabels: map[string]string{}},
		{name: "reserved mutation rejection", record: func() { RecordReservedMutationRejected("manager_post") }, metricName: "sandbox_id_reserved_mutation_rejected_total", metricType: dto.MetricType_COUNTER, expectedLabels: map[string]string{"surface": "manager_post"}},
		{name: "collision", record: func() { RecordCollision("cache") }, metricName: "sandbox_id_collision_total", metricType: dto.MetricType_COUNTER, expectedLabels: map[string]string{"surface": "cache"}},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			tt.record()
			families, err := metrics.Registry.Gather()
			require.NoError(t, err)
			family := findMetricFamily(families, tt.metricName)
			require.NotNil(t, family)
			assert.Equal(t, tt.metricType, family.GetType())
			require.Len(t, family.Metric, 1)
			assert.Equal(t, tt.expectedLabels, metricLabels(family.Metric[0]))
		})
	}
}

func findMetricFamily(families []*dto.MetricFamily, name string) *dto.MetricFamily {
	for _, family := range families {
		if family.GetName() == name {
			return family
		}
	}
	return nil
}

func metricLabels(metric *dto.Metric) map[string]string {
	labels := make(map[string]string, len(metric.Label))
	for _, label := range metric.Label {
		labels[label.GetName()] = label.GetValue()
	}
	return labels
}
