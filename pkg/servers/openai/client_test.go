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

package openai

import (
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestSessionClientRetrieve(t *testing.T) {
	const sessionID = "sess_retrieve_1"
	tests := []struct {
		name       string
		status     int
		body       any
		wantErr    error
		wantStatus string
	}{
		{
			name:   "ok",
			status: http.StatusOK,
			body: map[string]any{
				"id":     sessionID,
				"status": "action_required",
			},
			wantStatus: "action_required",
		},
		{
			name:    "not found",
			status:  http.StatusNotFound,
			wantErr: errSessionNotFound,
		},
		{
			name:   "server error is not not-found",
			status: http.StatusInternalServerError,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				assert.Equal(t, http.MethodGet, r.Method)
				assert.Equal(t, "/v1/agents/sessions/"+sessionID, r.URL.Path)
				assert.Equal(t, "agents=v1", r.Header.Get("OpenAI-Beta"))
				assert.Equal(t, "Bearer sk-test", r.Header.Get("Authorization"))
				w.WriteHeader(tt.status)
				if tt.body != nil {
					_ = json.NewEncoder(w).Encode(tt.body)
				}
			}))
			t.Cleanup(srv.Close)

			got, err := newSessionClient(srv.URL, "sk-test", 0).Retrieve(t.Context(), sessionID)
			if tt.wantErr != nil {
				require.ErrorIs(t, err, tt.wantErr)
				assert.Nil(t, got)
				return
			}
			if tt.status >= 300 {
				require.Error(t, err)
				assert.False(t, errors.Is(err, errSessionNotFound))
				assert.Nil(t, got)
				return
			}
			require.NoError(t, err)
			require.NotNil(t, got)
			assert.Equal(t, tt.wantStatus, got.Status)
		})
	}
}
