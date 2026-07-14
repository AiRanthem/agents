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
	"time"

	"github.com/prometheus/client_golang/prometheus"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"sigs.k8s.io/controller-runtime/pkg/metrics"
)

const (
	fallbackReasonRVExpectation = "rv_expectation_unsatisfied"
	fallbackReasonCacheLagging  = "cache_lagging_behind_route"

	postModifierResultSuccess  = "success"
	postModifierResultError    = "error"
	postModifierResultConflict = "conflict"
)

var sandboxFallbackTotal = prometheus.NewCounterVec(
	prometheus.CounterOpts{
		Name:        "sandbox_get_claimed_fallback_total",
		Help:        "Number of GetClaimedSandbox fallbacks to APIReader, broken down by reason.",
		ConstLabels: prometheus.Labels{"source": "e2b"},
	},
	[]string{"namespace", "reason"},
)

var quotaSourceEventDropTotal = prometheus.NewCounterVec(
	prometheus.CounterOpts{
		Name: "sandboxcr_quota_source_event_drop_total",
		Help: "Total number of quota source sandbox events dropped by reason.",
	},
	[]string{"reason"},
)

var postModifierGetTotal = prometheus.NewCounterVec(
	prometheus.CounterOpts{
		Name: "sandbox_post_modifier_get_total",
		Help: "Total final PostModifier direct API-server Get attempts by result.",
	},
	[]string{"result"},
)

var postModifierUpdateTotal = prometheus.NewCounterVec(
	prometheus.CounterOpts{
		Name: "sandbox_post_modifier_update_total",
		Help: "Total final PostModifier Update attempts by result.",
	},
	[]string{"result"},
)

var postModifierConflictRetriesTotal = prometheus.NewCounter(
	prometheus.CounterOpts{
		Name: "sandbox_post_modifier_conflict_retries_total",
		Help: "Total final PostModifier retries requested after Update conflicts.",
	},
)

var postModifierDuration = prometheus.NewHistogram(
	prometheus.HistogramOpts{
		Name:    "sandbox_post_modifier_duration_seconds",
		Help:    "Duration of final PostModifier execution in seconds.",
		Buckets: prometheus.ExponentialBuckets(0.005, 2, 14),
	},
)

func init() {
	metrics.Registry.MustRegister(
		sandboxFallbackTotal,
		quotaSourceEventDropTotal,
		postModifierGetTotal,
		postModifierUpdateTotal,
		postModifierConflictRetriesTotal,
		postModifierDuration,
	)
}

func recordPostModifierGet(err error) {
	result := postModifierResultSuccess
	if err != nil {
		result = postModifierResultError
	}
	postModifierGetTotal.WithLabelValues(result).Inc()
}

func recordPostModifierUpdate(err error) {
	result := postModifierResultSuccess
	if err != nil {
		result = postModifierResultError
		if apierrors.IsConflict(err) {
			result = postModifierResultConflict
		}
	}
	postModifierUpdateTotal.WithLabelValues(result).Inc()
}

func recordPostModifierConflictRetry() {
	postModifierConflictRetriesTotal.Inc()
}

func observePostModifierDuration(duration time.Duration) {
	postModifierDuration.Observe(duration.Seconds())
}
