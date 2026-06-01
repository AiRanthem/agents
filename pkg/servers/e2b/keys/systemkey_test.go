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
	"errors"
	"sync/atomic"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"
	"sigs.k8s.io/controller-runtime/pkg/client/interceptor"
)

const testSystemNamespace = "sandbox-system"

func newSystemKeySchemeForTest(t *testing.T) *runtime.Scheme {
	t.Helper()
	scheme := runtime.NewScheme()
	require.NoError(t, clientgoscheme.AddToScheme(scheme))
	return scheme
}

func systemKeySecretWithData(data map[string][]byte) *corev1.Secret {
	return &corev1.Secret{
		ObjectMeta: metav1.ObjectMeta{Name: SystemKeySecretName, Namespace: testSystemNamespace},
		Type:       corev1.SecretTypeOpaque,
		Data:       data,
	}
}

func TestSystemKey_EnsureKey_SecretMissing_FailsClosedAndNeverCreates(t *testing.T) {
	scheme := newSystemKeySchemeForTest(t)
	var createCalls atomic.Int32
	var updateCalls atomic.Int32
	fc := fake.NewClientBuilder().
		WithScheme(scheme).
		WithInterceptorFuncs(interceptor.Funcs{
			Create: func(ctx context.Context, c client.WithWatch, obj client.Object, opts ...client.CreateOption) error {
				createCalls.Add(1)
				return c.Create(ctx, obj, opts...)
			},
			Update: func(ctx context.Context, c client.WithWatch, obj client.Object, opts ...client.UpdateOption) error {
				updateCalls.Add(1)
				return c.Update(ctx, obj, opts...)
			},
		}).
		Build()

	sk := NewSystemKey(fc, fc, testSystemNamespace)
	ctx, cancel := context.WithTimeout(context.Background(), 150*time.Millisecond)
	defer cancel()

	err := sk.EnsureKey(ctx)
	require.Error(t, err)
	assert.ErrorIs(t, err, context.DeadlineExceeded)
	assert.Equal(t, int32(0), createCalls.Load())
	assert.Equal(t, int32(0), updateCalls.Load())
	assert.Empty(t, sk.Key())
}

func TestSystemKey_EnsureKey_DataAbsent_PopulatesViaUpdate(t *testing.T) {
	fc := fake.NewClientBuilder().
		WithScheme(newSystemKeySchemeForTest(t)).
		WithObjects(systemKeySecretWithData(map[string][]byte{})).
		Build()
	sk := NewSystemKey(fc, fc, testSystemNamespace)

	require.NoError(t, sk.EnsureKey(context.Background()))

	got := sk.Key()
	require.NotEmpty(t, got)
	var stored corev1.Secret
	require.NoError(t, fc.Get(context.Background(), client.ObjectKey{Namespace: testSystemNamespace, Name: SystemKeySecretName}, &stored))
	assert.Equal(t, got, string(stored.Data[SystemKeyDataKey]))
}

func TestSystemKey_EnsureKey_DataEmptyOrWhitespace_PopulatesViaUpdate(t *testing.T) {
	tests := []struct {
		name string
		raw  string
	}{
		{name: "empty string", raw: ""},
		{name: "single space", raw: " "},
		{name: "tab", raw: "\t"},
		{name: "newline", raw: "\n"},
		{name: "mixed whitespace", raw: " \t\n "},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			fc := fake.NewClientBuilder().
				WithScheme(newSystemKeySchemeForTest(t)).
				WithObjects(systemKeySecretWithData(map[string][]byte{SystemKeyDataKey: []byte(tt.raw)})).
				Build()
			sk := NewSystemKey(fc, fc, testSystemNamespace)

			require.NoError(t, sk.EnsureKey(context.Background()))

			got := sk.Key()
			require.NotEmpty(t, got)
			assert.NotEqual(t, tt.raw, got)
			var stored corev1.Secret
			require.NoError(t, fc.Get(context.Background(), client.ObjectKey{Namespace: testSystemNamespace, Name: SystemKeySecretName}, &stored))
			assert.Equal(t, got, string(stored.Data[SystemKeyDataKey]))
		})
	}
}

func TestSystemKey_EnsureKey_AlreadyPopulated_AdoptsAsIsAndDoesNotUpdate(t *testing.T) {
	tests := []struct {
		name   string
		preset string
	}{
		{name: "plain key", preset: "preset-system-key-do-not-rewrite"},
		{name: "non-empty key with surrounding whitespace", preset: " preset-system-key-with-spaces "},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var updateCalls atomic.Int32
			fc := fake.NewClientBuilder().
				WithScheme(newSystemKeySchemeForTest(t)).
				WithObjects(systemKeySecretWithData(map[string][]byte{SystemKeyDataKey: []byte(tt.preset)})).
				WithInterceptorFuncs(interceptor.Funcs{
					Update: func(ctx context.Context, c client.WithWatch, obj client.Object, opts ...client.UpdateOption) error {
						updateCalls.Add(1)
						return c.Update(ctx, obj, opts...)
					},
				}).
				Build()
			sk := NewSystemKey(fc, fc, testSystemNamespace)

			require.NoError(t, sk.EnsureKey(context.Background()))

			assert.Equal(t, tt.preset, sk.Key())
			assert.Equal(t, int32(0), updateCalls.Load())
		})
	}
}

func TestSystemKey_EnsureKey_ConcurrentFirstWriteConflict_AdoptsWinner(t *testing.T) {
	scheme := newSystemKeySchemeForTest(t)
	gvr := schema.GroupResource{Resource: "secrets"}
	var updateCalls atomic.Int32
	fc := fake.NewClientBuilder().
		WithScheme(scheme).
		WithObjects(systemKeySecretWithData(map[string][]byte{})).
		WithInterceptorFuncs(interceptor.Funcs{
			Update: func(ctx context.Context, c client.WithWatch, obj client.Object, opts ...client.UpdateOption) error {
				if updateCalls.Add(1) == 1 {
					winner := obj.DeepCopyObject().(*corev1.Secret)
					if winner.Data == nil {
						winner.Data = map[string][]byte{}
					}
					winner.Data[SystemKeyDataKey] = []byte("winner-system-key")
					require.NoError(t, c.Update(ctx, winner, opts...))
					return apierrors.NewConflict(gvr, SystemKeySecretName, errors.New("simulated conflict"))
				}
				return c.Update(ctx, obj, opts...)
			},
		}).
		Build()
	sk := NewSystemKey(fc, fc, testSystemNamespace)

	require.NoError(t, sk.EnsureKey(context.Background()))

	assert.Equal(t, "winner-system-key", sk.Key())
	assert.Equal(t, int32(1), updateCalls.Load())
}

func TestSystemKey_Match_RejectsBlankAndUsesExactMatch(t *testing.T) {
	sk := &SystemKey{}
	sk.SetKeyForUnitTest("known-system-key")

	tests := []struct {
		name      string
		presented string
		expect    bool
	}{
		{name: "exact match", presented: "known-system-key", expect: true},
		{name: "blank presented key rejected", presented: "", expect: false},
		{name: "trailing diff rejected", presented: "known-system-keyy", expect: false},
		{name: "shorter rejected", presented: "kno", expect: false},
		{name: "unrelated rejected", presented: "WRONG", expect: false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.expect, sk.Match(tt.presented))
		})
	}

	sk.SetKeyForUnitTest("")
	assert.False(t, sk.Match("known-system-key"))
}
