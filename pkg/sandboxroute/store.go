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
	"fmt"
	"sort"
	"sync"
	"time"

	"github.com/openkruise/agents/pkg/sandboxidmetrics"
	"k8s.io/apimachinery/pkg/types"
)

// CompatibilityDrainWindow is the default old-peer retry and drain window.
const CompatibilityDrainWindow = 2 * time.Second

// Reason identifies a fixed explanation for a mutation result.
type Reason string

const (
	ReasonNone                     Reason = ""
	ReasonInvalidRoute             Reason = "invalid_route"
	ReasonStaleResourceVersion     Reason = "stale_resource_version"
	ReasonDominatedByFull          Reason = "dominated_by_full"
	ReasonDeletionFence            Reason = "deletion_fence"
	ReasonRetiredUID               Reason = "retired_uid"
	ReasonIDCollision              Reason = "id_collision"
	ReasonUIDCollision             Reason = "uid_collision"
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
	Now         func() time.Time
	DrainWindow time.Duration
}

// StoreStats contains bounded physical and active-view counts.
type StoreStats struct {
	Full      int
	IDOnly    int
	Retired   int
	Deletion  int
	Collision int
	Active    int
}

type routeRecord struct {
	route        Route
	generation   uint64
	lastObserved time.Time
	quarantined  bool
}

type retiredFence struct {
	uid             types.UID
	id              string
	resourceVersion string
	generation      uint64
	createdAt       time.Time
}

type deletionFence struct {
	key                types.NamespacedName
	uid                types.UID
	id                 string
	resourceVersion    string
	generation         uint64
	createdAt          time.Time
	confirmationQueued bool
	confirmed          bool
}

// Store owns full, compatibility, retired, deletion, collision, and active route state.
type Store struct {
	mu          sync.RWMutex
	surface     Surface
	now         func() time.Time
	drainWindow time.Duration

	generation       uint64
	fullByObject     map[types.NamespacedName]routeRecord
	fullByUID        map[types.UID]map[types.NamespacedName]struct{}
	compatByUID      map[types.UID]routeRecord
	retiredByUID     map[types.UID]retiredFence
	deletionByObject map[types.NamespacedName]deletionFence
	activeByID       map[string]Route
	collisionsByID   map[string]struct{}
}

// NewStore creates an empty Store for one supported component surface.
func NewStore(surface Surface) (*Store, error) {
	return NewStoreWithOptions(surface, StoreOptions{})
}

// NewStoreWithOptions creates an empty Store with optional runtime dependencies.
func NewStoreWithOptions(surface Surface, options StoreOptions) (*Store, error) {
	if surface != SurfaceManager && surface != SurfaceGateway {
		return nil, fmt.Errorf("unsupported route Store surface %q", surface)
	}
	now := options.Now
	if now == nil {
		now = time.Now
	}
	drainWindow := options.DrainWindow
	if drainWindow <= 0 {
		drainWindow = CompatibilityDrainWindow
	}
	store := &Store{
		surface:          surface,
		now:              now,
		drainWindow:      drainWindow,
		fullByObject:     make(map[types.NamespacedName]routeRecord),
		fullByUID:        make(map[types.UID]map[types.NamespacedName]struct{}),
		compatByUID:      make(map[types.UID]routeRecord),
		retiredByUID:     make(map[types.UID]retiredFence),
		deletionByObject: make(map[types.NamespacedName]deletionFence),
		activeByID:       make(map[string]Route),
		collisionsByID:   make(map[string]struct{}),
	}
	store.setRecordMetricsLocked()
	return store, nil
}

// Surface returns the component surface owning this Store.
func (s *Store) Surface() Surface {
	return s.surface
}

