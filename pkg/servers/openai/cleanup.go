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
	"errors"
	"time"

	"k8s.io/klog/v2"

	sandboxmanager "github.com/openkruise/agents/pkg/sandbox-manager"
	"github.com/openkruise/agents/pkg/sandbox-manager/infra"
)

func (c *Controller) runCleanup(ctx context.Context) {
	ticker := time.NewTicker(c.cleanupInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			if c.manager == nil || !c.manager.IsPrimary() {
				continue
			}
			c.cleanupOnce(ctx)
		}
	}
}

func (c *Controller) cleanupOnce(ctx context.Context) {
	log := klog.FromContext(ctx)
	keys, err := c.manager.ListSessionKeys(ctx, infra.ListSessionKeysOptions{Namespace: c.namespace})
	if err != nil {
		log.Error(err, "failed to list session keys for cleanup")
		return
	}
	for _, key := range keys {
		if ctx.Err() != nil || !c.manager.IsPrimary() {
			return
		}
		c.cleanupSession(ctx, key)
	}
}

func (c *Controller) cleanupSession(ctx context.Context, key infra.SessionKeyInfo) {
	log := klog.FromContext(ctx).WithValues("sessionID", key.SessionID)
	session, err := c.client.Retrieve(ctx, key.SessionID)
	if err != nil {
		if errors.Is(err, errSessionNotFound) {
			if closeErr := c.manager.CloseSession(ctx, sandboxmanager.CloseSessionOptions{
				SessionID: key.SessionID,
				Namespace: c.namespace,
			}); closeErr != nil {
				log.Error(closeErr, "failed to close session after openai reported not found")
			}
			return
		}
		log.Error(err, "openai session query failed; retaining sandbox resources")
		return
	}
	if session.Status != "failed" {
		return
	}
	if err := c.manager.CloseSession(ctx, sandboxmanager.CloseSessionOptions{
		SessionID: key.SessionID,
		Namespace: c.namespace,
	}); err != nil {
		log.Error(err, "failed to close failed openai session")
	}
}
