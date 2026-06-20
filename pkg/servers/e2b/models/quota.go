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

import (
	"bytes"
	"encoding/json"
	"fmt"
)

// QuotaDimension identifies a quota dimension used by internal quota storage and enforcement.
type QuotaDimension string

const DimSandboxCount QuotaDimension = "sandbox.count"

// QuotaScope identifies the scope of a quota limit.
type QuotaScope struct {
	Template string `json:"template,omitempty"`
}

// QuotaLimit represents one internal quota limit.
type QuotaLimit struct {
	Dimension QuotaDimension `json:"dimension"`
	Scope     QuotaScope     `json:"scope,omitempty"`
	Limit     *int64         `json:"limit,omitempty"`
}

// QuotaSpec is the internal quota shape used by storage and enforcement.
type QuotaSpec struct {
	Limits []QuotaLimit `json:"limits,omitempty"`
}

// APIKeyQuota is the public quota shape for API key requests and responses.
type APIKeyQuota struct {
	Sandbox *SandboxQuota `json:"sandbox,omitempty"`
}

// SandboxQuota is the public sandbox quota shape.
type SandboxQuota struct {
	Count *int64 `json:"count,omitempty"`
}

// UnmarshalJSON rejects unknown public quota dimensions.
func (q *APIKeyQuota) UnmarshalJSON(data []byte) error {
	if isJSONNull(data) {
		*q = APIKeyQuota{}
		return nil
	}

	var fields map[string]json.RawMessage
	if err := json.Unmarshal(data, &fields); err != nil {
		return err
	}

	for field := range fields {
		if field != "sandbox" {
			return fmt.Errorf("unsupported quota field %q", field)
		}
	}

	type apiKeyQuota APIKeyQuota
	var decoded apiKeyQuota
	if err := json.Unmarshal(data, &decoded); err != nil {
		return err
	}
	*q = APIKeyQuota(decoded)
	return nil
}

// UnmarshalJSON rejects unknown public sandbox quota dimensions.
func (q *SandboxQuota) UnmarshalJSON(data []byte) error {
	if isJSONNull(data) {
		*q = SandboxQuota{}
		return nil
	}

	var fields map[string]json.RawMessage
	if err := json.Unmarshal(data, &fields); err != nil {
		return err
	}

	for field := range fields {
		if field != "count" {
			return fmt.Errorf("unsupported sandbox quota field %q", field)
		}
	}

	type sandboxQuota SandboxQuota
	var decoded sandboxQuota
	if err := json.Unmarshal(data, &decoded); err != nil {
		return err
	}
	*q = SandboxQuota(decoded)
	return nil
}

// ToQuotaSpec converts the public quota shape to the internal quota shape.
func (q *APIKeyQuota) ToQuotaSpec() (*QuotaSpec, error) {
	if q == nil || q.Sandbox == nil || q.Sandbox.Count == nil {
		return nil, nil
	}

	return NormalizeQuotaSpec(&QuotaSpec{
		Limits: []QuotaLimit{
			{
				Dimension: DimSandboxCount,
				Limit:     q.Sandbox.Count,
			},
		},
	})
}

// APIKeyQuotaFromSpec converts an internal quota spec to the public quota shape.
// Callers that need invalid internal spec visibility should use APIKeyQuotaFromSpecChecked.
func APIKeyQuotaFromSpec(spec *QuotaSpec) *APIKeyQuota {
	quota, err := APIKeyQuotaFromSpecChecked(spec)
	if err != nil {
		return nil
	}
	return quota
}

// APIKeyQuotaFromSpecChecked converts an internal quota spec to the public quota shape.
func APIKeyQuotaFromSpecChecked(spec *QuotaSpec) (*APIKeyQuota, error) {
	normalized, err := NormalizeQuotaSpec(spec)
	if err != nil {
		return nil, err
	}
	if normalized == nil {
		return nil, nil
	}

	limit, ok := normalized.SandboxCountLimit()
	if !ok {
		return nil, nil
	}

	limitCopy := limit
	return &APIKeyQuota{
		Sandbox: &SandboxQuota{
			Count: &limitCopy,
		},
	}, nil
}

