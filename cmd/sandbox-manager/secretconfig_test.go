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

package main

import (
	"context"
	"errors"
	"maps"
	"testing"

	"github.com/openkruise/agents/pkg/servers/e2b/keys"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"
	"sigs.k8s.io/controller-runtime/pkg/client/interceptor"
)

func fullSecretData() map[string][]byte {
	return map[string][]byte{
		E2BAdminKeyEnvVar:        []byte("admin"),
		E2BKeyStorageDSNEnvVar:   []byte("dsn"),
		E2BKeyHashPepperEnvVar:   []byte("pepper"),
		QuotaRedisUsernameEnvVar: []byte("user"),
		QuotaRedisPasswordEnvVar: []byte("pass"),
	}
}

func secretWith(data map[string][]byte) *corev1.Secret {
	return &corev1.Secret{
		ObjectMeta: metav1.ObjectMeta{Namespace: "ns", Name: "cfg"},
		Data:       data,
	}
}

func TestParseSecretConfig(t *testing.T) {
	missing := func(key string) map[string][]byte {
		data := fullSecretData()
		delete(data, key)
		return data
	}

	cases := []struct {
		name        string
		data        map[string][]byte
		errContains string
		check       func(t *testing.T, cfg secretConfig)
	}{
		{
			name: "all-empty-ok",
			data: map[string][]byte{E2BAdminKeyEnvVar: {}, E2BKeyStorageDSNEnvVar: {}, E2BKeyHashPepperEnvVar: {}, QuotaRedisUsernameEnvVar: {}, QuotaRedisPasswordEnvVar: {}},
			check: func(t *testing.T, cfg secretConfig) {
				assert.Equal(t, secretConfig{}, cfg)
			},
		},
		{
			name:        "missing-admin-key",
			data:        missing(E2BAdminKeyEnvVar),
			errContains: E2BAdminKeyEnvVar,
		},
		{
			name:        "missing-dsn-key",
			data:        missing(E2BKeyStorageDSNEnvVar),
			errContains: E2BKeyStorageDSNEnvVar,
		},
		{
			name:        "missing-pepper-key",
			data:        missing(E2BKeyHashPepperEnvVar),
			errContains: E2BKeyHashPepperEnvVar,
		},
		{
			name:        "missing-redis-username-key",
			data:        missing(QuotaRedisUsernameEnvVar),
			errContains: QuotaRedisUsernameEnvVar,
		},
		{
			name:        "missing-redis-password-key",
			data:        missing(QuotaRedisPasswordEnvVar),
			errContains: QuotaRedisPasswordEnvVar,
		},
		{
			name: "values-present",
			data: fullSecretData(),
			check: func(t *testing.T, cfg secretConfig) {
				assert.Equal(t, "admin", cfg.AdminKey)
				assert.Equal(t, "dsn", cfg.KeyStorageDSN)
				assert.Equal(t, "pepper", cfg.KeyHashPepper)
				assert.Equal(t, "user", cfg.RedisUsername)
				assert.Equal(t, "pass", cfg.RedisPassword)
			},
		},
		{
			name: "admin-not-trimmed-others-trimmed",
			data: map[string][]byte{E2BAdminKeyEnvVar: []byte(" x "), E2BKeyStorageDSNEnvVar: []byte("  d  "), E2BKeyHashPepperEnvVar: []byte("\tp\n"), QuotaRedisUsernameEnvVar: []byte(" u "), QuotaRedisPasswordEnvVar: []byte(" w ")},
			check: func(t *testing.T, cfg secretConfig) {
				assert.Equal(t, " x ", cfg.AdminKey)
				assert.Equal(t, "d", cfg.KeyStorageDSN)
				assert.Equal(t, "p", cfg.KeyHashPepper)
				assert.Equal(t, "u", cfg.RedisUsername)
				assert.Equal(t, "w", cfg.RedisPassword)
			},
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			cfg, err := parseSecretConfig(tc.data)
			if tc.errContains != "" {
				require.Error(t, err)
				assert.Contains(t, err.Error(), tc.errContains)
				return
			}
			require.NoError(t, err)
			if tc.check != nil {
				tc.check(t, cfg)
			}
		})
	}
}

