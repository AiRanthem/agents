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
	"github.com/prometheus/client_golang/prometheus"
	"sigs.k8s.io/controller-runtime/pkg/metrics"
)

const (
	acquireResultAllowed   = "allowed"
	acquireResultRejected  = "rejected"
	acquireResultFailOpen  = "fail_open"
	acquireResultUnlimited = "unlimited"
	acquireResultError     = "error"

	releaseResultReleased = "released"
	releaseResultNoop     = "noop"
	releaseResultError    = "error"

	backendOperationAcquire       = "acquire"
	backendOperationRelease       = "release"
	backendOperationAddObserved   = "add_observed"
	backendOperationList          = "list"
	backendOperationDeleteSubject = "delete_subject"

	antiDriftSkipReasonKeyStoreError        = "key_store_error"
	antiDriftSkipReasonLiveListError        = "live_list_error"
	antiDriftSkipReasonBackendListError     = "backend_list_error"
	antiDriftSkipReasonEventNotPrimary      = "event_not_primary"
	antiDriftSkipReasonEventRemoveUnsafe    = "event_remove_unsafe"
	antiDriftSkipReasonEventMissingIdentity = "event_missing_identity"
	antiDriftSkipReasonEventProbeError      = "event_probe_error"
	antiDriftSkipReasonEventStillLive       = "event_still_live"
)

var (
	acquireTotal = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Name: "e2b_quota_acquire_total",
			Help: "Total quota acquire decisions.",
		},
		[]string{"result"},
	)
	backendErrorsTotal = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Name: "e2b_quota_backend_errors_total",
			Help: "Total quota backend errors by operation.",
		},
		[]string{"operation"},
	)
	releaseTotal = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Name: "e2b_quota_release_total",
			Help: "Total quota release decisions.",
		},
		[]string{"result"},
	)
	antiDriftSkippedTotal = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Name: "e2b_quota_antidrift_skipped_total",
			Help: "Total quota anti-drift skips by reason.",
		},
		[]string{"reason"},
	)
)

func init() {
	registerCollector(acquireTotal)
	registerCollector(backendErrorsTotal)
	registerCollector(releaseTotal)
	registerCollector(antiDriftSkippedTotal)
}

func registerCollector(collector prometheus.Collector) {
	if err := metrics.Registry.Register(collector); err != nil {
		if _, ok := err.(prometheus.AlreadyRegisteredError); ok {
			return
		}
		panic(err)
	}
}
