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
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

const defaultOpenAIBaseURL = "https://api.openai.com"

var errSessionNotFound = errors.New("openai session not found")

type sessionClient struct {
	baseURL    string
	apiKey     string
	httpClient *http.Client
}

type agentSession struct {
	ID              string             `json:"id"`
	Status          string             `json:"status"`
	Environment     sessionEnvironment `json:"environment"`
	RequiredActions []requiredAction   `json:"required_actions"`
	RequiredAction  *requiredAction    `json:"required_action"`
}

type sessionEnvironment struct {
	ID        string `json:"id"`
	Type      string `json:"type"`
	RemoteURL string `json:"remote_url"`
}

type requiredAction struct {
	Type          string `json:"type"`
	EnvironmentID string `json:"environment_id"`
}

func newSessionClient(baseURL, apiKey string, timeout time.Duration) *sessionClient {
	if baseURL == "" {
		baseURL = defaultOpenAIBaseURL
	}
	if timeout <= 0 {
		timeout = 10 * time.Second
	}
	return &sessionClient{
		baseURL: strings.TrimRight(baseURL, "/"),
		apiKey:  apiKey,
		httpClient: &http.Client{
			Timeout: timeout,
		},
	}
}

func (c *sessionClient) Retrieve(ctx context.Context, sessionID string) (*agentSession, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.baseURL+"/v1/beta/agents/sessions/"+sessionID, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+c.apiKey)
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return nil, err
	}
	if resp.StatusCode == http.StatusNotFound {
		return nil, errSessionNotFound
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("openai retrieve session: status %d", resp.StatusCode)
	}
	session := &agentSession{}
	if err := json.Unmarshal(body, session); err != nil {
		return nil, err
	}
	return session, nil
}

func (s *agentSession) needsEnvironmentConnection() bool {
	if s == nil {
		return false
	}
	if s.RequiredAction != nil && s.RequiredAction.Type == actionEnvironmentConnection {
		return true
	}
	for _, action := range s.RequiredActions {
		if action.Type == actionEnvironmentConnection {
			return true
		}
	}
	return false
}
