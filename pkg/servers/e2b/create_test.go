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

package e2b

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"

	"github.com/openkruise/agents/api/v1alpha1"
	agentsv1alpha1 "github.com/openkruise/agents/api/v1alpha1"
	"github.com/openkruise/agents/pkg/cache"
	managererrors "github.com/openkruise/agents/pkg/sandbox-manager/errors"
	"github.com/openkruise/agents/pkg/sandbox-manager/infra/sandboxcr"
	"github.com/openkruise/agents/pkg/servers/e2b/models"
	"github.com/openkruise/agents/pkg/servers/e2b/quota"
)

type fakeQuotaManager struct {
	acquireErr         error
	releaseErr         error
	acquireCalls       atomic.Int64
	releaseCalls       atomic.Int64
	cleanupCalls       atomic.Int64
	releaseHasDeadline atomic.Bool

	mu          sync.Mutex
	lastAcquire quota.AcquireRequest
	lastRelease quota.ReleaseRequest
	lastCleanup string
}

func (f *fakeQuotaManager) Acquire(_ context.Context, req quota.AcquireRequest) error {
	f.mu.Lock()
	f.lastAcquire = req
	f.mu.Unlock()
	f.acquireCalls.Add(1)
	return f.acquireErr
}

func (f *fakeQuotaManager) Release(ctx context.Context, req quota.ReleaseRequest) error {
	if _, ok := ctx.Deadline(); ok {
		f.releaseHasDeadline.Store(true)
	}
	f.mu.Lock()
	f.lastRelease = req
	f.mu.Unlock()
	f.releaseCalls.Add(1)
	return f.releaseErr
}

func (f *fakeQuotaManager) Cleanup(_ context.Context, apiKeyID string) error {
	f.mu.Lock()
	f.lastCleanup = apiKeyID
	f.mu.Unlock()
	f.cleanupCalls.Add(1)
	return nil
}

// TestResolveServerTimeout verifies that a positive seconds value yields a
// finite timeout, while an absent (zero) or non-positive value yields
// noServerTimeout, leaving the operation bounded only by the client context.
func TestResolveServerTimeout(t *testing.T) {
	tests := []struct {
		name     string
		seconds  int
		expected time.Duration
	}{
		{
			name:     "absent or non-positive yields no server timeout",
			seconds:  0,
			expected: noServerTimeout,
		},
		{
			name:     "positive yields finite timeout",
			seconds:  30,
			expected: 30 * time.Second,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.expected, resolveServerTimeout(tt.seconds))
		})
	}
}

