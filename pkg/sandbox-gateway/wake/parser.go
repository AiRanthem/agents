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

package wake

import (
	"strconv"
	"strings"
)

const annotationPrefix = "timeout:"

func ParseAnnotation(value string) (int, bool) {
	if value == "timeout:never" {
		return 1, true
	}
	if !strings.HasPrefix(value, annotationPrefix) {
		return 0, false
	}
	raw := strings.TrimPrefix(value, annotationPrefix)
	if raw == "" || strings.TrimSpace(raw) != raw {
		return 0, false
	}
	for _, r := range raw {
		if r < '0' || r > '9' {
			return 0, false
		}
	}
	timeout, err := strconv.Atoi(raw)
	if err != nil || timeout <= 0 {
		return 0, false
	}
	return timeout, true
}