// DeepCopy copies the public API key quota shape and nested limit pointers.
func (q *APIKeyQuota) DeepCopy() *APIKeyQuota {
	if q == nil {
		return nil
	}

	copyQuota := &APIKeyQuota{}
	if q.Sandbox != nil {
		copyQuota.Sandbox = &SandboxQuota{}
		if q.Sandbox.Count != nil {
			countCopy := *q.Sandbox.Count
			copyQuota.Sandbox.Count = &countCopy
		}
	}
	return copyQuota
}

// NormalizeQuotaSpec validates and copies the internal quota shape.
func NormalizeQuotaSpec(spec *QuotaSpec) (*QuotaSpec, error) {
	if spec == nil || len(spec.Limits) == 0 {
		return nil, nil
	}

	normalized := &QuotaSpec{
		Limits: make([]QuotaLimit, 0, len(spec.Limits)),
	}
	seen := make(map[string]struct{}, len(spec.Limits))
	for _, limit := range spec.Limits {
		if limit.Dimension != DimSandboxCount {
			return nil, fmt.Errorf("unsupported quota dimension %q", limit.Dimension)
		}
		if limit.Scope != (QuotaScope{}) {
			return nil, fmt.Errorf("quota scope is not supported for dimension %q", limit.Dimension)
		}

		if limit.Limit == nil {
			continue
		}
		key := quotaLimitKey(limit)
		if _, ok := seen[key]; ok {
			return nil, fmt.Errorf("duplicate quota limit for dimension %q and scope", limit.Dimension)
		}
		seen[key] = struct{}{}

		if *limit.Limit < 0 {
			return nil, fmt.Errorf("quota limit for dimension %q cannot be negative", limit.Dimension)
		}

		limitCopy := *limit.Limit
		normalized.Limits = append(normalized.Limits, QuotaLimit{
			Dimension: limit.Dimension,
			Scope:     limit.Scope,
			Limit:     &limitCopy,
		})
	}

	if len(normalized.Limits) == 0 {
		return nil, nil
	}
	return normalized, nil
}

// SandboxCountLimit returns the sandbox.count limit when it is set.
func (q *QuotaSpec) SandboxCountLimit() (int64, bool) {
	if q == nil {
		return 0, false
	}
	for _, limit := range q.Limits {
		if limit.Dimension == DimSandboxCount && limit.Scope == (QuotaScope{}) && limit.Limit != nil {
			return *limit.Limit, true
		}
	}
	return 0, false
}

// IsLimited returns true when the spec contains an active quota limit.
func (q *QuotaSpec) IsLimited() bool {
	_, ok := q.SandboxCountLimit()
	return ok
}

// DeepCopy copies the quota spec and limit pointers.
func (q *QuotaSpec) DeepCopy() *QuotaSpec {
	if q == nil {
		return nil
	}

	copySpec := &QuotaSpec{
		Limits: make([]QuotaLimit, 0, len(q.Limits)),
	}
	for _, limit := range q.Limits {
		limitCopy := QuotaLimit{
			Dimension: limit.Dimension,
			Scope:     limit.Scope,
		}
		if limit.Limit != nil {
			valueCopy := *limit.Limit
			limitCopy.Limit = &valueCopy
		}
		copySpec.Limits = append(copySpec.Limits, limitCopy)
	}
	return copySpec
}

func isJSONNull(data []byte) bool {
	return bytes.Equal(bytes.TrimSpace(data), []byte("null"))
}

func quotaLimitKey(limit QuotaLimit) string {
	return fmt.Sprintf("%s/%s", limit.Dimension, limit.Scope.Template)
}