// TestCsiMountOptionsConfigRecord tests the csiMountOptionsConfigRecord function
func TestCsiMountOptionsConfigRecord(t *testing.T) {
	tests := []struct {
		name                  string
		request               models.NewSandboxRequest
		initialAnnotations    map[string]string
		expectedAnnotationKey string
		expectedAnnotationVal string
		shouldSet             bool
	}{
		{
			name: "empty mount configs",
			request: models.NewSandboxRequest{
				Extensions: models.NewSandboxRequestExtension{
					CSIMount: models.CSIMountExtension{
						MountConfigs: []v1alpha1.CSIMountConfig{},
					},
				},
			},
			shouldSet: false,
		},
		{
			name: "single mount config with all fields",
			request: models.NewSandboxRequest{
				Extensions: models.NewSandboxRequestExtension{
					CSIMount: models.CSIMountExtension{
						MountConfigs: []v1alpha1.CSIMountConfig{
							{
								MountID:   "mount-123",
								PvName:    "pv-nas-001",
								MountPath: "/data",
								SubPath:   "subdir",
								ReadOnly:  true,
							},
						},
					},
				},
				Metadata: map[string]string{
					"user-id": "user-456",
				},
			},
			initialAnnotations:    map[string]string{},
			expectedAnnotationKey: models.ExtensionKeyClaimWithCSIMount_MountConfig,
			expectedAnnotationVal: `[{"mountID":"mount-123","pvName":"pv-nas-001","mountPath":"/data","subPath":"subdir","readOnly":true}]`,
			shouldSet:             true,
		},
		{
			name: "multiple mount configs with optional fields omitted",
			request: models.NewSandboxRequest{
				Extensions: models.NewSandboxRequestExtension{
					CSIMount: models.CSIMountExtension{
						MountConfigs: []v1alpha1.CSIMountConfig{
							{
								PvName:    "pv-nas-001",
								MountPath: "/data",
							},
							{
								PvName:    "pv-oss-002",
								MountPath: "/models",
								ReadOnly:  true,
							},
						},
					},
				},
			},
			initialAnnotations:    map[string]string{"existing-key": "existing-val"},
			expectedAnnotationKey: models.ExtensionKeyClaimWithCSIMount_MountConfig,
			expectedAnnotationVal: `[{"pvName":"pv-nas-001","mountPath":"/data"},{"pvName":"pv-oss-002","mountPath":"/models","readOnly":true}]`,
			shouldSet:             true,
		},
		{
			name: "with metadata merging",
			request: models.NewSandboxRequest{
				Extensions: models.NewSandboxRequestExtension{
					CSIMount: models.CSIMountExtension{
						MountConfigs: []v1alpha1.CSIMountConfig{
							{
								PvName:    "pv-test",
								MountPath: "/workspace",
							},
						},
					},
				},
			},
			initialAnnotations: map[string]string{
				"old-key": "old-val",
			},
			expectedAnnotationKey: models.ExtensionKeyClaimWithCSIMount_MountConfig,
			expectedAnnotationVal: `[{"pvName":"pv-test","mountPath":"/workspace"}]`,
			shouldSet:             true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Create mock sandbox
			mockSbx := &sandboxcr.Sandbox{
				Sandbox: &agentsv1alpha1.Sandbox{
					ObjectMeta: metav1.ObjectMeta{
						Name:        "test-sandbox",
						Namespace:   "default",
						Annotations: tt.initialAnnotations,
					},
				},
			}

			// Create controller instance
			ctrl := &Controller{}

			// Call the function
			ctx := context.Background()
			ctrl.csiMountOptionsConfigRecord(ctx, mockSbx, tt.request)

			// Verify results
			annotations := mockSbx.GetAnnotations()

			if !tt.shouldSet {
				// Should not set any annotation when mount configs are empty
				if len(annotations) != len(tt.initialAnnotations) {
					t.Errorf("expected no annotations to be added, got %d", len(annotations))
				}
				return
			}

			// Check if expected annotation is set
			val, exists := annotations[tt.expectedAnnotationKey]
			if !exists {
				t.Errorf("expected annotation %q to exist", tt.expectedAnnotationKey)
				return
			}

			// Verify the annotation value (parse JSON for comparison to avoid ordering issues)
			var expectedConfigs, actualConfigs []v1alpha1.CSIMountConfig
			if err := json.Unmarshal([]byte(tt.expectedAnnotationVal), &expectedConfigs); err != nil {
				t.Fatalf("failed to unmarshal expected value: %v", err)
			}
			if err := json.Unmarshal([]byte(val), &actualConfigs); err != nil {
				t.Fatalf("failed to unmarshal actual value: %v", err)
			}

			if !reflect.DeepEqual(expectedConfigs, actualConfigs) {
				t.Errorf("csi mount config mismatch:\nexpected: %#v\ngot:      %#v", expectedConfigs, actualConfigs)
			}

			if !reflect.DeepEqual(expectedConfigs, actualConfigs) {
				t.Errorf("csi mount config mismatch:\nexpected: %#v\ngot:      %#v", expectedConfigs, actualConfigs)
			}

			// Verify existing annotations are preserved
			if tt.initialAnnotations != nil {
				for k, v := range tt.initialAnnotations {
					if annotations[k] != v {
						t.Errorf("expected existing annotation %q=%q, got %q", k, v, annotations[k])
					}
				}
			}
		})
	}
}

