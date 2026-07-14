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

import "strconv"

// ResourceVersionComparison describes incoming relative to current.
type ResourceVersionComparison string

const (
	ResourceVersionOlder       ResourceVersionComparison = "older"
	ResourceVersionEqual       ResourceVersionComparison = "equal"
	ResourceVersionNewer       ResourceVersionComparison = "newer"
	ResourceVersionUnorderable ResourceVersionComparison = "unorderable"
)

// CompareResourceVersions compares incoming against current using base-10 uint64 ordering.
func CompareResourceVersions(current, incoming string) ResourceVersionComparison {
	if current == incoming {
		return ResourceVersionEqual
	}
	currentValue, currentErr := strconv.ParseUint(current, 10, 64)
	incomingValue, incomingErr := strconv.ParseUint(incoming, 10, 64)
	if currentErr != nil || incomingErr != nil {
		return ResourceVersionUnorderable
	}
	switch {
	case incomingValue < currentValue:
		return ResourceVersionOlder
	case incomingValue > currentValue:
		return ResourceVersionNewer
	default:
		return ResourceVersionEqual
	}
}
