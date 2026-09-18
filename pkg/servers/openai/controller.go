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
	"net"
	"net/http"
	"sync"
	"time"

	"golang.org/x/time/rate"
	"k8s.io/klog/v2"

	sandboxmanager "github.com/openkruise/agents/pkg/sandbox-manager"
	managererrors "github.com/openkruise/agents/pkg/sandbox-manager/errors"
	"github.com/openkruise/agents/pkg/sandbox-manager/infra"
	"github.com/openkruise/agents/pkg/sandbox-manager/logs"
	"github.com/openkruise/agents/pkg/utils/network"
)

const (
	eventActionRequired = "agent.session.action_required"
	eventInProgress     = "agent.session.in_progress"
	eventIdle           = "agent.session.idle"
	eventFailed         = "agent.session.failed"

	actionEnvironmentConnection = "environment_connection"

	defaultAcceptWait      = 8 * time.Second
	maxWebhookBodyBytes    = 1 << 20
	defaultWebhookQPS      = 20
	defaultCleanupInterval = time.Minute
)

type webhookEvent struct {
	ID   string          `json:"id"`
	Type string          `json:"type"`
	Data json.RawMessage `json:"data"`
}

type webhookSessionData struct {
	ID             string          `json:"id"`
	RequiredAction *requiredAction `json:"required_action"`
}

type Controller struct {
	manager         *sandboxmanager.SandboxManager
	client          *sessionClient
	signingSecret   string
	namespace       string
	template        string
	initCommand     []string
	claimTimeout    time.Duration
	pauseAfter      time.Duration
	shutdownAfter   time.Duration
	limiter         *rate.Limiter
	cleanupInterval time.Duration
	acceptWait      time.Duration

	mux     *http.ServeMux
	server  *http.Server
	ready   bool
	lifeCtx context.Context
	cancel  context.CancelFunc
	wg      sync.WaitGroup
}

type ControllerOptions struct {
	Port            int
	BindAddress     string
	Manager         *sandboxmanager.SandboxManager
	SigningSecret   string
	APIKey          string
	BaseURL         string
	Namespace       string
	Template        string
	InitCommand     []string
	ClaimTimeout    time.Duration
	PauseAfter      time.Duration
	ShutdownAfter   time.Duration
	WebhookQPS      float64
	CleanupInterval time.Duration
}

func NewController(opts ControllerOptions) *Controller {
	qps := opts.WebhookQPS
	if qps <= 0 {
		qps = defaultWebhookQPS
	}
	cleanup := opts.CleanupInterval
	if cleanup <= 0 {
		cleanup = defaultCleanupInterval
	}
	c := &Controller{
		manager:         opts.Manager,
		client:          newSessionClient(opts.BaseURL, opts.APIKey, 10*time.Second),
		signingSecret:   opts.SigningSecret,
		namespace:       opts.Namespace,
		template:        opts.Template,
		initCommand:     append([]string(nil), opts.InitCommand...),
		claimTimeout:    opts.ClaimTimeout,
		pauseAfter:      opts.PauseAfter,
		shutdownAfter:   opts.ShutdownAfter,
		limiter:         rate.NewLimiter(rate.Limit(qps), int(qps)),
		cleanupInterval: cleanup,
		acceptWait:      defaultAcceptWait,
		mux:             http.NewServeMux(),
		lifeCtx:         context.Background(),
	}
	c.mux.HandleFunc("POST /webhooks", c.handleWebhook)
	c.server = &http.Server{
		Addr:              network.ListenAddress(opts.BindAddress, opts.Port),
		Handler:           c.mux,
		ReadHeaderTimeout: 5 * time.Second,
	}
	return c
}

func (c *Controller) Ready() bool {
	return c != nil && c.ready && c.manager != nil
}