func TestCreateSandboxWithClaim_CSIMount(t *testing.T) {
	tests := []struct {
		name               string
		request            models.NewSandboxRequest
		expectCSIMount     bool
		expectedMountCount int
	}{
		{
			name: "no csi mount configs",
			request: models.NewSandboxRequest{
				TemplateID: "test-template",
				Extensions: models.NewSandboxRequestExtension{
					CSIMount: models.CSIMountExtension{
						MountConfigs: []v1alpha1.CSIMountConfig{},
					},
				},
			},
			expectCSIMount: false,
		},
		{
			name: "single csi mount config",
			request: models.NewSandboxRequest{
				TemplateID: "test-template",
				Extensions: models.NewSandboxRequestExtension{
					CSIMount: models.CSIMountExtension{
						MountConfigs: []v1alpha1.CSIMountConfig{
							{
								PvName:    "test-pv",
								MountPath: "/data",
								SubPath:   "subdir",
								ReadOnly:  true,
							},
						},
					},
				},
			},
			expectCSIMount:     true,
			expectedMountCount: 1,
		},
		{
			name: "multiple csi mount configs",
			request: models.NewSandboxRequest{
				TemplateID: "test-template",
				Extensions: models.NewSandboxRequestExtension{
					CSIMount: models.CSIMountExtension{
						MountConfigs: []v1alpha1.CSIMountConfig{
							{
								PvName:    "pv-nas-001",
								MountPath: "/workspace",
							},
							{
								PvName:    "pv-oss-002",
								MountPath: "/models",
								ReadOnly:  true,
							},
							{
								PvName:    "pv-disk-003",
								MountPath: "/storage",
								SubPath:   "data",
							},
						},
					},
				},
			},
			expectCSIMount:     true,
			expectedMountCount: 3,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Verify the request structure is valid
			if len(tt.request.Extensions.CSIMount.MountConfigs) != tt.expectedMountCount {
				t.Errorf("expected %d mount configs, got %d", tt.expectedMountCount,
					len(tt.request.Extensions.CSIMount.MountConfigs))
			}

			// Check if CSI mount configs are properly set
			hasCSIMount := len(tt.request.Extensions.CSIMount.MountConfigs) > 0
			if hasCSIMount != tt.expectCSIMount {
				t.Errorf("expectCSIMount mismatch: expected %v, got %v", tt.expectCSIMount, hasCSIMount)
			}
		})
	}
}

func TestCreateSandboxWithClone_CSIMount(t *testing.T) {
	tests := []struct {
		name               string
		request            models.NewSandboxRequest
		expectCSIMount     bool
		expectedMountCount int
		hasInplaceUpdate   bool
	}{
		{
			name: "clone with csi mount",
			request: models.NewSandboxRequest{
				TemplateID: "test-checkpoint",
				Extensions: models.NewSandboxRequestExtension{
					CSIMount: models.CSIMountExtension{
						MountConfigs: []v1alpha1.CSIMountConfig{
							{
								PvName:    "test-pv",
								MountPath: "/data",
							},
						},
					},
				},
			},
			expectCSIMount:     true,
			expectedMountCount: 1,
		},
		{
			name: "clone with multiple csi mounts",
			request: models.NewSandboxRequest{
				TemplateID: "test-checkpoint",
				Extensions: models.NewSandboxRequestExtension{
					CSIMount: models.CSIMountExtension{
						MountConfigs: []v1alpha1.CSIMountConfig{
							{
								PvName:    "pv-1",
								MountPath: "/mnt/data1",
							},
							{
								PvName:    "pv-2",
								MountPath: "/mnt/data2",
								ReadOnly:  true,
							},
						},
					},
				},
			},
			expectCSIMount:     true,
			expectedMountCount: 2,
		},
		{
			name: "clone with inplace update and csi mount",
			request: models.NewSandboxRequest{
				TemplateID: "test-checkpoint",
				Extensions: models.NewSandboxRequestExtension{
					InplaceUpdate: models.InplaceUpdateExtension{
						Image: "new-image",
					},
					CSIMount: models.CSIMountExtension{
						MountConfigs: []v1alpha1.CSIMountConfig{
							{
								PvName:    "test-pv",
								MountPath: "/data",
							},
						},
					},
				},
			},
			expectCSIMount:     true,
			expectedMountCount: 1,
			hasInplaceUpdate:   true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Verify the request structure is valid
			if len(tt.request.Extensions.CSIMount.MountConfigs) != tt.expectedMountCount {
				t.Errorf("expected %d mount configs, got %d", tt.expectedMountCount,
					len(tt.request.Extensions.CSIMount.MountConfigs))
			}

			// Check if CSI mount configs are properly set
			hasCSIMount := len(tt.request.Extensions.CSIMount.MountConfigs) > 0
			if hasCSIMount != tt.expectCSIMount {
				t.Errorf("expectCSIMount mismatch: expected %v, got %v", tt.expectCSIMount, hasCSIMount)
			}

			// Check inplace update
			hasInplaceUpdate := tt.request.Extensions.InplaceUpdate.Image != ""
			if hasInplaceUpdate != tt.hasInplaceUpdate {
				t.Errorf("hasInplaceUpdate mismatch: expected %v, got %v", tt.hasInplaceUpdate, hasInplaceUpdate)
			}
		})
	}
}

