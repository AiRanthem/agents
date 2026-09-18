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
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"sigs.k8s.io/controller-runtime/pkg/client"

	"github.com/openkruise/agents/api/v1alpha1"
	"github.com/openkruise/agents/pkg/cache/cachetest"
	"github.com/openkruise/agents/pkg/proxy"
	sandboxmanager "github.com/openkruise/agents/pkg/sandbox-manager"
	"github.com/openkruise/agents/pkg/sandbox-manager/config"
	"github.com/openkruise/agents/pkg/sandbox-manager/infra"
	"github.com/openkruise/agents/pkg/sandbox-manager/infra/sandboxcr"
)

// TestWebhookActivatePersistsSessionClaim covers the OpenAI webhook happy path:
// signed action_required is accepted after the session SandboxClaim is persisted.
func TestWebhookActivatePersistsSessionClaim(t *testing.T) {
	const (
		signingSecret = "test-webhook-secret"
		sessionID     = "sess_integration_1"
		template      = "openai-session"
		namespace     = "default"
		envID         = "env_123"
		remoteURL     = "wss://api.openai.com/v1/beta/agents/sessions/sess_integration_1"
	)

	openaiAPI := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/beta/agents/sessions/"+sessionID {
			http.NotFound(w, r)
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]any{
			"id":     sessionID,
			"status": "action_required",
			"required_action": map[string]any{
				"type": actionEnvironmentConnection,
			},
			"environment": map[string]any{
				"id":         envID,
				"remote_url": remoteURL,
			},
		})
	}))
	t.Cleanup(openaiAPI.Close)

	opts := config.InitOptions(config.SandboxManagerOptions{})
	cache, fc, err := cachetest.NewTestCache(t)
	require.NoError(t, err)
	proxyServer := proxy.NewServer(opts)
	manager, err := sandboxmanager.NewSandboxManagerBuilder(opts).
		WithCustomInfra(func() (infra.Builder, error) {
			return sandboxcr.NewInfraBuilder(opts).
				WithCache(cache).
				WithAPIReader(fc).
				WithRouteReader(proxyServer), nil
		}).
		Build()
	require.NoError(t, err)

	require.NoError(t, fc.Create(t.Context(), &v1alpha1.SandboxSet{
		ObjectMeta: metav1.ObjectMeta{Name: template, Namespace: namespace},
	}))

	c := NewController(ControllerOptions{
		Manager:       manager,
		SigningSecret: signingSecret,
		APIKey:        "sk-test",
		BaseURL:       openaiAPI.URL,
		Namespace:     namespace,
		Template:      template,
		InitCommand:   []string{"/usr/local/bin/connect-openai"},
		ClaimTimeout:  200 * time.Millisecond,
	})

	body := []byte(`{"id":"evt_1","type":"agent.session.action_required","data":{"id":"` + sessionID + `","required_action":{"type":"environment_connection"}}}`)

	bad := httptest.NewRequest(http.MethodPost, "/webhooks", strings.NewReader(string(body)))
	badRec := httptest.NewRecorder()
	c.mux.ServeHTTP(badRec, bad)
	assert.Equal(t, http.StatusBadRequest, badRec.Code)

	req := httptest.NewRequest(http.MethodPost, "/webhooks", strings.NewReader(string(body)))
	signWebhook(req, signingSecret, "msg_1", body)
	rec := httptest.NewRecorder()
	c.mux.ServeHTTP(rec, req)
	require.Equal(t, http.StatusOK, rec.Code, rec.Body.String())

	list := &v1alpha1.SandboxClaimList{}
	require.NoError(t, fc.List(t.Context(), list, client.InNamespace(namespace)))
	require.Len(t, list.Items, 1)
	claim := list.Items[0]
	assert.Equal(t, v1alpha1.True, claim.Labels[v1alpha1.LabelSandboxSession])
	assert.Equal(t, sessionID, claim.Annotations[v1alpha1.AnnotationSandboxSessionID])
	assert.Equal(t, template, claim.Spec.TemplateName)
	require.NotNil(t, claim.Spec.PostClaim)
	require.NotNil(t, claim.Spec.PostClaim.Run)
	assert.Equal(t, []string{"/usr/local/bin/connect-openai", envID, remoteURL}, claim.Spec.PostClaim.Run.Command)
}

func signWebhook(req *http.Request, secret, id string, body []byte) {
	ts := strconv.FormatInt(time.Now().Unix(), 10)
	mac := hmac.New(sha256.New, []byte(secret))
	_, _ = mac.Write([]byte(id + "." + ts + "."))
	_, _ = mac.Write(body)
	req.Header.Set(headerWebhookID, id)
	req.Header.Set(headerWebhookTimestamp, ts)
	req.Header.Set(headerWebhookSignature, "v1,"+base64.StdEncoding.EncodeToString(mac.Sum(nil)))
}
