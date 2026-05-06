/*
Copyright 2025.

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

package cachetest

import (
	"context"

	"k8s.io/apimachinery/pkg/types"
	"k8s.io/client-go/util/retry"
	ctrlclient "sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/interceptor"
)

// ResourceVersionInterceptorFuncs returns interceptor functions that handle resourceVersion
// conflicts in tests. The controller-runtime fake client strictly checks resourceVersion,
// but tests often use separate object instances that don't have the updated resourceVersion.
// This interceptor automatically syncs resourceVersion before Update and
// subresource Update operations.
//
// Usage:
//
//	fakeClient := fake.NewClientBuilder().
//	    WithScheme(scheme).
//	    WithInterceptorFuncs(cache.ResourceVersionInterceptorFuncs()).
//	    Build()
func ResourceVersionInterceptorFuncs() interceptor.Funcs {
	return interceptor.Funcs{
		Update: func(ctx context.Context, client ctrlclient.WithWatch, obj ctrlclient.Object, opts ...ctrlclient.UpdateOption) error {
			return retry.RetryOnConflict(retry.DefaultRetry, func() error {
				syncResourceVersion(ctx, client, obj)
				return client.Update(ctx, obj, opts...)
			})
		},
		SubResourceUpdate: func(ctx context.Context, client ctrlclient.Client, subResourceName string, obj ctrlclient.Object, opts ...ctrlclient.SubResourceUpdateOption) error {
			return retry.RetryOnConflict(retry.DefaultRetry, func() error {
				syncResourceVersion(ctx, client, obj)
				return client.SubResource(subResourceName).Update(ctx, obj, opts...)
			})
		},
	}
}

type resourceVersionReader interface {
	Get(context.Context, types.NamespacedName, ctrlclient.Object, ...ctrlclient.GetOption) error
}

func syncResourceVersion(ctx context.Context, client resourceVersionReader, obj ctrlclient.Object) {
	// The Deepcopy is not necessary, but it's the simplest way to create a new object.
	// For it is only used by unit tests, so the performance impact is negligible.
	latest := obj.DeepCopyObject().(ctrlclient.Object)
	if err := client.Get(ctx, types.NamespacedName{Name: obj.GetName(), Namespace: obj.GetNamespace()}, latest); err == nil {
		obj.SetResourceVersion(latest.GetResourceVersion())
	}
}
