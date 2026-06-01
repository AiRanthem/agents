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

package keys

import (
	"context"
	"crypto/rand"
	"crypto/subtle"
	"encoding/hex"
	"fmt"
	"strings"
	"sync"
	"time"

	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/klog/v2"
	"sigs.k8s.io/controller-runtime/pkg/client"
)

// SystemKeySecretName is the dedicated Secret holding the cluster-wide system
// credential. It must be pre-created; the manager never creates it.
const SystemKeySecretName = "e2b-system-key-store"

// SystemKeyDataKey is the data key inside the Secret holding the plaintext
// system credential.
const SystemKeyDataKey = "key"

const (
	systemKeyByteLen       = 32
	systemKeyBackoffMin    = 100 * time.Millisecond
	systemKeyBackoffMax    = 5 * time.Second
	systemKeyGeneratedSize = systemKeyByteLen * 2
)

// SystemKey holds the in-memory copy of the cluster-wide system credential.
type SystemKey struct {
	Namespace string
	Client    client.Client
	APIReader client.Reader

	mu  sync.RWMutex
	key string
}

func NewSystemKey(c client.Client, r client.Reader, namespace string) *SystemKey {
	return &SystemKey{
		Namespace: namespace,
		Client:    c,
		APIReader: r,
	}
}

// EnsureKey blocks until the pre-created Secret yields a non-empty key. Missing
// Secret is fail-closed: this method retries until ctx is cancelled and never
// calls Create.
func (s *SystemKey) EnsureKey(ctx context.Context) error {
	log := klog.FromContext(ctx).WithValues("secret", SystemKeySecretName, "namespace", s.Namespace)
	backoff := systemKeyBackoffMin
	for {
		if err := ctx.Err(); err != nil {
			return err
		}
		done, err := s.tryEnsureOnce(ctx)
		if done {
			return nil
		}
		if err != nil {
			log.Error(err, "system-key Secret is not ready; retrying")
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(backoff):
		}
		backoff *= 2
		if backoff > systemKeyBackoffMax {
			backoff = systemKeyBackoffMax
		}
	}
}

func (s *SystemKey) tryEnsureOnce(ctx context.Context) (bool, error) {
	secret := &corev1.Secret{}
	if err := s.APIReader.Get(ctx, client.ObjectKey{Namespace: s.Namespace, Name: SystemKeySecretName}, secret); err != nil {
		return false, fmt.Errorf("get system-key secret: %w", err)
	}

	raw := string(secret.Data[SystemKeyDataKey])
	if strings.TrimSpace(raw) != "" {
		s.setKey(raw)
		return true, nil
	}

	generated, err := generateSystemKey()
	if err != nil {
		return false, fmt.Errorf("generate system key: %w", err)
	}
	if len(generated) != systemKeyGeneratedSize {
		return false, fmt.Errorf("generated system key has unexpected length %d", len(generated))
	}

	cp := secret.DeepCopy()
	if cp.Data == nil {
		cp.Data = map[string][]byte{}
	}
	cp.Data[SystemKeyDataKey] = []byte(generated)
	if err := s.Client.Update(ctx, cp); err != nil {
		if apierrors.IsConflict(err) {
			return false, nil
		}
		return false, fmt.Errorf("populate system-key secret: %w", err)
	}
	s.setKey(generated)
	return true, nil
}

func (s *SystemKey) Key() string {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.key
}

// Match compares the presented key against the in-memory system key using a
// constant-time comparison for equal-length non-blank values.
func (s *SystemKey) Match(presented string) bool {
	in := s.Key()
	if strings.TrimSpace(in) == "" || strings.TrimSpace(presented) == "" {
		return false
	}
	if len(in) != len(presented) {
		return false
	}
	return subtle.ConstantTimeCompare([]byte(in), []byte(presented)) == 1
}

// SetKeyForUnitTest exposes the in-memory setter to package tests without
// routing through Kubernetes. Production code should use EnsureKey.
func (s *SystemKey) SetKeyForUnitTest(k string) {
	s.setKey(k)
}

func (s *SystemKey) setKey(k string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.key = k
}

func generateSystemKey() (string, error) {
	buf := make([]byte, systemKeyByteLen)
	if _, err := rand.Read(buf); err != nil {
		return "", err
	}
	return hex.EncodeToString(buf), nil
}
