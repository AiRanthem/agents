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

package sandboxid

import (
	"encoding/base32"
	"fmt"
	"strings"

	"github.com/google/uuid"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"

	agentsv1alpha1 "github.com/openkruise/agents/api/v1alpha1"
)

const (
	// LabelKey is the reserved Sandbox label containing an authoritative ID.
	LabelKey = agentsv1alpha1.LabelSandboxID
	// LegacySeparator separates namespace and name in a legacy Sandbox ID.
	LegacySeparator = "--"
	// ShortIDLength is the fixed length of an encoded short ID: 16 UID bytes
	// as unpadded Base32. Length policy on top of it is owned by callers.
	ShortIDLength = 26
)

var shortEncoding = base32.StdEncoding.WithPadding(base32.NoPadding)

// Resolve returns the authoritative label value or the legacy ID when no value is set.
func Resolve(sandbox metav1.Object) string {
	if sandboxID := sandbox.GetLabels()[LabelKey]; sandboxID != "" {
		return sandboxID
	}
	return Legacy(sandbox.GetNamespace(), sandbox.GetName())
}

// Legacy returns the legacy namespace-and-name Sandbox ID.
func Legacy(namespace, name string) string {
	return namespace + LegacySeparator + name
}

// GenerateShort encodes all 128 bits of a Kubernetes UID as lowercase unpadded Base32.
func GenerateShort(uid types.UID) (string, error) {
	parsed, err := uuid.Parse(string(uid))
	if err != nil {
		return "", fmt.Errorf("invalid sandbox UID %q: %w", uid, err)
	}
	return strings.ToLower(shortEncoding.EncodeToString(parsed[:])), nil
}

// ValidatePrefix checks that prefix uses only [a-z0-9-] and, when non-empty,
// starts with [a-z0-9]. Callers own broader prefix and ID correctness policy.
func ValidatePrefix(prefix string) error {
	if prefix != "" && !isLowerAlphanumeric(prefix[0]) {
		return fmt.Errorf(
			"short sandbox ID prefix %q is invalid: it must start with a lowercase letter or digit",
			prefix,
		)
	}
	for i := 1; i < len(prefix); i++ {
		char := prefix[i]
		if isLowerAlphanumeric(char) || char == '-' {
			continue
		}
		return fmt.Errorf(
			"short sandbox ID prefix %q is invalid: character %q at position %d is not "+
				"a lowercase letter, digit, or hyphen",
			prefix,
			char,
			i,
		)
	}
	return nil
}

func isLowerAlphanumeric(char byte) bool {
	return (char >= 'a' && char <= 'z') || (char >= '0' && char <= '9')
}

// AssignShort assigns a prefixed short ID only when the authoritative label value is empty.
// The caller must validate prefix before calling.
func AssignShort(sandbox metav1.Object, prefix string) (bool, error) {
	labels := sandbox.GetLabels()
	if labels[LabelKey] != "" {
		return false, nil
	}

	sandboxID, err := GenerateShort(sandbox.GetUID())
	if err != nil {
		return false, err
	}
	if labels == nil {
		labels = make(map[string]string, 1)
	}
	labels[LabelKey] = prefix + sandboxID
	sandbox.SetLabels(labels)
	return true, nil
}