func TestLoadSecretConfig(t *testing.T) {
	t.Run("ref", func(t *testing.T) {
		c := fake.NewClientBuilder().WithObjects(secretWith(fullSecretData())).Build()
		cases := []struct {
			name      string
			ref       string
			defaultNs string
			wantErr   string
		}{
			{name: "ns-name", ref: "ns/cfg", defaultNs: "sys"},
			{name: "name-only-uses-default-ns", ref: "cfg", defaultNs: "ns"},
			{name: "empty-namespace-uses-default-ns", ref: "/cfg", defaultNs: "ns"},
			{name: "empty-name", ref: "ns/", defaultNs: "sys", wantErr: "Secret name or namespace/name"},
			{name: "empty", ref: "", defaultNs: "sys", wantErr: "Secret name or namespace/name"},
			{name: "extra-slash", ref: "ns/cfg/extra", defaultNs: "sys", wantErr: "Secret name or namespace/name"},
			{name: "name-only-empty-default-ns", ref: "cfg", defaultNs: "", wantErr: "Secret name or namespace/name"},
		}
		for _, tc := range cases {
			t.Run(tc.name, func(t *testing.T) {
				cfg, err := loadSecretConfig(c, tc.ref, tc.defaultNs)
				if tc.wantErr != "" {
					require.Error(t, err)
					assert.Contains(t, err.Error(), tc.wantErr)
					return
				}
				require.NoError(t, err)
				assert.Equal(t, "admin", cfg.AdminKey)
			})
		}
	})

	t.Run("success", func(t *testing.T) {
		c := fake.NewClientBuilder().WithObjects(secretWith(fullSecretData())).Build()
		cfg, err := loadSecretConfig(c, "ns/cfg", "sys")
		require.NoError(t, err)
		assert.Equal(t, "admin", cfg.AdminKey)
		assert.Equal(t, "dsn", cfg.KeyStorageDSN)
		assert.Equal(t, "pepper", cfg.KeyHashPepper)
	})
	t.Run("not-found", func(t *testing.T) {
		c := fake.NewClientBuilder().Build()
		_, err := loadSecretConfig(c, "ns/cfg", "sys")
		require.Error(t, err)
		assert.True(t, apierrors.IsNotFound(err))
		assert.Contains(t, err.Error(), "ns/cfg")
	})
	t.Run("forbidden", func(t *testing.T) {
		forbidden := apierrors.NewForbidden(schema.GroupResource{Resource: "secrets"}, "cfg", errors.New("denied"))
		c := fake.NewClientBuilder().WithInterceptorFuncs(interceptor.Funcs{
			Get: func(ctx context.Context, c client.WithWatch, key client.ObjectKey, obj client.Object, opts ...client.GetOption) error {
				return forbidden
			},
		}).Build()
		_, err := loadSecretConfig(c, "ns/cfg", "sys")
		require.Error(t, err)
		assert.True(t, apierrors.IsForbidden(err))
	})
	t.Run("missing-key-wrapped-with-ref", func(t *testing.T) {
		data := fullSecretData()
		delete(data, E2BKeyHashPepperEnvVar)
		c := fake.NewClientBuilder().WithObjects(secretWith(data)).Build()
		_, err := loadSecretConfig(c, "ns/cfg", "sys")
		require.Error(t, err)
		assert.Contains(t, err.Error(), E2BKeyHashPepperEnvVar)
		assert.Contains(t, err.Error(), "ns/cfg")
	})
	t.Run("exactly-one-precise-get-never-list", func(t *testing.T) {
		getCalls := 0
		var gotKey client.ObjectKey
		c := fake.NewClientBuilder().
			WithObjects(secretWith(fullSecretData())).
			WithInterceptorFuncs(interceptor.Funcs{
				Get: func(ctx context.Context, c client.WithWatch, key client.ObjectKey, obj client.Object, opts ...client.GetOption) error {
					getCalls++
					gotKey = key
					return c.Get(ctx, key, obj, opts...)
				},
				List: func(ctx context.Context, c client.WithWatch, list client.ObjectList, opts ...client.ListOption) error {
					t.Fatal("List must never be called")
					return nil
				},
			}).Build()
		_, err := loadSecretConfig(c, "ns/cfg", "sys")
		require.NoError(t, err)
		assert.Equal(t, 1, getCalls)
		assert.Equal(t, client.ObjectKey{Namespace: "ns", Name: "cfg"}, gotKey)
	})
}

