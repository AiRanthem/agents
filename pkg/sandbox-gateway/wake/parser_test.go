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
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestParseAnnotation(t *testing.T) {
	tests := []struct {
		name          string
		value         string
		expectTimeout int
		expectEnabled bool
	}{
		{name: "never", value: "timeout:never", expectTimeout: 1, expectEnabled: true},
		{name: "positive seconds", value: "timeout:300", expectTimeout: 300, expectEnabled: true},
		{name: "empty", value: "", expectEnabled: false},
		{name: "wrong key", value: "ttl:300", expectEnabled: false},
		{name: "missing value", value: "timeout:", expectEnabled: false},
		{name: "zero", value: "timeout:0", expectEnabled: false},
		{name: "negative", value: "timeout:-1", expectEnabled: false},
		{name: "plus sign", value: "timeout:+1", expectEnabled: false},
		{name: "float", value: "timeout:1.5", expectEnabled: false},
		{name: "space before", value: " timeout:300", expectEnabled: false},
		{name: "space after", value: "timeout:300 ", expectEnabled: false},
		{name: "uppercase never", value: "timeout:Never", expectEnabled: false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			gotTimeout, gotEnabled := ParseAnnotation(tt.value)
			assert.Equal(t, tt.expectTimeout, gotTimeout)
			assert.Equal(t, tt.expectEnabled, gotEnabled)
		})
	}
}
