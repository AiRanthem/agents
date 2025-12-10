package e2b

import (
	"testing"

	"github.com/openkruise/agents/pkg/servers/e2b/keys"
	"github.com/openkruise/agents/pkg/servers/e2b/models"
	"github.com/openkruise/agents/pkg/servers/web"
	"github.com/stretchr/testify/assert"
)

func TestListSandboxes(t *testing.T) {
	templateName := "test-template"
	controller, client, teardown := Setup(t)
	defer teardown()
	tests := []struct {
		name           string
		createRequests []models.NewSandboxRequest
		queryParams    map[string]string
		expectListed   func(sandbox *models.Sandbox) bool
		expectError    *web.ApiError
	}{
		{
			name: "list by metadata",
			createRequests: []models.NewSandboxRequest{
				{
					TemplateID: templateName,
					Metadata: map[string]string{
						"testKey": "value1",
					},
				},
				{
					TemplateID: templateName,
					Metadata: map[string]string{
						"testKey": "value2",
					},
				},
			},
			queryParams: map[string]string{
				"metadata": "testKey=value1",
			},
			expectListed: func(sbx *models.Sandbox) bool {
				return sbx.Metadata["testKey"] == "value1"
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cleanup := CreateSandboxPool(t, client.SandboxClient, templateName, 10)
			defer cleanup()

			user := &models.CreatedTeamAPIKey{
				ID:   keys.AdminKeyID,
				Key:  InitKey,
				Name: "admin",
			}

			var expectedListed []models.Sandbox
			for _, request := range tt.createRequests {
				resp, apiError := controller.CreateSandbox(NewRequest(t, nil, request, user))
				assert.Nil(t, apiError)
				sandbox := resp.Body
				if apiError == nil && tt.expectListed(sandbox) {
					expectedListed = append(expectedListed, *sandbox)
				}
			}

			resp, apiError := controller.ListSandboxes(NewRequest(t, tt.queryParams, nil, user))
			if apiError != nil {
				t.Errorf("ListSandboxes() error = %v", apiError)
				return
			}

			if tt.expectError != nil {
				assert.NotNil(t, apiError)
				if apiError != nil {
					assert.Equal(t, tt.expectError.Code, apiError.Code)
					assert.Equal(t, tt.expectError.Message, apiError.Message)
				}
			} else {
				assert.Nil(t, apiError)
				list := resp.Body
				var gotListed []models.Sandbox
				for _, sandbox := range list {
					gotListed = append(gotListed, *sandbox)
				}
				assert.ElementsMatch(t, expectedListed, gotListed)
			}
		})
	}
}