// UpsertFull applies an ObjectKey-backed route event.
func (s *Store) UpsertFull(route Route) MutationResult {
	if !hasExpectedShape(route, ShapeFull) {
		return s.recordWithoutMutation(OperationUpsert, ShapeFull, EventResultInvalid, ReasonInvalidRoute)
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	key, _ := route.ObjectKey()
	current, hasCurrent := s.fullByObject[key]
	if hasCurrent {
		comparison := CompareResourceVersions(current.route.ResourceVersion, route.ResourceVersion)
		switch {
		case current.route.UID == route.UID && current.route.ID == route.ID:
			if comparison != ResourceVersionEqual && comparison != ResourceVersionNewer {
				return s.finishLocked(OperationUpsert, ShapeFull, EventResultIgnored, ReasonStaleResourceVersion, nil)
			}
		case current.route.UID == route.UID:
			if comparison != ResourceVersionNewer {
				return s.finishLocked(OperationUpsert, ShapeFull, EventResultIgnored, ReasonStaleResourceVersion, nil)
			}
		default:
			switch comparison {
			case ResourceVersionNewer:
			case ResourceVersionOlder:
				return s.finishLocked(OperationUpsert, ShapeFull, EventResultIgnored, ReasonStaleResourceVersion, nil)
			default:
				current.generation = s.nextGenerationLocked()
				current.quarantined = true
				s.fullByObject[key] = current
				s.recomputeActiveViewLocked()
				request := RepairRequest{ObjectKey: key, Generation: current.generation}
				return s.finishLocked(OperationUpsert, ShapeFull, EventResultRepairRequired, ReasonAmbiguousResourceVersion, []RepairRequest{request})
			}
		}
	}

	deletion, hasDeletion := s.deletionByObject[key]
	if !hasCurrent && hasDeletion {
		comparison := CompareResourceVersions(deletion.resourceVersion, route.ResourceVersion)
		switch comparison {
		case ResourceVersionNewer:
		case ResourceVersionOlder:
			return s.finishLocked(OperationUpsert, ShapeFull, EventResultIgnored, ReasonStaleResourceVersion, nil)
		default:
			deletion.generation = s.nextGenerationLocked()
			deletion.confirmationQueued = true
			s.deletionByObject[key] = deletion
			request := RepairRequest{ObjectKey: key, Generation: deletion.generation}
			return s.finishLocked(OperationUpsert, ShapeFull, EventResultRepairRequired, ReasonAmbiguousResourceVersion, []RepairRequest{request})
		}
	}

	if compatibility, exists := s.compatByUID[route.UID]; exists &&
		!equalOrNewer(compatibility.route.ResourceVersion, route.ResourceVersion) {
		return s.finishLocked(OperationUpsert, ShapeFull, EventResultIgnored, ReasonStaleResourceVersion, nil)
	}

	targetCompatibility := s.compatibilityClaimsLocked(route.ID, route.UID)
	supersedeCompatibility := len(targetCompatibility) > 0 && allStrictlyOlder(targetCompatibility, route.ResourceVersion)
	compatibilityCollision := len(targetCompatibility) > 0 && !supersedeCompatibility
	displacedUID := types.UID("")
	if hasCurrent && current.route.UID != route.UID {
		displacedUID = current.route.UID
	}
	preserveQuarantine := hasCurrent && current.route.UID == route.UID &&
		current.route.ID == route.ID && current.quarantined
	s.installFullLocked(key, route, supersedeCompatibility, preserveQuarantine)
	displacedRequests := s.refreshQuarantinedUIDClaimsLocked(displacedUID)
	uidCollisionRequests := s.quarantineUIDClaimsLocked(route.UID, true)
	s.recomputeActiveViewLocked()
	if len(uidCollisionRequests) > 0 {
		return s.finishLocked(
			OperationUpsert,
			ShapeFull,
			EventResultCollision,
			ReasonUIDCollision,
			deduplicateRepairRequests(append(displacedRequests, uidCollisionRequests...)),
		)
	}
	if compatibilityCollision || s.idCollidedLocked(route.ID) {
		requests := append(displacedRequests, s.repairRequestsForIDLocked(route.ID)...)
		return s.finishLocked(
			OperationUpsert,
			ShapeFull,
			EventResultCollision,
			ReasonIDCollision,
			deduplicateRepairRequests(requests),
		)
	}
	return s.finishLocked(OperationUpsert, ShapeFull, EventResultApplied, ReasonNone, displacedRequests)
}

// UpsertIDOnly applies a compatibility route event without an ObjectKey.
func (s *Store) UpsertIDOnly(route Route) MutationResult {
	if !hasExpectedShape(route, ShapeIDOnly) {
		return s.recordWithoutMutation(OperationUpsert, ShapeIDOnly, EventResultInvalid, ReasonInvalidRoute)
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	if s.idHasDeletionFenceLocked(route.ID) {
		return s.finishLocked(OperationUpsert, ShapeIDOnly, EventResultIgnored, ReasonDeletionFence, nil)
	}
	if _, retired := s.retiredByUID[route.UID]; retired {
		return s.finishLocked(OperationUpsert, ShapeIDOnly, EventResultIgnored, ReasonRetiredUID, nil)
	}
	if s.uidHasFullOwnerLocked(route.UID) || s.idHasFullOwnerLocked(route.ID) {
		return s.finishLocked(OperationUpsert, ShapeIDOnly, EventResultIgnored, ReasonDominatedByFull, nil)
	}
	if current, exists := s.compatByUID[route.UID]; exists {
		if current.route.ID != route.ID {
			return s.finishLocked(OperationUpsert, ShapeIDOnly, EventResultCollision, ReasonUIDCollision, nil)
		}
		if !equalOrNewer(current.route.ResourceVersion, route.ResourceVersion) {
			return s.finishLocked(OperationUpsert, ShapeIDOnly, EventResultIgnored, ReasonStaleResourceVersion, nil)
		}
	}

	s.compatByUID[route.UID] = routeRecord{
		route:        route,
		generation:   s.nextGenerationLocked(),
		lastObserved: s.now(),
	}
	s.recomputeActiveViewLocked()
	if s.idCollidedLocked(route.ID) {
		return s.finishLocked(OperationUpsert, ShapeIDOnly, EventResultCollision, ReasonIDCollision, nil)
	}
	return s.finishLocked(OperationUpsert, ShapeIDOnly, EventResultApplied, ReasonNone, nil)
}

// DeleteAuthoritativeByObjectKey removes the current local ObjectKey incarnation.
// When no full record exists, legacyFallbackID may identify compatibility records only.
func (s *Store) DeleteAuthoritativeByObjectKey(
	key types.NamespacedName,
	legacyFallbackID string,
) MutationResult {
	if key.Namespace == "" || key.Name == "" {
		return s.recordWithoutMutation(OperationDelete, ShapeFull, EventResultInvalid, ReasonInvalidObjectKey)
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	if current, exists := s.fullByObject[key]; exists {
		return s.deleteFullLocked(OperationDelete, key, current, current.route.ResourceVersion)
	}
	if legacyFallbackID == "" {
		return s.finishLocked(OperationDelete, ShapeFull, EventResultIgnored, ReasonAbsent, nil)
	}

	participants := s.compatibilityClaimsLocked(legacyFallbackID, "")
	switch len(participants) {
	case 0:
		return s.finishLocked(OperationDelete, ShapeIDOnly, EventResultIgnored, ReasonAbsent, nil)
	case 1:
		return s.deleteCompatibilityForObjectLocked(
			OperationDelete,
			key,
			participants[0],
			participants[0].route.ResourceVersion,
		)
	default:
		return s.finishLocked(OperationDelete, ShapeIDOnly, EventResultCollision, ReasonIDCollision, nil)
	}
}

// DeleteFullConditionally removes a full identity only when ObjectKey, ID, UID,
// and resource-version fences match. It may remove an exact compatibility
// participant when no full ObjectKey record exists.
func (s *Store) DeleteFullConditionally(route Route) MutationResult {
	if !hasExpectedShape(route, ShapeFull) {
		return s.recordWithoutMutation(OperationDelete, ShapeFull, EventResultInvalid, ReasonInvalidRoute)
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	key, _ := route.ObjectKey()
	if current, exists := s.fullByObject[key]; exists {
		if current.route.ID != route.ID || current.route.UID != route.UID {
			return s.finishLocked(OperationDelete, ShapeFull, EventResultIgnored, ReasonIdentityMismatch, nil)
		}
		if !equalOrNewer(current.route.ResourceVersion, route.ResourceVersion) {
			return s.finishLocked(OperationDelete, ShapeFull, EventResultIgnored, ReasonStaleResourceVersion, nil)
		}
		return s.deleteFullLocked(OperationDelete, key, current, route.ResourceVersion)
	}

	if compatibility, exists := s.compatByUID[route.UID]; exists {
		if compatibility.route.ID != route.ID {
			return s.finishLocked(OperationDelete, ShapeIDOnly, EventResultIgnored, ReasonIdentityMismatch, nil)
		}
		if !equalOrNewer(compatibility.route.ResourceVersion, route.ResourceVersion) {
			return s.finishLocked(OperationDelete, ShapeIDOnly, EventResultIgnored, ReasonStaleResourceVersion, nil)
		}
		return s.deleteCompatibilityForObjectLocked(OperationDelete, key, compatibility, route.ResourceVersion)
	}
	if s.uidHasFullOwnerLocked(route.UID) ||
		s.idHasFullOwnerLocked(route.ID) || s.idHasCompatibilityOwnerLocked(route.ID) {
		return s.finishLocked(OperationDelete, ShapeFull, EventResultIgnored, ReasonIdentityMismatch, nil)
	}
	return s.finishLocked(OperationDelete, ShapeFull, EventResultIgnored, ReasonAbsent, nil)
}

// DeleteIDOnlyConditionally removes only an exact compatibility identity when
// its delete resource version is equal or newer and comparable.
func (s *Store) DeleteIDOnlyConditionally(route Route) MutationResult {
	if !hasExpectedShape(route, ShapeIDOnly) {
		return s.recordWithoutMutation(OperationDelete, ShapeIDOnly, EventResultInvalid, ReasonInvalidRoute)
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	current, exists := s.compatByUID[route.UID]
	if !exists {
		if s.uidHasFullOwnerLocked(route.UID) || s.idHasFullOwnerLocked(route.ID) {
			return s.finishLocked(OperationDelete, ShapeIDOnly, EventResultIgnored, ReasonDominatedByFull, nil)
		}
		if s.idHasCompatibilityOwnerLocked(route.ID) {
			return s.finishLocked(OperationDelete, ShapeIDOnly, EventResultIgnored, ReasonIdentityMismatch, nil)
		}
		return s.finishLocked(OperationDelete, ShapeIDOnly, EventResultIgnored, ReasonAbsent, nil)
	}
	if current.route.ID != route.ID {
		return s.finishLocked(OperationDelete, ShapeIDOnly, EventResultIgnored, ReasonIdentityMismatch, nil)
	}
	if !equalOrNewer(current.route.ResourceVersion, route.ResourceVersion) {
		return s.finishLocked(OperationDelete, ShapeIDOnly, EventResultIgnored, ReasonStaleResourceVersion, nil)
	}

	delete(s.compatByUID, route.UID)
	generation := s.nextGenerationLocked()
	s.retiredByUID[route.UID] = retiredFence{
		uid:             route.UID,
		id:              route.ID,
		resourceVersion: route.ResourceVersion,
		generation:      generation,
		createdAt:       s.now(),
	}
	s.recomputeActiveViewLocked()
	return s.finishLocked(OperationDelete, ShapeIDOnly, EventResultApplied, ReasonNone, nil)
}

// Get returns the unique active route for id.
func (s *Store) Get(id string) (Route, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	route, exists := s.activeByID[id]
	return route, exists
}

// List returns active routes sorted by ID.
func (s *Store) List() []Route {
	s.mu.RLock()
	defer s.mu.RUnlock()
	routes := make([]Route, 0, len(s.activeByID))
	for _, route := range s.activeByID {
		routes = append(routes, route)
	}
	sort.Slice(routes, func(i, j int) bool {
		return routes[i].ID < routes[j].ID
	})
	return routes
}

// Stats returns bounded physical and active-view counts.
func (s *Store) Stats() StoreStats {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.statsLocked()
}

// ApplyAuthoritativeRepair applies a scoped direct-read observation only when
// the affected ObjectKey record or fence still has the requested generation.
func (s *Store) ApplyAuthoritativeRepair(
	request RepairRequest,
	observation AuthoritativeObservation,
) MutationResult {
	if request.ObjectKey.Namespace == "" || request.ObjectKey.Name == "" || request.Generation == 0 {
		return MutationResult{Result: EventResultInvalid, Reason: ReasonInvalidObjectKey}
	}
	if observation.Present {
		if !hasExpectedShape(observation.Route, ShapeFull) {
			return MutationResult{Result: EventResultInvalid, Reason: ReasonInvalidRoute}
		}
		key, _ := observation.Route.ObjectKey()
		if key != request.ObjectKey {
			return MutationResult{Result: EventResultInvalid, Reason: ReasonIdentityMismatch}
		}
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	generation, exists := s.affectedGenerationLocked(request.ObjectKey)
	if !exists || generation != request.Generation {
		return s.finishRepairLocked(EventResultIgnored, ReasonStaleRepairGeneration, nil)
	}
	if !observation.Present {
		return s.applyAuthoritativeAbsenceLocked(request.ObjectKey)
	}
	return s.applyAuthoritativePresenceLocked(request.ObjectKey, observation.Route)
}

// Maintenance expires compatibility-only state and returns deletion-fence
// confirmations that must be observed through the Repairer direct-read callback.
func (s *Store) Maintenance() []RepairRequest {
	s.mu.Lock()
	defer s.mu.Unlock()

	now := s.now()
	changedView, requests := s.expireCompatibilityLocked(now)
	for key, fence := range s.deletionByObject {
		if now.Sub(fence.createdAt) < s.drainWindow {
			continue
		}
		if fence.confirmed {
			delete(s.deletionByObject, key)
			s.pruneRetiredUIDLocked(fence.uid, now)
			continue
		}
		if fence.confirmationQueued {
			continue
		}
		fence.generation = s.nextGenerationLocked()
		fence.confirmationQueued = true
		s.deletionByObject[key] = fence
		requests = append(requests, RepairRequest{ObjectKey: key, Generation: fence.generation})
	}

	for uid, fence := range s.retiredByUID {
		if now.Sub(fence.createdAt) >= s.drainWindow && !s.uidHasDeletionFenceLocked(uid) {
			delete(s.retiredByUID, uid)
		}
	}
	if changedView {
		s.nextGenerationLocked()
		s.recomputeActiveViewLocked()
	}
	requests = deduplicateRepairRequests(requests)
	s.setRecordMetricsLocked()
	return requests
}

func (s *Store) applyAuthoritativePresenceLocked(
	key types.NamespacedName,
	route Route,
) MutationResult {
	displacedUID := types.UID("")
	if current, exists := s.fullByObject[key]; exists && current.route.UID != route.UID {
		displacedUID = current.route.UID
	}
	_, alreadyOwned := s.fullByUID[route.UID][key]
	s.installFullLocked(key, route, true, false)
	displacedRequests := s.refreshQuarantinedUIDClaimsLocked(displacedUID)
	uidCollisionRequests := s.quarantineUIDClaimsLocked(route.UID, !alreadyOwned)
	s.recomputeActiveViewLocked()
	if len(uidCollisionRequests) > 0 {
		if alreadyOwned {
			uidCollisionRequests = nil
		}
		requests := deduplicateRepairRequests(append(displacedRequests, uidCollisionRequests...))
		return s.finishRepairLocked(EventResultCollision, ReasonUIDCollision, requests)
	}
	if s.idCollidedLocked(route.ID) {
		return s.finishRepairLocked(EventResultCollision, ReasonIDCollision, displacedRequests)
	}
	return s.finishRepairLocked(EventResultApplied, ReasonAuthoritativePresent, displacedRequests)
}

func (s *Store) applyAuthoritativeAbsenceLocked(key types.NamespacedName) MutationResult {
	now := s.now()
	if current, exists := s.fullByObject[key]; exists {
		delete(s.fullByObject, key)
		s.removeFullUIDOwnerLocked(current.route.UID, key)
		generation := s.nextGenerationLocked()
		s.installDeletionFencesLocked(key, current.route, current.route.ResourceVersion, generation, true)
		requests := s.refreshQuarantinedUIDClaimsLocked(current.route.UID)
		s.recomputeActiveViewLocked()
		return s.finishRepairLocked(EventResultApplied, ReasonAuthoritativeAbsent, requests)
	}

	fence := s.deletionByObject[key]
	if now.Sub(fence.createdAt) >= s.drainWindow {
		delete(s.deletionByObject, key)
		s.pruneRetiredUIDLocked(fence.uid, now)
		s.nextGenerationLocked()
		return s.finishRepairLocked(EventResultApplied, ReasonAuthoritativeAbsent, nil)
	}
	fence.confirmed = true
	fence.confirmationQueued = true
	fence.generation = s.nextGenerationLocked()
	s.deletionByObject[key] = fence
	return s.finishRepairLocked(EventResultApplied, ReasonAuthoritativeAbsent, nil)
}

func (s *Store) expireCompatibilityLocked(now time.Time) (bool, []RepairRequest) {
	claimsByID := make(map[string][]types.UID)
	for uid, record := range s.compatByUID {
		claimsByID[record.route.ID] = append(claimsByID[record.route.ID], uid)
	}
	changed := false
	requests := make([]RepairRequest, 0)
	for id, uids := range claimsByID {
		allExpired := true
		for _, uid := range uids {
			if now.Sub(s.compatByUID[uid].lastObserved) < s.drainWindow {
				allExpired = false
				break
			}
		}
		if len(uids) > 1 && !allExpired {
			continue
		}
		wasCollided := s.idCollidedLocked(id)
		removed := false
		for _, uid := range uids {
			if allExpired || now.Sub(s.compatByUID[uid].lastObserved) >= s.drainWindow {
				delete(s.compatByUID, uid)
				changed = true
				removed = true
			}
		}
		if removed && wasCollided {
			requests = append(requests, s.quarantineFullIDClaimsLocked(id)...)
		}
	}
	return changed, deduplicateRepairRequests(requests)
}

func (s *Store) installFullLocked(
	key types.NamespacedName,
	route Route,
	supersedeTargetCompatibility bool,
	preserveQuarantine bool,
) {
	now := s.now()
	generation := s.nextGenerationLocked()
	if current, exists := s.fullByObject[key]; exists && current.route.UID != route.UID {
		s.removeFullUIDOwnerLocked(current.route.UID, key)
		if !s.uidHasFullOwnerLocked(current.route.UID) {
			s.retiredByUID[current.route.UID] = retiredFence{
				uid:             current.route.UID,
				id:              current.route.ID,
				resourceVersion: current.route.ResourceVersion,
				generation:      generation,
				createdAt:       now,
			}
		}
	}
	delete(s.compatByUID, route.UID)
	delete(s.retiredByUID, route.UID)
	delete(s.deletionByObject, key)

	if supersedeTargetCompatibility {
		for uid, record := range s.compatByUID {
			if record.route.ID != route.ID {
				continue
			}
			delete(s.compatByUID, uid)
			s.retiredByUID[uid] = retiredFence{
				uid:             uid,
				id:              record.route.ID,
				resourceVersion: record.route.ResourceVersion,
				generation:      generation,
				createdAt:       now,
			}
		}
	}
	s.fullByObject[key] = routeRecord{
		route:       route,
		generation:  generation,
		quarantined: preserveQuarantine,
	}
	s.addFullUIDOwnerLocked(route.UID, key)
}

func (s *Store) deleteFullLocked(
	operation Operation,
	key types.NamespacedName,
	current routeRecord,
	fenceResourceVersion string,
) MutationResult {
	delete(s.fullByObject, key)
	s.removeFullUIDOwnerLocked(current.route.UID, key)
	generation := s.nextGenerationLocked()
	s.installDeletionFencesLocked(key, current.route, fenceResourceVersion, generation, false)
	requests := s.refreshQuarantinedUIDClaimsLocked(current.route.UID)
	s.recomputeActiveViewLocked()
	return s.finishLocked(operation, ShapeFull, EventResultApplied, ReasonNone, requests)
}

func (s *Store) deleteCompatibilityForObjectLocked(
	operation Operation,
	key types.NamespacedName,
	current routeRecord,
	fenceResourceVersion string,
) MutationResult {
	delete(s.compatByUID, current.route.UID)
	generation := s.nextGenerationLocked()
	s.installDeletionFencesLocked(key, current.route, fenceResourceVersion, generation, false)
	s.recomputeActiveViewLocked()
	return s.finishLocked(operation, ShapeIDOnly, EventResultApplied, ReasonNone, nil)
}

func (s *Store) installDeletionFencesLocked(
	key types.NamespacedName,
	deleted Route,
	fenceResourceVersion string,
	generation uint64,
	confirmed bool,
) {
	now := s.now()
	deletion := deletionFence{
		key:                key,
		uid:                deleted.UID,
		id:                 deleted.ID,
		resourceVersion:    fenceResourceVersion,
		generation:         generation,
		createdAt:          now,
		confirmationQueued: confirmed,
		confirmed:          confirmed,
	}
	if existing, exists := s.deletionByObject[key]; exists &&
		CompareResourceVersions(existing.resourceVersion, fenceResourceVersion) != ResourceVersionNewer {
		deletion.uid = existing.uid
		deletion.id = existing.id
		deletion.resourceVersion = existing.resourceVersion
		deletion.createdAt = existing.createdAt
		deletion.confirmed = existing.confirmed || confirmed
		deletion.confirmationQueued = existing.confirmationQueued || confirmed
	}
	s.deletionByObject[key] = deletion
	s.retiredByUID[deleted.UID] = retiredFence{
		uid:             deleted.UID,
		id:              deleted.ID,
		resourceVersion: fenceResourceVersion,
		generation:      generation,
		createdAt:       now,
	}
}

func hasExpectedShape(route Route, expected Shape) bool {
	if err := route.Validate(); err != nil {
		return false
	}
	shape, err := route.Shape()
	return err == nil && shape == expected
}

func equalOrNewer(current, incoming string) bool {
	comparison := CompareResourceVersions(current, incoming)
	return comparison == ResourceVersionEqual || comparison == ResourceVersionNewer
}

func allStrictlyOlder(records []routeRecord, incomingResourceVersion string) bool {
	if len(records) == 0 {
		return false
	}
	for _, record := range records {
		if CompareResourceVersions(record.route.ResourceVersion, incomingResourceVersion) != ResourceVersionNewer {
			return false
		}
	}
	return true
}

func (s *Store) compatibilityClaimsLocked(id string, excludeUID types.UID) []routeRecord {
	records := make([]routeRecord, 0)
	for uid, record := range s.compatByUID {
		if uid != excludeUID && record.route.ID == id {
			records = append(records, record)
		}
	}
	return records
}

func (s *Store) idHasFullOwnerLocked(id string) bool {
	for _, record := range s.fullByObject {
		if record.route.ID == id {
			return true
		}
	}
	return false
}

func (s *Store) uidHasFullOwnerLocked(uid types.UID) bool {
	return len(s.fullByUID[uid]) > 0
}

func (s *Store) addFullUIDOwnerLocked(uid types.UID, key types.NamespacedName) {
	owners := s.fullByUID[uid]
	if owners == nil {
		owners = make(map[types.NamespacedName]struct{})
		s.fullByUID[uid] = owners
	}
	owners[key] = struct{}{}
}

func (s *Store) removeFullUIDOwnerLocked(uid types.UID, key types.NamespacedName) {
	owners := s.fullByUID[uid]
	delete(owners, key)
	if len(owners) == 0 {
		delete(s.fullByUID, uid)
	}
}

func (s *Store) quarantineUIDClaimsLocked(uid types.UID, advanceGeneration bool) []RepairRequest {
	owners := s.fullByUID[uid]
	if len(owners) <= 1 {
		return nil
	}
	requests := make([]RepairRequest, 0, len(owners))
	for key := range owners {
		record := s.fullByObject[key]
		record.quarantined = true
		if advanceGeneration {
			record.generation = s.nextGenerationLocked()
		}
		s.fullByObject[key] = record
		requests = append(requests, RepairRequest{ObjectKey: key, Generation: record.generation})
	}
	sortRepairRequests(requests)
	return requests
}

func (s *Store) quarantineFullIDClaimsLocked(id string) []RepairRequest {
	requests := make([]RepairRequest, 0)
	for key, record := range s.fullByObject {
		if record.route.ID != id {
			continue
		}
		record.quarantined = true
		record.generation = s.nextGenerationLocked()
		s.fullByObject[key] = record
		requests = append(requests, RepairRequest{ObjectKey: key, Generation: record.generation})
	}
	sortRepairRequests(requests)
	return requests
}

func (s *Store) refreshQuarantinedUIDClaimsLocked(uid types.UID) []RepairRequest {
	owners := s.fullByUID[uid]
	requests := make([]RepairRequest, 0, len(owners))
	for key := range owners {
		record := s.fullByObject[key]
		if !record.quarantined {
			continue
		}
		record.generation = s.nextGenerationLocked()
		s.fullByObject[key] = record
		requests = append(requests, RepairRequest{ObjectKey: key, Generation: record.generation})
	}
	sortRepairRequests(requests)
	return requests
}

func (s *Store) idHasCompatibilityOwnerLocked(id string) bool {
	for _, record := range s.compatByUID {
		if record.route.ID == id {
			return true
		}
	}
	return false
}

func (s *Store) idHasDeletionFenceLocked(id string) bool {
	for _, fence := range s.deletionByObject {
		if fence.id == id {
			return true
		}
	}
	return false
}

func (s *Store) idCollidedLocked(id string) bool {
	_, collided := s.collisionsByID[id]
	return collided
}

func (s *Store) recomputeActiveViewLocked() {
	claims := make(map[string][]Route)
	forcedCollisions := make(map[string]struct{})
	for _, record := range s.fullByObject {
		claims[record.route.ID] = append(claims[record.route.ID], record.route)
		if record.quarantined {
			forcedCollisions[record.route.ID] = struct{}{}
		}
	}
	for _, record := range s.compatByUID {
		if s.idHasDeletionFenceLocked(record.route.ID) {
			continue
		}
		claims[record.route.ID] = append(claims[record.route.ID], record.route)
	}

	s.activeByID = make(map[string]Route, len(claims))
	s.collisionsByID = make(map[string]struct{})
	for id, routes := range claims {
		_, forced := forcedCollisions[id]
		if len(routes) == 1 && !forced {
			s.activeByID[id] = routes[0]
			continue
		}
		s.collisionsByID[id] = struct{}{}
	}
}

func (s *Store) nextGenerationLocked() uint64 {
	s.generation++
	return s.generation
}

func (s *Store) affectedGenerationLocked(key types.NamespacedName) (uint64, bool) {
	if record, exists := s.fullByObject[key]; exists {
		return record.generation, true
	}
	if fence, exists := s.deletionByObject[key]; exists {
		return fence.generation, true
	}
	return 0, false
}

func (s *Store) repairRequestsForIDLocked(id string) []RepairRequest {
	requests := make([]RepairRequest, 0)
	for key, record := range s.fullByObject {
		if record.route.ID == id {
			requests = append(requests, RepairRequest{ObjectKey: key, Generation: record.generation})
		}
	}
	sortRepairRequests(requests)
	return requests
}

func sortRepairRequests(requests []RepairRequest) {
	sort.Slice(requests, func(i, j int) bool {
		if requests[i].ObjectKey.Namespace == requests[j].ObjectKey.Namespace {
			return requests[i].ObjectKey.Name < requests[j].ObjectKey.Name
		}
		return requests[i].ObjectKey.Namespace < requests[j].ObjectKey.Namespace
	})
}

func deduplicateRepairRequests(requests []RepairRequest) []RepairRequest {
	newestByKey := make(map[types.NamespacedName]RepairRequest, len(requests))
	for _, request := range requests {
		current, exists := newestByKey[request.ObjectKey]
		if !exists || current.Generation < request.Generation {
			newestByKey[request.ObjectKey] = request
		}
	}
	deduplicated := make([]RepairRequest, 0, len(newestByKey))
	for _, request := range newestByKey {
		deduplicated = append(deduplicated, request)
	}
	sortRepairRequests(deduplicated)
	return deduplicated
}

func (s *Store) uidHasDeletionFenceLocked(uid types.UID) bool {
	for _, fence := range s.deletionByObject {
		if fence.uid == uid {
			return true
		}
	}
	return false
}

func (s *Store) pruneRetiredUIDLocked(uid types.UID, now time.Time) {
	fence, exists := s.retiredByUID[uid]
	if !exists || now.Sub(fence.createdAt) < s.drainWindow || s.uidHasDeletionFenceLocked(uid) {
		return
	}
	delete(s.retiredByUID, uid)
}

func (s *Store) recordWithoutMutation(
	operation Operation,
	shape Shape,
	result EventResult,
	reason Reason,
) MutationResult {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.finishLocked(operation, shape, result, reason, nil)
}

func (s *Store) finishLocked(
	operation Operation,
	shape Shape,
	result EventResult,
	reason Reason,
	requests []RepairRequest,
) MutationResult {
	recordEvent(s.surface, shape, operation, result)
	if result == EventResultCollision {
		sandboxidmetrics.RecordCollision(s.collisionMetricSurface())
	}
	s.setRecordMetricsLocked()
	return MutationResult{
		Result:         result,
		Reason:         reason,
		RepairRequests: append([]RepairRequest(nil), requests...),
	}
}

func (s *Store) finishRepairLocked(
	result EventResult,
	reason Reason,
	requests []RepairRequest,
) MutationResult {
	if result == EventResultCollision {
		sandboxidmetrics.RecordCollision(s.collisionMetricSurface())
	}
	s.setRecordMetricsLocked()
	return MutationResult{
		Result:         result,
		Reason:         reason,
		RepairRequests: append([]RepairRequest(nil), requests...),
	}
}

func (s *Store) collisionMetricSurface() string {
	if s.surface == SurfaceGateway {
		return "gateway_route"
	}
	return "manager_route"
}

func (s *Store) setRecordMetricsLocked() {
	stats := s.statsLocked()
	setRecords(s.surface, ShapeFull, stats.Full)
	setRecords(s.surface, ShapeIDOnly, stats.IDOnly)
	setRecords(s.surface, ShapeRetired, stats.Retired)
	setRecords(s.surface, ShapeCollision, stats.Collision)
}

func (s *Store) statsLocked() StoreStats {
	return StoreStats{
		Full:      len(s.fullByObject),
		IDOnly:    len(s.compatByUID),
		Retired:   len(s.retiredByUID),
		Deletion:  len(s.deletionByObject),
		Collision: len(s.collisionsByID),
		Active:    len(s.activeByID),
	}
}