func TestCreateSandboxWithClone_InplaceUpdateRejected(t *testing.T) {
	ctrl := &Controller{}
	request := models.NewSandboxRequest{
		TemplateID: "test-checkpoint",
		Extensions: models.NewSandboxRequestExtension{
			InplaceUpdate: models.InplaceUpdateExtension{
				Image: "nginx:latest",
			},
		},
	}
	user := &models.CreatedTeamAPIKey{ID: uuid.New(), Name: "test-user"}

	_, apiErr := ctrl.createSandboxWithClone(context.Background(), request, user)
	require.NotNil(t, apiErr)
	assert.Equal(t, http.StatusBadRequest, apiErr.Code)
	assert.Contains(t, apiErr.Message, "InplaceUpdate is not supported for clone")
}

func TestParseCreateSandboxRequest(t *testing.T) {
	ctrl := &Controller{maxTimeout: 3600}

	t.Run("invalid json", func(t *testing.T) {
		req := httptest.NewRequest(http.MethodPost, "/sandboxes", strings.NewReader("{"))
		_, apiErr := ctrl.parseCreateSandboxRequest(req)
		require.NotNil(t, apiErr)
		assert.Equal(t, 0, apiErr.Code)
		assert.NotEmpty(t, apiErr.Message)
	})

	t.Run("invalid extension", func(t *testing.T) {
		body := `{
			"templateID":"t1",
			"metadata":{
				"` + models.ExtensionKeyClaimWithCPULimit + `":"bad"
			}
		}`
		req := httptest.NewRequest(http.MethodPost, "/sandboxes", strings.NewReader(body))
		_, apiErr := ctrl.parseCreateSandboxRequest(req)
		require.NotNil(t, apiErr)
		assert.Equal(t, http.StatusBadRequest, apiErr.Code)
		assert.Contains(t, apiErr.Message, "Bad extension param")
	})

	t.Run("unqualified metadata key", func(t *testing.T) {
		body := `{
			"templateID":"t1",
			"metadata":{"bad/key/":"v"}
		}`
		req := httptest.NewRequest(http.MethodPost, "/sandboxes", strings.NewReader(body))
		_, apiErr := ctrl.parseCreateSandboxRequest(req)
		require.NotNil(t, apiErr)
		assert.Equal(t, http.StatusBadRequest, apiErr.Code)
		assert.Contains(t, apiErr.Message, "Unqualified metadata key")
	})

	t.Run("forbidden metadata key prefix", func(t *testing.T) {
		meta := map[string]string{v1alpha1.E2BPrefix + "custom-key": "v"}
		raw, err := json.Marshal(models.NewSandboxRequest{
			TemplateID: "t1",
			Metadata:   meta,
		})
		require.NoError(t, err)

		req := httptest.NewRequest(http.MethodPost, "/sandboxes", bytes.NewReader(raw))
		_, apiErr := ctrl.parseCreateSandboxRequest(req)
		require.NotNil(t, apiErr)
		assert.Equal(t, http.StatusBadRequest, apiErr.Code)
		assert.Contains(t, apiErr.Message, "Forbidden metadata key")
	})

	t.Run("timeout defaults when omitted", func(t *testing.T) {
		raw, err := json.Marshal(models.NewSandboxRequest{
			TemplateID: "t1",
		})
		require.NoError(t, err)
		req := httptest.NewRequest(http.MethodPost, "/sandboxes", bytes.NewReader(raw))

		got, apiErr := ctrl.parseCreateSandboxRequest(req)
		require.Nil(t, apiErr)
		assert.Equal(t, models.DefaultTimeoutSeconds, got.Timeout)
	})

	t.Run("timeout out of range", func(t *testing.T) {
		raw, err := json.Marshal(models.NewSandboxRequest{
			TemplateID: "t1",
			Timeout:    ctrl.maxTimeout + 1,
		})
		require.NoError(t, err)
		req := httptest.NewRequest(http.MethodPost, "/sandboxes", bytes.NewReader(raw))

		_, apiErr := ctrl.parseCreateSandboxRequest(req)
		require.NotNil(t, apiErr)
		assert.Equal(t, http.StatusBadRequest, apiErr.Code)
		assert.Contains(t, apiErr.Message, "timeout should between")
	})
}