func (c *Controller) Start(ctx context.Context) error {
	if c.manager == nil {
		return fmt.Errorf("sandbox manager is required")
	}
	if c.signingSecret == "" || c.client.apiKey == "" {
		return fmt.Errorf("openai webhook secret and api key are required")
	}
	if c.namespace == "" || c.template == "" {
		return fmt.Errorf("openai namespace and template are required")
	}
	c.lifeCtx, c.cancel = context.WithCancel(ctx)
	listener, err := net.Listen("tcp", c.server.Addr)
	if err != nil {
		return fmt.Errorf("listen for OpenAI Agents API on %s: %w", c.server.Addr, err)
	}
	c.wg.Add(2)
	go func() {
		defer c.wg.Done()
		klog.InfoS("Starting OpenAI Agents API", "address", listener.Addr().String())
		if err := c.server.Serve(listener); err != nil && !errors.Is(err, http.ErrServerClosed) && !errors.Is(err, net.ErrClosed) {
			klog.ErrorS(err, "OpenAI Agents API HTTP server failed")
		}
	}()
	go func() {
		defer c.wg.Done()
		c.runCleanup(c.lifeCtx)
	}()
	c.ready = true
	return nil
}

func (c *Controller) Stop(ctx context.Context) {
	c.ready = false
	if c.cancel != nil {
		c.cancel()
	}
	if c.server != nil {
		if err := c.server.Shutdown(ctx); err != nil {
			klog.ErrorS(err, "OpenAI Agents API HTTP server forced to shutdown")
		}
	}
	done := make(chan struct{})
	go func() {
		c.wg.Wait()
		close(done)
	}()
	select {
	case <-done:
	case <-ctx.Done():
	}
}

func (c *Controller) handleWebhook(w http.ResponseWriter, r *http.Request) {
	body, err := io.ReadAll(io.LimitReader(r.Body, maxWebhookBodyBytes))
	if err != nil {
		http.Error(w, "failed to read body", http.StatusBadRequest)
		return
	}
	if err := verifyWebhookSignature(c.signingSecret, r.Header.Get(headerWebhookID), r.Header.Get(headerWebhookTimestamp), r.Header.Get(headerWebhookSignature), body); err != nil {
		http.Error(w, "invalid signature", http.StatusBadRequest)
		return
	}
	if !c.limiter.Allow() {
		http.Error(w, "rate limited", http.StatusServiceUnavailable)
		return
	}
	var event webhookEvent
	if err := json.Unmarshal(body, &event); err != nil {
		http.Error(w, "invalid event", http.StatusBadRequest)
		return
	}
	parent := c.lifeCtx
	if parent == nil {
		parent = context.Background()
	}
	opCtx := logs.NewContextFrom(parent, "openaiEvent", event.Type)
	accepted := make(chan struct{})
	errCh := make(chan error, 1)
	c.wg.Add(1)
	go func() {
		defer c.wg.Done()
		errCh <- c.dispatch(opCtx, event, accepted)
	}()
	timer := time.NewTimer(c.acceptWait)
	defer timer.Stop()
	select {
	case <-accepted:
		w.WriteHeader(http.StatusOK)
	case err := <-errCh:
		c.writeDispatchError(w, err)
	case <-timer.C:
		http.Error(w, "accept timeout", http.StatusServiceUnavailable)
	case <-c.lifeCtx.Done():
		http.Error(w, "shutting down", http.StatusServiceUnavailable)
	}
}

func (c *Controller) dispatch(ctx context.Context, event webhookEvent, accepted chan struct{}) error {
	var data webhookSessionData
	if len(event.Data) > 0 {
		if err := json.Unmarshal(event.Data, &data); err != nil {
			notifyAccepted(accepted)
			return nil
		}
	}
	if data.ID == "" {
		notifyAccepted(accepted)
		return nil
	}
	switch event.Type {
	case eventActionRequired:
		if data.RequiredAction == nil || data.RequiredAction.Type != actionEnvironmentConnection {
			notifyAccepted(accepted)
			return nil
		}
		return c.activateFromConnection(ctx, data.ID, accepted)
	case eventInProgress:
		return c.activateExisting(ctx, data.ID, accepted)
	case eventIdle:
		err := c.manager.DeactivateSession(ctx, sandboxmanager.DeactivateSessionOptions{
			SessionID:     data.ID,
			Namespace:     c.namespace,
			PauseAfter:    c.pauseAfter,
			ShutdownAfter: c.shutdownAfter,
		})
		if err == nil {
			notifyAccepted(accepted)
		}
		return err
	case eventFailed:
		return c.closeIfStillFailed(ctx, data.ID, accepted)
	default:
		notifyAccepted(accepted)
		return nil
	}
}

