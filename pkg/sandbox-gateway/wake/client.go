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

package wake

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"path"
	"strings"
	"time"
)

const (
	apiKeyHeader           = "X-API-KEY"
	DetachedContextTimeout = 12 * time.Minute
)

type ConnectClient struct {
	baseURL      *url.URL
	apiAuthority string
	systemKey    string
	httpClient   *http.Client
}

func NewConnectClient(baseURL string, systemKey string, httpClient *http.Client) (*ConnectClient, error) {
	parsed, err := url.Parse(strings.TrimRight(baseURL, "/"))
	if err != nil {
		return nil, fmt.Errorf("parse manager base URL: %w", err)
	}
	if parsed.Scheme == "" || parsed.Host == "" {
		return nil, fmt.Errorf("manager base URL must include scheme and host")
	}
	if httpClient == nil {
		httpClient = http.DefaultClient
	}
	return &ConnectClient{
		baseURL:      parsed,
		apiAuthority: managerAPIAuthority(parsed.Host),
		systemKey:    systemKey,
		httpClient:   httpClient,
	}, nil
}

func (c *ConnectClient) Connect(ctx context.Context, sandboxID string, timeoutSeconds int) (int, error) {
	body, err := json.Marshal(struct {
		Timeout int `json:"timeout"`
	}{Timeout: timeoutSeconds})
	if err != nil {
		return 0, fmt.Errorf("marshal connect request: %w", err)
	}

	u := *c.baseURL
	u.Path = path.Join(c.baseURL.Path, "sandboxes", sandboxID, "connect")
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, u.String(), bytes.NewReader(body))
	if err != nil {
		return 0, fmt.Errorf("build connect request: %w", err)
	}
	req.Host = c.apiAuthority
	req.Header.Set(apiKeyHeader, c.systemKey)
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return 0, err
	}
	defer resp.Body.Close()
	_, _ = io.Copy(io.Discard, resp.Body)
	return resp.StatusCode, nil
}

func managerAPIAuthority(host string) string {
	if strings.HasPrefix(host, "api.") {
		return host
	}
	return "api." + host
}
