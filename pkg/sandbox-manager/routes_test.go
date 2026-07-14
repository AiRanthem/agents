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
	"context"
	"errors"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/labels"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"

	agentsv1alpha1 "github.com/openkruise/agents/api/v1alpha1"
	infracache "github.com/openkruise/agents/pkg/cache"
	"github.com/openkruise/agents/pkg/cache/cachetest"
	"github.com/openkruise/agents/pkg/proxy"
	"github.com/openkruise/agents/pkg/sandbox-manager/config"
	"github.com/openkruise/agents/pkg/sandbox-manager/infra"
	"github.com/openkruise/agents/pkg/sandbox-manager/infra/sandboxcr"
	"github.com/openkruise/agents/pkg/sandbox-manager/sandboxid"
	"github.com/openkruise/agents/pkg/sandboxroute"
)

func newManagerRouteTestSandbox(namespace, name string) *agentsv1alpha1.Sandbox {
	return &agentsv1alpha1.Sandbox{
		ObjectMeta: metav1.ObjectMeta{
			Namespace:       namespace,
			Name:            name,
			UID:             types.UID("uid-" + name),
			ResourceVersion: "10",
			Labels:          map[string]string{"env": "prod"},
			Annotations: map[string]string{
				agentsv1alpha1.AnnotationOwner:              "owner-a",
				agentsv1alpha1.AnnotationRuntimeAccessToken: "secret-token",
			},
		},
		Status: agentsv1alpha1.SandboxStatus{
			Phase:   agentsv1alpha1.SandboxRunning,
			PodInfo: agentsv1alpha1.PodInfo{PodIP: "10.0.0.1"},
			Conditions: []metav1.Condition{{
				Type:   string(agentsv1alpha1.SandboxConditionReady),
				Status: metav1.ConditionTrue,
			}},
		},
	}
}

func newRouteTestManager(t *testing.T) *SandboxManager {
	t.Helper()
	selector, err := labels.Parse("env=prod")
	require.NoError(t, err)
	return &SandboxManager{
		proxy:          proxy.NewServer(config.InitOptions(config.SandboxManagerOptions{})),
		routeProjector: newManagerRouteProjector(),
		routeNamespace: "team-a",
		routeSelector:  selector,
	}
}

func TestSandboxManagerReconcileSandboxRoute(t *testing.T) {
	tests := []struct {
		name          string
		sandbox       *agentsv1alpha1.Sandbox
		notFound      bool
		seed          func(t *testing.T, manager *SandboxManager, sandbox *agentsv1alpha1.Sandbox)
		expectID      string
		expectPresent bool
	}{
		{
			name:          "present legacy route",
			sandbox:       newManagerRouteTestSandbox("team-a", "legacy"),
			expectID:      "team-a--legacy",
			expectPresent: true,
		},
		{
			name: "present short route",
			sandbox: func() *agentsv1alpha1.Sandbox {
				sandbox := newManagerRouteTestSandbox("team-a", "short")
				sandbox.Labels[agentsv1alpha1.LabelSandboxID] = "opaque-short-id"
				return sandbox
			}(),
			expectID:      "opaque-short-id",
			expectPresent: true,
		},
		{
			name: "deleting object is authoritative absence",
			sandbox: func() *agentsv1alpha1.Sandbox {
				sandbox := newManagerRouteTestSandbox("team-a", "deleting")
				now := metav1.Now()
				sandbox.DeletionTimestamp = &now
				return sandbox
			}(),
			seed: func(t *testing.T, manager *SandboxManager, sandbox *agentsv1alpha1.Sandbox) {
				copy := sandbox.DeepCopy()
				copy.DeletionTimestamp = nil
				route, err := manager.projectSandboxObject(copy)
				require.NoError(t, err)
				assert.Equal(t, sandboxroute.EventResultApplied, manager.proxy.SetRoute(t.Context(), route).Result)
			},
			expectID: "team-a--deleting",
		},
		{
			name: "selector exclusion is authoritative absence",
			sandbox: func() *agentsv1alpha1.Sandbox {
				sandbox := newManagerRouteTestSandbox("team-a", "excluded")
				sandbox.Labels["env"] = "dev"
				return sandbox
			}(),
			seed: func(t *testing.T, manager *SandboxManager, sandbox *agentsv1alpha1.Sandbox) {
				copy := sandbox.DeepCopy()
				copy.Labels["env"] = "prod"
				route, err := manager.projectSandboxObject(copy)
				require.NoError(t, err)
				assert.Equal(t, sandboxroute.EventResultApplied, manager.proxy.SetRoute(t.Context(), route).Result)
			},
			expectID: "team-a--excluded",
		},
		{
			name:     "not found drains only legacy ID-only fallback",
			sandbox:  newManagerRouteTestSandbox("team-a", "missing"),
			notFound: true,
			seed: func(t *testing.T, manager *SandboxManager, sandbox *agentsv1alpha1.Sandbox) {
				result := manager.proxy.SetRoute(t.Context(), sandboxroute.Route{
					ID:              sandboxid.Legacy(sandbox.Namespace, sandbox.Name),
					UID:             sandbox.UID,
					ResourceVersion: sandbox.ResourceVersion,
				})
				assert.Equal(t, sandboxroute.EventResultApplied, result.Result)
			},
			expectID: "team-a--missing",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			manager := newRouteTestManager(t)
			if tt.seed != nil {
				tt.seed(t, manager, tt.sandbox)
			}
			_, err := manager.reconcileSandboxRoute(t.Context(), tt.sandbox, tt.notFound)
			require.NoError(t, err)

			route, present := manager.proxy.LoadRoute(tt.expectID)
			assert.Equal(t, tt.expectPresent, present)
			if tt.expectPresent {
				assert.Equal(t, tt.sandbox.Namespace, route.Namespace)
				assert.Equal(t, tt.sandbox.Name, route.Name)
				assert.Equal(t, tt.sandbox.UID, route.UID)
				assert.Equal(t, "owner-a", route.Owner)
				assert.Equal(t, "secret-token", route.AccessToken)
			}
		})
	}
}