func TestSecretConfigErrorsDoNotLeakValues(t *testing.T) {
	const sentinel = "SUPER_SECRET_SENTINEL"
	data := map[string][]byte{
		E2BAdminKeyEnvVar:        []byte(sentinel + "_ADMIN"),
		E2BKeyStorageDSNEnvVar:   []byte(sentinel + "_DSN"),
		E2BKeyHashPepperEnvVar:   []byte(sentinel + "_PEPPER"),
		QuotaRedisUsernameEnvVar: []byte(sentinel + "_USER"),
		QuotaRedisPasswordEnvVar: []byte(sentinel + "_PASS"),
	}

	t.Run("missing-key-error-omits-values", func(t *testing.T) {
		incomplete := map[string][]byte{}
		maps.Copy(incomplete, data)
		delete(incomplete, E2BKeyStorageDSNEnvVar)
		_, err := parseSecretConfig(incomplete)
		require.Error(t, err)
		assert.NotContains(t, err.Error(), sentinel)
	})

	t.Run("loaded-error-omits-values", func(t *testing.T) {
		incomplete := map[string][]byte{}
		maps.Copy(incomplete, data)
		delete(incomplete, E2BAdminKeyEnvVar)
		c := fake.NewClientBuilder().WithObjects(secretWith(incomplete)).Build()
		_, err := loadSecretConfig(c, "ns/cfg", "sys")
		require.Error(t, err)
		assert.NotContains(t, err.Error(), sentinel)
	})
}

func TestValidateSecretValues(t *testing.T) {
	cases := []struct {
		name        string
		adminKey    string
		dsn         string
		pepper      string
		enableAuth  bool
		storageMode keys.StorageMode
		errContains string
	}{
		{name: "auth-off-all-empty-ok", enableAuth: false},
		{name: "auth-on-empty-admin-fails", enableAuth: true, errContains: E2BAdminKeyEnvVar},
		{name: "auth-on-secret-storage-empty-dsn-ok", adminKey: "admin", enableAuth: true, storageMode: keys.StorageModeSecret},
		{name: "auth-on-mysql-empty-dsn-fails", adminKey: "admin", pepper: "pepper", enableAuth: true, storageMode: keys.StorageModeMySQL, errContains: E2BKeyStorageDSNEnvVar},
		{name: "auth-on-mysql-empty-pepper-fails", adminKey: "admin", dsn: "dsn", enableAuth: true, storageMode: keys.StorageModeMySQL, errContains: E2BKeyHashPepperEnvVar},
		{name: "auth-on-mysql-all-present-ok", adminKey: "admin", dsn: "dsn", pepper: "pepper", enableAuth: true, storageMode: keys.StorageModeMySQL},
		{name: "empty-admin-error-omits-other-values", adminKey: "", dsn: "SUPER_SECRET_SENTINEL", pepper: "SUPER_SECRET_SENTINEL", enableAuth: true, storageMode: keys.StorageModeMySQL, errContains: E2BAdminKeyEnvVar},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			err := validateSecretValues(tc.adminKey, tc.dsn, tc.pepper, tc.enableAuth, tc.storageMode)
			if tc.errContains != "" {
				require.Error(t, err)
				assert.Contains(t, err.Error(), tc.errContains)
				assert.NotContains(t, err.Error(), "SUPER_SECRET_SENTINEL")
				return
			}
			require.NoError(t, err)
		})
	}
}
