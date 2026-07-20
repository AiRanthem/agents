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
	// RouteSurface* label values for sandbox_route_* metrics (aligned with sandboxroute.Surface).

	RouteSurfaceManager = "manager"
	RouteSurfaceGateway = "gateway"

	// RouteRecordShape* label values retained on sandbox_route_records.

	RouteRecordShapeIDOnly    = "id_only"
	RouteRecordShapeCollision = "collision"
)

var (
	sandboxRouteLegacyFallbackTotal = prometheus.NewCounterVec(prometheus.CounterOpts{
		Name: "sandbox_route_legacy_fallback_total",
		Help: "Total successful legacy delete fallbacks that removed an ID-only route.",
	}, []string{"surface"})
	sandboxRouteInvalidTotal = prometheus.NewCounterVec(prometheus.CounterOpts{
		Name: "sandbox_route_invalid_total",
		Help: "Total invalid route mutations by serving surface.",
	}, []string{"surface"})
	sandboxRouteRecords = prometheus.NewGaugeVec(prometheus.GaugeOpts{
		Name: "sandbox_route_records",
		Help: "Current compatibility and collision route records by shape.",
	}, []string{"surface", "shape"})
	sandboxRouteRepairQueueDepth = prometheus.NewGaugeVec(prometheus.GaugeOpts{
		Name: "sandbox_route_repair_queue_depth",
		Help: "Current number of queued targeted route repairs.",
	}, []string{"surface"})
)

// RecordSandboxRouteLegacyFallback records one successful legacy delete fallback.
func RecordSandboxRouteLegacyFallback(gateway bool) {
	sandboxRouteLegacyFallbackTotal.WithLabelValues(sandboxRouteSurface(gateway)).Inc()
}

// RecordSandboxRouteInvalid records one invalid route mutation.
func RecordSandboxRouteInvalid(gateway bool) {
	sandboxRouteInvalidTotal.WithLabelValues(sandboxRouteSurface(gateway)).Inc()
}

// SetSandboxRouteRecords sets the current numbers of retained route records.
func SetSandboxRouteRecords(gateway bool, idOnly, collision int) {
	surface := sandboxRouteSurface(gateway)
	if idOnly >= 0 {
		sandboxRouteRecords.WithLabelValues(surface, RouteRecordShapeIDOnly).Set(float64(idOnly))
	}
	if collision >= 0 {
		sandboxRouteRecords.WithLabelValues(surface, RouteRecordShapeCollision).Set(float64(collision))
	}
}

// SetSandboxRouteRepairQueueDepth sets the current targeted repair queue depth.
func SetSandboxRouteRepairQueueDepth(gateway bool, count int) {
	if count >= 0 {
		sandboxRouteRepairQueueDepth.WithLabelValues(sandboxRouteSurface(gateway)).Set(float64(count))
	}
}

func sandboxRouteSurface(gateway bool) string {
	if gateway {
		return RouteSurfaceGateway
	}
	return RouteSurfaceManager
}