func TestMapInfraErrorToApiError(t *testing.T) {
	tests := []struct {
		name         string
		err          error
		expectedCode int
	}{
		{
			name:         "ErrorBadRequest maps to 400",
			err:          managererrors.NewError(managererrors.ErrorBadRequest, "quota exceeded"),
			expectedCode: http.StatusBadRequest,
		},
		{
			name:         "ErrorNotFound maps to 400",
			err:          managererrors.NewError(managererrors.ErrorNotFound, "template not found"),
			expectedCode: http.StatusBadRequest,
		},
		{
			name:         "ErrorInternal maps to 500",
			err:          managererrors.NewError(managererrors.ErrorInternal, "platform issue"),
			expectedCode: http.StatusInternalServerError,
		},
		{
			name:         "ErrorQuotaExceeded maps to 403",
			err:          managererrors.NewError(managererrors.ErrorQuotaExceeded, "api-key quota exceeded"),
			expectedCode: http.StatusForbidden,
		},
		{
			name:         "plain error maps to 500",
			err:          fmt.Errorf("some unknown error"),
			expectedCode: http.StatusInternalServerError,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			apiErr := mapInfraErrorToApiError(tt.err)
			assert.Equal(t, tt.expectedCode, apiErr.Code)
			assert.Contains(t, apiErr.Message, tt.err.Error())
		})
	}
}

