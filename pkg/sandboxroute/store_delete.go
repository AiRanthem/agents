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
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/apimachinery/pkg/util/resourceversion"
)

// Delete removes one ObjectKey. A non-empty resource version may establish a
// fence even without a prior record; an empty one removes the current record
// using its RV as the fence and is a no-op when no record exists.
func (s *Store) Delete(route Route) MutationResult {
	key, reason := validateDeleteRoute(route)
	if reason != ReasonNone {
		return MutationResult{Result: EventResultInvalid, Reason: reason}
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	current, hasCurrent := s.recordByObject[key]
	fenceResourceVersion := s.deletionByObject[key]

	if route.ResourceVersion == "" {
		if hasCurrent {
			s.deleteRecordLocked(key, current, current.ResourceVersion)
		}
		return MutationResult{Result: EventResultApplied}
	}

	currentResourceVersion := fenceResourceVersion
	if hasCurrent {
		currentResourceVersion = current.ResourceVersion
	}
	if currentResourceVersion != "" {
		comparison, err := resourceversion.CompareResourceVersion(
			route.ResourceVersion,
			currentResourceVersion,
		)
		if err != nil {
			return MutationResult{Result: EventResultInvalid, Reason: ReasonInvalidRoute}
		}
		if comparison < 0 {
			return MutationResult{Result: EventResultIgnored, Reason: ReasonStaleResourceVersion}
		}
	}

	if hasCurrent {
		s.deleteRecordLocked(key, current, route.ResourceVersion)
	} else {
		s.deletionByObject[key] = route.ResourceVersion
	}
	return MutationResult{Result: EventResultApplied}
}

func validateDeleteRoute(route Route) (types.NamespacedName, Reason) {
	key, err := routeObjectKey(route)
	if err != nil {
		return types.NamespacedName{}, ReasonInvalidRoute
	}
	if route.ResourceVersion == "" {
		return key, ReasonNone
	}
	if _, err := resourceversion.CompareResourceVersion(route.ResourceVersion, route.ResourceVersion); err != nil {
		return types.NamespacedName{}, ReasonInvalidRoute
	}
	return key, ReasonNone
}

func (s *Store) deleteRecordLocked(
	key types.NamespacedName,
	current Route,
	fenceResourceVersion string,
) {
	s.deactivateRouteLocked(key, current.ID)
	delete(s.recordByObject, key)
	s.deletionByObject[key] = fenceResourceVersion
}
