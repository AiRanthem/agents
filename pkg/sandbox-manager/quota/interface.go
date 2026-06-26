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
	"context"

	agentsv1alpha1 "github.com/openkruise/agents/api/v1alpha1"
)

type Entry struct {
	Footprint map[QuotaDimension]int64
	Scopes    []QuotaScope
}

type AcquireParams struct {
	User       string
	LockString string
	Footprint  map[QuotaDimension]int64
	Scopes     []QuotaScope
	Enforce    bool
	Limits     map[QuotaDimension]map[QuotaScope]int64
}

type Backend interface {
	Acquire(ctx context.Context, p AcquireParams) error
	Release(ctx context.Context, user, lockString string) error
	ListEntries(ctx context.Context, user string) (map[string]Entry, error)
	Cleanup(ctx context.Context, user string) error
}

type AcquireRequest struct {
	User       string
	LockString string
	Quota      *QuotaSpec
	Footprint  map[QuotaDimension]int64
	Scopes     []QuotaScope
}

type ReleaseRequest struct {
	User       string
	LockString string
}

// Subject is a quota-bearing identity (user/api-key) with its resolved limits.
type Subject struct {
	User  string
	Quota *QuotaSpec
}

// SubjectLister enumerates and loads limited subjects without coupling to any
// specific key-store implementation.
type SubjectLister interface {
	ListLimited(ctx context.Context) ([]Subject, error)
	Load(ctx context.Context, user string) (Subject, bool)
}

type LiveSandboxCache interface {
	ListLiveSandboxesByOwner(ctx context.Context, owner string) ([]*agentsv1alpha1.Sandbox, error)
	SandboxInformerHealthy() bool
}

type PrimaryChecker interface {
	IsPrimary() bool
}
