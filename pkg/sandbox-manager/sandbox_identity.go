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

package sandbox_manager

import (
	"errors"
	"fmt"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	"github.com/openkruise/agents/pkg/sandbox-manager/infra"
	"github.com/openkruise/agents/pkg/sandboxid"
)

// ErrReservedSandboxIDMutation reports a caller attempt to mutate the core-owned ID label.
var ErrReservedSandboxIDMutation = errors.New("reserved sandbox ID label was mutated")

type reservedLabelSnapshot struct {
	present bool
	value   string
}

func snapshotReservedLabel(object metav1.Object) reservedLabelSnapshot {
	value, present := object.GetLabels()[sandboxid.LabelKey]
	return reservedLabelSnapshot{present: present, value: value}
}

func ensureReservedLabelUnchanged(object metav1.Object, before reservedLabelSnapshot) error {
	after := snapshotReservedLabel(object)
	if before == after {
		return nil
	}
	return fmt.Errorf("%w: %s is managed by sandbox-manager core", ErrReservedSandboxIDMutation, sandboxid.LabelKey)
}

// decoratePreModifier guards the core-owned ID label from mutation.
func decoratePreModifier(modifier func(infra.Sandbox) error) func(infra.Sandbox) error {
	if modifier == nil {
		return nil
	}
	return func(sandbox infra.Sandbox) error {
		before := snapshotReservedLabel(sandbox)
		if err := modifier(sandbox); err != nil {
			return err
		}
		return ensureReservedLabelUnchanged(sandbox, before)
	}
}

// decoratePostModifier guards the core-owned ID label from mutation, and optionally assigns a sandbox ID.
func decoratePostModifier(
	modifier func(metav1.Object) (bool, error),
	enableAssignment bool,
	prefix string,
) func(metav1.Object) (bool, error) {
	if modifier == nil && !enableAssignment {
		return nil
	}

	return func(sandbox metav1.Object) (bool, error) {
		changed := false
		if modifier != nil {
			before := snapshotReservedLabel(sandbox)
			callerChanged, err := modifier(sandbox)
			if err != nil {
				return false, err
			}
			if err := ensureReservedLabelUnchanged(sandbox, before); err != nil {
				return false, err
			}
			changed = callerChanged
		}

		if !enableAssignment {
			return changed, nil
		}
		assigned, err := sandboxid.AssignShort(sandbox, prefix)
		if err != nil {
			return false, err
		}
		return changed || assigned, nil
	}
}

func (m *SandboxManager) prepareClaimSandboxIdentity(opts infra.ClaimSandboxOptions) infra.ClaimSandboxOptions {
	opts.Modifier = decoratePreModifier(opts.Modifier)
	opts.PostModifier = decoratePostModifier(opts.PostModifier, m.enableShortID, m.shortIDPrefix)
	return opts
}

func (m *SandboxManager) prepareCloneSandboxIdentity(opts infra.CloneSandboxOptions) infra.CloneSandboxOptions {
	opts.Modifier = decoratePreModifier(opts.Modifier)
	opts.PostModifier = decoratePostModifier(opts.PostModifier, m.enableShortID, m.shortIDPrefix)
	return opts
}
