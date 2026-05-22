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

package models

const (
	// DefaultMaxTimeout is a local default. Production deployments should override it
	// with --e2b-max-timeout to a far-future value that matches the desired retention policy.
	DefaultMaxTimeout        = 2592000 // 30 days
	DefaultMinTimeoutSeconds = 30      // existing Create-path floor
	DefaultTimeoutSeconds    = 300

	// DefaultMinResumeTimeoutSeconds is the minimum effective timeout for
	// Connect / Resume requests that trigger Resume on a Paused sandbox.
	// Resume itself may take up to a few minutes (CSI mount + ReInit +
	// container start); a placeholder timeout shorter than that would let
	// the controller auto-pause mid-Resume, leaving the sandbox paused
	// despite the request returning success. Override via
	// --e2b-min-resume-timeout if production Resume durations exceed 5 min.
	DefaultMinResumeTimeoutSeconds = 300 // 5 min

	MaxListLimit = 100
	MinListLimit = 1
)
