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
	"encoding/json"
	"errors"
	"fmt"
)

type QuotaDimension string

const (
	DimSandboxCount QuotaDimension = "sandbox.count"
	DimLimitsCPU    QuotaDimension = "limits.cpu"
	DimLimitsMemory QuotaDimension = "limits.memory"
)

type QuotaScope string

const (
	ScopeAll     QuotaScope = "all"
	ScopeRunning QuotaScope = "running"
)

var ErrQuotaLimitNegative = errors.New("quota limit must be non-negative")

type QuotaLimit struct {
	Dimension QuotaDimension `json:"dimension"`
	Scope     QuotaScope     `json:"scope"`
	Limit     int64          `json:"limit"`
}

type QuotaSpec struct {
	Limits []QuotaLimit `json:"limits,omitempty"`
}

func (q *QuotaSpec) IsLimited() bool {
	return q != nil && len(q.Limits) > 0
}

func (q *QuotaSpec) LimitedPairs() map[QuotaDimension]map[QuotaScope]int64 {
	if q == nil {
		return nil
	}

	pairs := make(map[QuotaDimension]map[QuotaScope]int64, len(q.Limits))
	for _, limit := range q.Limits {
		if _, ok := pairs[limit.Dimension]; !ok {
			pairs[limit.Dimension] = map[QuotaScope]int64{}
		}
		pairs[limit.Dimension][limit.Scope] = limit.Limit
	}
	return pairs
}

func (q *QuotaSpec) DeepCopy() *QuotaSpec {
	if q == nil {
		return nil
	}

	out := &QuotaSpec{Limits: make([]QuotaLimit, len(q.Limits))}
	copy(out.Limits, q.Limits)
	return out
}

func NormalizeQuotaSpec(spec *QuotaSpec) (*QuotaSpec, error) {
	if spec == nil || len(spec.Limits) == 0 {
		return nil, nil
	}

	normalized := &QuotaSpec{Limits: make([]QuotaLimit, 0, len(spec.Limits))}
	seen := make(map[string]struct{}, len(spec.Limits))
	for _, limit := range spec.Limits {
		if err := validateQuotaDimension(limit.Dimension); err != nil {
			return nil, err
		}
		if err := validateQuotaScope(limit.Scope); err != nil {
			return nil, err
		}
		if limit.Limit < 0 {
			return nil, ErrQuotaLimitNegative
		}

		key := string(limit.Dimension) + "\x00" + string(limit.Scope)
		if _, ok := seen[key]; ok {
			return nil, fmt.Errorf("duplicate quota limit for dimension %q and scope %q", limit.Dimension, limit.Scope)
		}
		seen[key] = struct{}{}
		normalized.Limits = append(normalized.Limits, limit)
	}

	if len(normalized.Limits) == 0 {
		return nil, nil
	}
	return normalized, nil
}

func DecodeQuotaSpec(raw []byte) (*QuotaSpec, error) {
	if len(raw) == 0 || string(raw) == "null" {
		return nil, nil
	}

	var stored map[string]json.RawMessage
	if err := json.Unmarshal(raw, &stored); err != nil {
		return nil, fmt.Errorf("unmarshal quota: %w", err)
	}
	if len(stored) == 0 {
		return nil, errors.New("stored quota missing limits")
	}
	if _, ok := stored["limits"]; !ok {
		return nil, errors.New("stored quota missing limits")
	}
	if len(stored) != 1 {
		return nil, errors.New("stored quota contains unsupported fields")
	}

	var spec QuotaSpec
	if err := json.Unmarshal(raw, &spec); err != nil {
		return nil, fmt.Errorf("unmarshal quota: %w", err)
	}

	normalized, err := NormalizeQuotaSpec(&spec)
	if err != nil {
		return nil, err
	}
	return normalized, nil
}

func MarshalQuotaSpec(spec *QuotaSpec) ([]byte, error) {
	normalized, err := NormalizeQuotaSpec(spec)
	if err != nil {
		return nil, err
	}
	if normalized == nil {
		return nil, nil
	}

	raw, err := json.Marshal(normalized)
	if err != nil {
		return nil, fmt.Errorf("marshal quota: %w", err)
	}
	return raw, nil
}

func QuotaSpecFromWire(raw json.RawMessage) (*QuotaSpec, error) {
	if len(raw) == 0 || string(raw) == "null" {
		return nil, nil
	}

	var wire map[string]map[string]int64
	if err := json.Unmarshal(raw, &wire); err != nil {
		return nil, fmt.Errorf("unmarshal quota wire: %w", err)
	}
	if len(wire) == 0 {
		return nil, nil
	}

	for scopeName, dims := range wire {
		scope := QuotaScope(scopeName)
		if err := validateQuotaScope(scope); err != nil {
			return nil, err
		}
		for dimName := range dims {
			if _, err := quotaDimensionFromWireKey(dimName); err != nil {
				return nil, err
			}
		}
	}

	spec := &QuotaSpec{}
	for _, scope := range []QuotaScope{ScopeRunning, ScopeAll} {
		dims, ok := wire[string(scope)]
		if !ok {
			continue
		}
		for _, dimName := range []string{"count", "cpu", "memory"} {
			limit, exists := dims[dimName]
			if !exists {
				continue
			}
			dimension, err := quotaDimensionFromWireKey(dimName)
			if err != nil {
				return nil, err
			}
			spec.Limits = append(spec.Limits, QuotaLimit{
				Dimension: dimension,
				Scope:     scope,
				Limit:     limit,
			})
		}
	}

	return NormalizeQuotaSpec(spec)
}

func WireFromQuotaSpec(spec *QuotaSpec) json.RawMessage {
	if spec == nil || len(spec.Limits) == 0 {
		return nil
	}

	wire := make(map[string]map[string]int64, 2)
	for _, limit := range spec.Limits {
		scopeKey := string(limit.Scope)
		if _, ok := wire[scopeKey]; !ok {
			wire[scopeKey] = map[string]int64{}
		}
		wire[scopeKey][quotaDimensionWireKey(limit.Dimension)] = limit.Limit
	}

	raw, _ := json.Marshal(wire)
	return raw
}

func validateQuotaDimension(dimension QuotaDimension) error {
	switch dimension {
	case DimSandboxCount, DimLimitsCPU, DimLimitsMemory:
		return nil
	default:
		return fmt.Errorf("unsupported quota dimension %q", dimension)
	}
}

func validateQuotaScope(scope QuotaScope) error {
	switch scope {
	case ScopeAll, ScopeRunning:
		return nil
	default:
		return fmt.Errorf("unsupported quota scope %q", scope)
	}
}

func quotaDimensionFromWireKey(key string) (QuotaDimension, error) {
	switch key {
	case "count":
		return DimSandboxCount, nil
	case "cpu":
		return DimLimitsCPU, nil
	case "memory":
		return DimLimitsMemory, nil
	default:
		return "", fmt.Errorf("unsupported quota dimension %q", key)
	}
}

func quotaDimensionWireKey(dimension QuotaDimension) string {
	switch dimension {
	case DimSandboxCount:
		return "count"
	case DimLimitsCPU:
		return "cpu"
	case DimLimitsMemory:
		return "memory"
	default:
		return string(dimension)
	}
}