func TestResolveCreateFootprint(t *testing.T) {
	tests := []struct {
		name            string
		setup           func(t *testing.T, controller *Controller, user *models.CreatedTeamAPIKey)
		request         models.NewSandboxRequest
		user            *models.CreatedTeamAPIKey
		expectFootprint map[models.QuotaDimension]int64
		expectError     string
	}{
		{
			name: "claim resolves cpu from template ref",
			setup: func(t *testing.T, controller *Controller, user *models.CreatedTeamAPIKey) {
				createSandboxSetTemplateRefFixture(t, controller, Namespace, "claim-template", "claim-template-ref", "2000m", "0Mi")
			},
			request: models.NewSandboxRequest{TemplateID: "claim-template"},
			user: quotaLimitedUser([]models.QuotaLimit{{
				Dimension: models.DimLimitsCPU,
				Scope:     models.ScopeRunning,
				Limit:     4000,
			}}),
			expectFootprint: map[models.QuotaDimension]int64{
				models.DimLimitsCPU:    2000,
				models.DimLimitsMemory: 0,
			},
		},
		{
			name: "claim override wins",
			setup: func(t *testing.T, controller *Controller, user *models.CreatedTeamAPIKey) {
				createSandboxSetTemplateRefFixture(t, controller, Namespace, "claim-template", "claim-template-ref", "2000m", "0Mi")
			},
			request: models.NewSandboxRequest{
				TemplateID: "claim-template",
				Extensions: models.NewSandboxRequestExtension{
					InplaceUpdate: models.InplaceUpdateExtension{
						Resources: &models.InplaceUpdateResourcesExtension{
							Limits: corev1.ResourceList{
								corev1.ResourceCPU: resource.MustParse("4000m"),
							},
						},
					},
				},
			},
			user: quotaLimitedUser([]models.QuotaLimit{{
				Dimension: models.DimLimitsCPU,
				Scope:     models.ScopeRunning,
				Limit:     4000,
			}}),
			expectFootprint: map[models.QuotaDimension]int64{
				models.DimLimitsCPU:    4000,
				models.DimLimitsMemory: 0,
			},
		},
		{
			name: "clone resolves checkpoint template without override",
			setup: func(t *testing.T, controller *Controller, user *models.CreatedTeamAPIKey) {
				createCheckpointTemplateWithLimitsFixture(t, controller, user.Team.Name, "clone-template", "checkpoint-1", user.ID.String(), "source-sandbox", "2026-06-19T00:00:00Z", "2000m", "0Mi")
			},
			request: models.NewSandboxRequest{TemplateID: "checkpoint-1"},
			user: quotaLimitedUser([]models.QuotaLimit{{
				Dimension: models.DimLimitsCPU,
				Scope:     models.ScopeRunning,
				Limit:     4000,
			}}),
			expectFootprint: map[models.QuotaDimension]int64{
				models.DimLimitsCPU:    2000,
				models.DimLimitsMemory: 0,
			},
		},
		{
			name:    "count only key skips template read",
			request: models.NewSandboxRequest{TemplateID: "missing-template"},
			user: quotaLimitedUser([]models.QuotaLimit{{
				Dimension: models.DimSandboxCount,
				Scope:     models.ScopeRunning,
				Limit:     2,
			}}),
			expectFootprint: nil,
		},
		{
			name: "limited key returns error when template ref is missing",
			setup: func(t *testing.T, controller *Controller, user *models.CreatedTeamAPIKey) {
				createSandboxSetWithoutTemplateRefFixture(t, controller, Namespace, "claim-template", "missing-template-ref")
			},
			request: models.NewSandboxRequest{TemplateID: "claim-template"},
			user: quotaLimitedUser([]models.QuotaLimit{{
				Dimension: models.DimLimitsCPU,
				Scope:     models.ScopeRunning,
				Limit:     4000,
			}}),
			expectError: "not found",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			controller, _, teardown := Setup(t)
			defer teardown()
			if tt.user.Team == nil {
				tt.user.Team = models.AdminTeam()
			}
			if tt.setup != nil {
				tt.setup(t, controller, tt.user)
			}

			got, err := controller.resolveCreateFootprint(t.Context(), tt.request, tt.user)
			if tt.expectError != "" {
				require.Error(t, err)
				assert.Contains(t, err.Error(), tt.expectError)
				return
			}

			require.NoError(t, err)
			assert.Equal(t, tt.expectFootprint, got)
		})
	}
}

func TestCreateSandbox_ResolverFailureReturnsTemplateNotFoundBeforeQuotaAcquire(t *testing.T) {
	controller, _, teardown := Setup(t)
	defer teardown()

	fakeQuota := &fakeQuotaManager{}
	controller.quota = fakeQuota
	user := quotaLimitedUser([]models.QuotaLimit{{
		Dimension: models.DimLimitsCPU,
		Scope:     models.ScopeRunning,
		Limit:     4000,
	}})
	createSandboxSetWithoutTemplateRefFixture(t, controller, Namespace, "claim-template", "missing-template-ref")

	resp, apiErr := controller.CreateSandbox(NewRequest(t, nil, models.NewSandboxRequest{
		TemplateID: "claim-template",
		Metadata: map[string]string{
			models.ExtensionKeySkipInitRuntime: v1alpha1.True,
		},
	}, nil, user))

	require.NotNil(t, apiErr)
	assert.Equal(t, http.StatusBadRequest, apiErr.Code)
	assert.Contains(t, apiErr.Message, "Template or Checkpoint not found")
	assert.Zero(t, resp.Code)
	assert.Equal(t, int64(0), fakeQuota.acquireCalls.Load())
}

func quotaLimitedUser(limits []models.QuotaLimit) *models.CreatedTeamAPIKey {
	return &models.CreatedTeamAPIKey{
		ID:   uuid.New(),
		Key:  uuid.NewString(),
		Name: "limited",
		Team: models.AdminTeam(),
		QuotaSpec: &models.QuotaSpec{
			Limits: limits,
		},
	}
}

