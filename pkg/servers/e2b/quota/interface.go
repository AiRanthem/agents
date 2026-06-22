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
	"time"

	agentsv1alpha1 "github.com/openkruise/agents/api/v1alpha1"
	"github.com/openkruise/agents/pkg/servers/e2b/models"
)

type Config struct {
	RedisAddr         string
	RedisUsername     string
	RedisPassword     string
	RedisDB           int
	OperationTimeout  time.Duration
	BreakerN          int
	BreakerD          time.Duration
	AntiDriftInterval time.Duration
	AntiDriftGrace    time.Duration
}

type Entry struct {
	Footprint map[models.QuotaDimension]int64
	Scopes    []models.QuotaScope
}

type AcquireParams struct {
	APIKeyID   string
	LockString string
	Footprint  map[models.QuotaDimension]int64
	Scopes     []models.QuotaScope
	Enforce    bool
	Limits     map[models.QuotaDimension]map[models.QuotaScope]int64
}

type Backend interface {
	Acquire(ctx context.Context, p AcquireParams) error
	Release(ctx context.Context, apiKeyID, lockString string) error
	ListEntries(ctx context.Context, apiKeyID string) (map[string]Entry, error)
	Cleanup(ctx context.Context, apiKeyID string) error
}

type AcquireRequest struct {
	APIKeyID   string
	LockString string
	Quota      *models.QuotaSpec
	Footprint  map[models.QuotaDimension]int64
	Scopes     []models.QuotaScope
}

type ReleaseRequest struct {
	APIKeyID   string
	LockString string
}

type LimitedKeyStore interface {
	ListLimited(ctx context.Context) ([]*models.CreatedTeamAPIKey, error)
}

type LiveSandboxCache interface {
	ListLiveSandboxesByOwner(ctx context.Context, owner string) ([]*agentsv1alpha1.Sandbox, error)
	SandboxInformerHealthy() bool
}

type PrimaryChecker interface {
	IsPrimary() bool
}