type managerRouteReader struct {
	sandbox *agentsv1alpha1.Sandbox
	err     error
}

func (r managerRouteReader) Get(_ context.Context, key client.ObjectKey, object client.Object, _ ...client.GetOption) error {
	if r.err != nil {
		return r.err
	}
	if r.sandbox == nil {
		return apierrors.NewNotFound(schema.GroupResource{Group: agentsv1alpha1.GroupVersion.Group, Resource: "sandboxes"}, key.Name)
	}
	target, ok := object.(*agentsv1alpha1.Sandbox)
	if !ok {
		return errors.New("unexpected object type")
	}
	*target = *r.sandbox.DeepCopy()
	return nil
}

func (r managerRouteReader) List(context.Context, client.ObjectList, ...client.ListOption) error {
	return errors.New("unexpected list")
}

func TestSandboxManagerObserveRoute(t *testing.T) {
	readErr := errors.New("direct read failed")
	tests := []struct {
		name          string
		reader        client.Reader
		expectPresent bool
		expectError   string
	}{
		{name: "present included", reader: managerRouteReader{sandbox: newManagerRouteTestSandbox("team-a", "observed")}, expectPresent: true},
		{name: "not found is absence", reader: managerRouteReader{}},
		{name: "deleting is absence", reader: managerRouteReader{sandbox: func() *agentsv1alpha1.Sandbox {
			sandbox := newManagerRouteTestSandbox("team-a", "deleting")
			now := metav1.Now()
			sandbox.DeletionTimestamp = &now
			return sandbox
		}()}},
		{name: "namespace exclusion is absence", reader: managerRouteReader{sandbox: newManagerRouteTestSandbox("team-b", "excluded")}},
		{name: "selector exclusion is absence", reader: managerRouteReader{sandbox: func() *agentsv1alpha1.Sandbox {
			sandbox := newManagerRouteTestSandbox("team-a", "excluded")
			sandbox.Labels["env"] = "dev"
			return sandbox
		}()}},
		{name: "get error is classified", reader: managerRouteReader{err: readErr}, expectError: readErr.Error()},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			manager := newRouteTestManager(t)
			observation, err := manager.observeRoute(tt.reader)(t.Context(), types.NamespacedName{Namespace: "team-a", Name: "observed"})
			if tt.expectError != "" {
				require.Error(t, err)
				assert.Contains(t, err.Error(), tt.expectError)
				assert.ErrorIs(t, err, readErr)
				return
			}
			require.NoError(t, err)
			assert.Equal(t, tt.expectPresent, observation.Present)
			if tt.expectPresent {
				assert.Equal(t, "team-a", observation.Route.Namespace)
				assert.Equal(t, "observed", observation.Route.Name)
			}
		})
	}
}

func TestSandboxManagerBuilderForwardsRouteRepairRequests(t *testing.T) {
	tests := []struct {
		name          string
		routes        []sandboxroute.Route
		expectResults []sandboxroute.EventResult
		expectPending int
	}{
		{
			name: "ID collision enqueues both authoritative object keys",
			routes: []sandboxroute.Route{
				{ID: "shared-id", Namespace: "team-a", Name: "sandbox-a", UID: "uid-a", ResourceVersion: "10"},
				{ID: "shared-id", Namespace: "team-a", Name: "sandbox-b", UID: "uid-b", ResourceVersion: "11"},
			},
			expectResults: []sandboxroute.EventResult{sandboxroute.EventResultApplied, sandboxroute.EventResultCollision},
			expectPending: 2,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			opts := config.InitOptions(config.SandboxManagerOptions{})
			managerCache, apiReader, err := cachetest.NewTestCacheWithOptions(t, infracache.Options{SandboxIDResolver: sandboxid.Resolve})
			require.NoError(t, err)

			manager, err := NewSandboxManagerBuilder(opts).
				WithCustomInfra(func() (infra.Builder, error) {
					return sandboxcr.NewInfraBuilder(opts).
						WithCache(managerCache).
						WithAPIReader(apiReader), nil
				}).
				Build()
			require.NoError(t, err)
			require.NotNil(t, manager.routeRepairer)

			for i, route := range tt.routes {
				result := manager.proxy.SetRoute(t.Context(), route)
				assert.Equal(t, tt.expectResults[i], result.Result)
			}
			assert.Equal(t, tt.expectPending, manager.routeRepairer.Pending())
		})
	}
}
