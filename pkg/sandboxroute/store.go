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

package sandboxroute

import (
	"sync"
	"time"

	"k8s.io/apimachinery/pkg/types"
)

// DeletionFenceConfirmationDelay is the delay before an authoritative deletion is confirmed.
const DeletionFenceConfirmationDelay = 2 * time.Second

// EventResult identifies the result of a route mutation event.
type EventResult string

const (
	EventResultApplied        EventResult = "applied"
	EventResultIgnored        EventResult = "ignored"
	EventResultInvalid        EventResult = "invalid"
	EventResultRepairRequired EventResult = "repair_required"
)

// RepairResult identifies a targeted repair outcome for structured logs.
type RepairResult string

const (
	RepairResultSuccess         RepairResult = "success"
	RepairResultGetError        RepairResult = "get_error"
	RepairResultProjectionError RepairResult = "projection_error"
	RepairResultStale           RepairResult = "stale"
)

// Reason identifies a fixed explanation for a mutation result.
type Reason string

const (
	ReasonNone                     Reason = ""
	ReasonInvalidRoute             Reason = "invalid_route"
	ReasonStaleResourceVersion     Reason = "stale_resource_version"
	ReasonAbsent                   Reason = "absent"
	ReasonIdentityMismatch         Reason = "identity_mismatch"
	ReasonInvalidObjectKey         Reason = "invalid_object_key"
	ReasonAmbiguousResourceVersion Reason = "ambiguous_resource_version"
	ReasonStaleRepairGeneration    Reason = "stale_repair_generation"
	ReasonAuthoritativePresent     Reason = "authoritative_present"
	ReasonAuthoritativeAbsent      Reason = "authoritative_absent"
)

// RepairRequest identifies one affected ObjectKey generation to read directly.
type RepairRequest struct {
	ObjectKey  types.NamespacedName
	Generation uint64
}

// MutationResult describes the outcome of one Store mutation request.
type MutationResult struct {
	Result         EventResult
	Reason         Reason
	RepairRequests []RepairRequest
}

// AuthoritativeObservation is one scoped direct-reader result for an ObjectKey.
// Present=false represents NotFound, deletion, or component-policy exclusion.
type AuthoritativeObservation struct {
	Present bool
	Route   Route
}

// StoreOptions provides optional runtime dependencies for a Store.
type StoreOptions struct {
	Now                func() time.Time
	DeletionFenceDelay time.Duration
}

type routeRecord struct {
	route      Route
	generation uint64
}

type deletionFence struct {
	resourceVersion    string
	generation         uint64
	createdAt          time.Time
	confirmationQueued bool
	confirmed          bool
}

// Store owns source records, transition fences, and an active ID-to-ObjectKey index.
type Store struct {
	mu                 sync.RWMutex
	now                func() time.Time
	deletionFenceDelay time.Duration

	generation       uint64
	recordByObject   map[types.NamespacedName]routeRecord
	deletionByObject map[types.NamespacedName]deletionFence
	activeKeyByID    map[string]types.NamespacedName
}

// NewStore creates an empty Store with optional runtime dependencies.
func NewStore(options StoreOptions) *Store {
	now := options.Now
	if now == nil {
		now = time.Now
	}
	deletionFenceDelay := options.DeletionFenceDelay
	if deletionFenceDelay <= 0 {
		deletionFenceDelay = DeletionFenceConfirmationDelay
	}
	store := &Store{
		now:                now,
		deletionFenceDelay: deletionFenceDelay,
		recordByObject:     make(map[types.NamespacedName]routeRecord),
		deletionByObject:   make(map[types.NamespacedName]deletionFence),
		activeKeyByID:      make(map[string]types.NamespacedName),
	}
	return store
}