func (c *Controller) activateFromConnection(ctx context.Context, sessionID string, accepted chan struct{}) error {
	session, err := c.client.Retrieve(ctx, sessionID)
	if err != nil {
		if errors.Is(err, errSessionNotFound) {
			notifyAccepted(accepted)
			return nil
		}
		return err
	}
	if !session.needsEnvironmentConnection() {
		notifyAccepted(accepted)
		return nil
	}
	return c.manager.ActivateSession(ctx, sandboxmanager.ActivateSessionOptions{
		SessionID:       sessionID,
		Namespace:       c.namespace,
		Template:        c.template,
		CreateIfMissing: true,
		PauseAfter:      c.pauseAfter,
		ShutdownAfter:   c.shutdownAfter,
		ClaimTimeout:    c.claimTimeout,
		PostClaim:       c.postClaim(session),
		Accepted:        accepted,
	})
}

func (c *Controller) activateExisting(ctx context.Context, sessionID string, accepted chan struct{}) error {
	return c.manager.ActivateSession(ctx, sandboxmanager.ActivateSessionOptions{
		SessionID:       sessionID,
		Namespace:       c.namespace,
		Template:        c.template,
		CreateIfMissing: false,
		PauseAfter:      c.pauseAfter,
		ShutdownAfter:   c.shutdownAfter,
		ClaimTimeout:    c.claimTimeout,
		Accepted:        accepted,
	})
}

func (c *Controller) closeIfStillFailed(ctx context.Context, sessionID string, accepted chan struct{}) error {
	session, err := c.client.Retrieve(ctx, sessionID)
	if err != nil {
		if errors.Is(err, errSessionNotFound) {
			err = c.manager.CloseSession(ctx, sandboxmanager.CloseSessionOptions{SessionID: sessionID, Namespace: c.namespace})
			if err == nil {
				notifyAccepted(accepted)
			}
			return err
		}
		return err
	}
	if session.Status != "failed" {
		notifyAccepted(accepted)
		return nil
	}
	err = c.manager.CloseSession(ctx, sandboxmanager.CloseSessionOptions{SessionID: sessionID, Namespace: c.namespace})
	if err == nil {
		notifyAccepted(accepted)
	}
	return err
}

func (c *Controller) postClaim(session *agentSession) *infra.PostClaimRun {
	if len(c.initCommand) == 0 || session == nil {
		return nil
	}
	cmd := append([]string(nil), c.initCommand...)
	if session.Environment.ID != "" {
		cmd = append(cmd, session.Environment.ID)
	}
	if session.Environment.RemoteURL != "" {
		cmd = append(cmd, session.Environment.RemoteURL)
	}
	return &infra.PostClaimRun{Command: cmd}
}

func (c *Controller) writeDispatchError(w http.ResponseWriter, err error) {
	if err == nil {
		w.WriteHeader(http.StatusOK)
		return
	}
	status := http.StatusInternalServerError
	switch managererrors.GetErrCode(err) {
	case managererrors.ErrorBadRequest:
		status = http.StatusBadRequest
	case managererrors.ErrorNotFound:
		status = http.StatusNotFound
	case managererrors.ErrorConflict:
		status = http.StatusConflict
	case managererrors.ErrorUnavailable:
		status = http.StatusServiceUnavailable
	}
	http.Error(w, err.Error(), status)
}

func notifyAccepted(ch chan struct{}) {
	if ch == nil {
		return
	}
	select {
	case <-ch:
	default:
		close(ch)
	}
}
