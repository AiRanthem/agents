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
	"errors"
	"testing"
	"time"

	dto "github.com/prometheus/client_model/go"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"sigs.k8s.io/controller-runtime/pkg/metrics"
)

func TestPostModifierMetricsUseBoundedLabels(t *testing.T) {
	conflict := apierrors.NewConflict(schema.GroupResource{Resource: "sandboxes"}, "sandbox-a", errors.New("conflict"))
	tests := []struct {
		name           string
		record         func()
		metricName     string
		expectedLabels map[string]string
	}{
		{
			name:           "Get result",
			record:         func() { recordPostModifierGet(nil) },
			metricName:     "sandbox_post_modifier_get_total",
			expectedLabels: map[string]string{"result": postModifierResultSuccess},
		},
		{
			name:           "Update conflict result",
			record:         func() { recordPostModifierUpdate(conflict) },
			metricName:     "sandbox_post_modifier_update_total",
			expectedLabels: map[string]string{"result": postModifierResultConflict},
		},
		{
			name:       "conflict retry",
			record:     recordPostModifierConflictRetry,
			metricName: "sandbox_post_modifier_conflict_retries_total",
		},
		{
			name:       "duration",
			record:     func() { observePostModifierDuration(25 * time.Millisecond) },
			metricName: "sandbox_post_modifier_duration_seconds",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			tt.record()
			families, err := metrics.Registry.Gather()
			require.NoError(t, err)
			family := postModifierMetricFamily(families, tt.metricName)
			require.NotNil(t, family)
			assert.True(t, containsPostModifierMetricLabels(family.Metric, tt.expectedLabels))
		})
	}
}

func postModifierMetricFamily(families []*dto.MetricFamily, name string) *dto.MetricFamily {
	for _, family := range families {
		if family.GetName() == name {
			return family
		}
	}
	return nil
}

func containsPostModifierMetricLabels(metrics []*dto.Metric, expected map[string]string) bool {
	for _, metric := range metrics {
		if len(metric.Label) != len(expected) {
			continue
		}
		matched := true
		for _, label := range metric.Label {
			if expected[label.GetName()] != label.GetValue() {
				matched = false
				break
			}
		}
		if matched {
			return true
		}
	}
	return false
}
