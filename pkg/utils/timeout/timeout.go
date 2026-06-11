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

package timeout

import (
	"fmt"
	"time"

	agentsv1alpha1 "github.com/openkruise/agents/api/v1alpha1"
)

func GetTimeoutFromSandbox(sbx *agentsv1alpha1.Sandbox) Options {
	opts := Options{}
	if sbx.Spec.ShutdownTime != nil {
		opts.ShutdownTime = NormalizeTime(sbx.Spec.ShutdownTime.Time)
	}
	if sbx.Spec.PauseTime != nil {
		opts.PauseTime = NormalizeTime(sbx.Spec.PauseTime.Time)
	}
	return opts
}

func ParseReservePausedSandboxFor(raw string) (time.Duration, error) {
	if raw == ReservePausedSandboxForDefaultValue {
		return DefaultReservePausedSandboxFor, nil
	}
	if raw == "" || raw == "never" || raw == "forever" {
		return 0, fmt.Errorf("invalid reserve paused sandbox duration %q: use %q for the built-in 100-year retention", raw, ReservePausedSandboxForDefaultValue)
	}
	retention, err := time.ParseDuration(raw)
	if err != nil {
		return 0, fmt.Errorf("invalid reserve paused sandbox duration %q: %w; use %q for the built-in 100-year retention", raw, err, ReservePausedSandboxForDefaultValue)
	}
	if retention <= 0 {
		return 0, fmt.Errorf("reserve paused sandbox duration %q must be positive; use %q for the built-in 100-year retention", raw, ReservePausedSandboxForDefaultValue)
	}
	return retention, nil
}

func ResolveReservePausedSandboxForAnnotation(annotations map[string]string) (time.Duration, bool, error) {
	if annotations == nil {
		return 0, false, nil
	}
	raw, ok := annotations[agentsv1alpha1.AnnotationReservePausedSandboxFor]
	if !ok {
		return 0, false, nil
	}
	retention, err := ParseReservePausedSandboxFor(raw)
	if err != nil {
		return 0, true, err
	}
	return retention, true, nil
}

func PausedShutdownTime(anchor time.Time, pausedRetention time.Duration) time.Time {
	return NormalizeTime(anchor.Add(pausedRetention))
}

func BuildAutoPauseOptions(now time.Time, requestedTimeout, pausedRetention time.Duration) Options {
	pauseTime := NormalizeTime(now.Add(requestedTimeout))
	return Options{
		PauseTime:    pauseTime,
		ShutdownTime: PausedShutdownTime(pauseTime, pausedRetention),
	}
}

// Equal compares timeout options after normalizing time precision.
func Equal(a, b Options) bool {
	return timeEqual(a.ShutdownTime, b.ShutdownTime) && timeEqual(a.PauseTime, b.PauseTime)
}

// ShouldExtendTimeout reports whether requested extends the effective end time.
func ShouldExtendTimeout(current, requested Options) bool {
	currentEndAt := timeoutEndAt(current)
	requestedEndAt := timeoutEndAt(requested)
	if currentEndAt.IsZero() || requestedEndAt.IsZero() {
		return false
	}
	return requestedEndAt.After(currentEndAt)
}

// NormalizeTime converts timeout values to the precision Kubernetes persists and
// E2B exposes: wall-clock time at whole-second precision in UTC. This removes Go's
// monotonic clock reading, drops sub-second differences, and normalizes the
// Location so timeout comparison and retry conflict handling stay stable across
// in-memory values, metav1.Time serialization, and API server round trips.
func NormalizeTime(t time.Time) time.Time {
	if t.IsZero() {
		return time.Time{}
	}
	return t.Round(0).Truncate(time.Second).UTC()
}

func timeoutEndAt(opts Options) time.Time {
	if !opts.PauseTime.IsZero() {
		return opts.PauseTime
	}
	return opts.ShutdownTime
}

func timeEqual(a, b time.Time) bool {
	if a.IsZero() && b.IsZero() {
		return true
	}
	return NormalizeTime(a).Equal(NormalizeTime(b))
}