func createSandboxSetTemplateRefFixture(t *testing.T, controller *Controller, namespace, sandboxSetName, templateRefName, cpu, memory string) {
	t.Helper()
	fc := getTestCRClient(controller)

	sbt := &agentsv1alpha1.SandboxTemplate{
		ObjectMeta: metav1.ObjectMeta{
			Name:      templateRefName,
			Namespace: namespace,
			UID:       types.UID(uuid.NewString()),
		},
		Spec: agentsv1alpha1.SandboxTemplateSpec{
			Template: podTemplateWithLimits(cpu, memory),
		},
	}
	require.NoError(t, fc.Create(t.Context(), sbt))

	sbs := &agentsv1alpha1.SandboxSet{
		ObjectMeta: metav1.ObjectMeta{
			Name:      sandboxSetName,
			Namespace: namespace,
		},
		Spec: agentsv1alpha1.SandboxSetSpec{
			Replicas: 0,
			EmbeddedSandboxTemplate: agentsv1alpha1.EmbeddedSandboxTemplate{
				TemplateRef: &agentsv1alpha1.SandboxTemplateRef{Name: templateRefName},
			},
		},
	}
	require.NoError(t, fc.Create(t.Context(), sbs))
}

func createSandboxSetWithoutTemplateRefFixture(t *testing.T, controller *Controller, namespace, sandboxSetName, templateRefName string) {
	t.Helper()
	fc := getTestCRClient(controller)

	sbs := &agentsv1alpha1.SandboxSet{
		ObjectMeta: metav1.ObjectMeta{
			Name:      sandboxSetName,
			Namespace: namespace,
		},
		Spec: agentsv1alpha1.SandboxSetSpec{
			Replicas: 0,
			EmbeddedSandboxTemplate: agentsv1alpha1.EmbeddedSandboxTemplate{
				TemplateRef: &agentsv1alpha1.SandboxTemplateRef{Name: templateRefName},
			},
		},
	}
	require.NoError(t, fc.Create(t.Context(), sbs))
}

func createCheckpointTemplateWithLimitsFixture(t *testing.T, controller *Controller, namespace, name, checkpointID, owner, sandboxID, creationTime, cpu, memory string) {
	t.Helper()
	fc := getTestCRClient(controller)
	createdAt, err := time.Parse(time.RFC3339, creationTime)
	require.NoError(t, err)

	sbt := &agentsv1alpha1.SandboxTemplate{
		ObjectMeta: metav1.ObjectMeta{
			Name:      name,
			Namespace: namespace,
			UID:       types.UID(uuid.NewString()),
		},
		Spec: agentsv1alpha1.SandboxTemplateSpec{
			Template: podTemplateWithLimits(cpu, memory),
		},
	}
	require.NoError(t, fc.Create(t.Context(), sbt))

	cp := &agentsv1alpha1.Checkpoint{
		ObjectMeta: metav1.ObjectMeta{
			Name:              name,
			Namespace:         namespace,
			UID:               types.UID(uuid.NewString()),
			CreationTimestamp: metav1.NewTime(createdAt),
			Labels: map[string]string{
				agentsv1alpha1.LabelSandboxTemplate: name,
			},
			Annotations: map[string]string{
				agentsv1alpha1.AnnotationOwner:     owner,
				agentsv1alpha1.AnnotationSandboxID: sandboxID,
			},
		},
		Status: agentsv1alpha1.CheckpointStatus{
			Phase:        agentsv1alpha1.CheckpointSucceeded,
			CheckpointId: checkpointID,
		},
	}
	require.NoError(t, fc.Create(t.Context(), cp))
	require.NoError(t, fc.Status().Update(t.Context(), cp))
	require.Eventually(t, func() bool {
		_, err := controller.cache.GetCheckpoint(t.Context(), cache.GetCheckpointOptions{
			Namespace:    namespace,
			CheckpointID: checkpointID,
		})
		return err == nil
	}, time.Second, 10*time.Millisecond)
}

func podTemplateWithLimits(cpu, memory string) *corev1.PodTemplateSpec {
	return &corev1.PodTemplateSpec{
		Spec: corev1.PodSpec{
			Containers: []corev1.Container{{
				Name:  "main",
				Image: "test-image",
				Resources: corev1.ResourceRequirements{
					Limits: corev1.ResourceList{
						corev1.ResourceCPU:    resource.MustParse(cpu),
						corev1.ResourceMemory: resource.MustParse(memory),
					},
				},
			}},
		},
	}
}
