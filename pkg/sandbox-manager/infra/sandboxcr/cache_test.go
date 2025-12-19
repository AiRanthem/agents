package sandboxcr

import (
	"context"
	"testing"
	"time"

	agentsv1alpha1 "github.com/openkruise/agents/api/v1alpha1"
	"github.com/openkruise/agents/client/clientset/versioned/fake"
	informers "github.com/openkruise/agents/client/informers/externalversions"
	"github.com/stretchr/testify/assert"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

//goland:noinspection GoDeprecation
func NewTestCache() (cache *Cache, client *fake.Clientset) {
	client = fake.NewSimpleClientset()
	informerFactory := informers.NewSharedInformerFactory(client, time.Minute*10)
	sandboxInformer := informerFactory.Api().V1alpha1().Sandboxes().Informer()
	sandboxSetInformer := informerFactory.Api().V1alpha1().SandboxSets().Informer()
	cache, err := NewCache(informerFactory, sandboxInformer, sandboxSetInformer)
	if err != nil {
		panic(err)
	}
	err = cache.Run(context.Background())
	if err != nil {
		panic(err)
	}
	return cache, client
}

func TestCache_WaitForSandboxSatisfied(t *testing.T) {
	tests := []struct {
		name          string
		setupFunc     func(*testing.T, *Cache, *fake.Clientset) *agentsv1alpha1.Sandbox
		checkFunc     checkFunc
		timeout       time.Duration
		expectError   bool
		expectTimeout bool
	}{
		{
			name: "unsatisfied condition should timeout",
			setupFunc: func(t *testing.T, cache *Cache, client *fake.Clientset) *agentsv1alpha1.Sandbox {
				sandbox := &agentsv1alpha1.Sandbox{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "test-sandbox-1",
						Namespace: "default",
					},
					Status: agentsv1alpha1.SandboxStatus{
						Phase: agentsv1alpha1.SandboxPending,
					},
				}
				_, err := client.ApiV1alpha1().Sandboxes("default").Create(context.Background(), sandbox, metav1.CreateOptions{})
				assert.NoError(t, err)
				time.Sleep(10 * time.Millisecond) // Allow informer to sync
				return sandbox
			},
			checkFunc: func(sbx *agentsv1alpha1.Sandbox) (bool, error) {
				return sbx.Status.Phase == agentsv1alpha1.SandboxRunning, nil
			},
			timeout:       100 * time.Millisecond,
			expectError:   true,
			expectTimeout: true,
		},
		{
			name: "check function returns error",
			setupFunc: func(t *testing.T, cache *Cache, client *fake.Clientset) *agentsv1alpha1.Sandbox {
				sandbox := &agentsv1alpha1.Sandbox{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "test-sandbox-2",
						Namespace: "default",
					},
					Status: agentsv1alpha1.SandboxStatus{
						Phase: agentsv1alpha1.SandboxPending,
					},
				}
				_, err := client.ApiV1alpha1().Sandboxes("default").Create(context.Background(), sandbox, metav1.CreateOptions{})
				assert.NoError(t, err)
				time.Sleep(10 * time.Millisecond) // Allow informer to sync
				return sandbox
			},
			checkFunc: func(sbx *agentsv1alpha1.Sandbox) (bool, error) {
				return false, assert.AnError
			},
			timeout:     1 * time.Second,
			expectError: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cache, client := NewTestCache()
			defer cache.Stop()

			// Setup test sandbox
			sandbox := tt.setupFunc(t, cache, client)

			// Call WaitForSandboxSatisfied
			ctx := context.Background()
			err := cache.WaitForSandboxSatisfied(ctx, sandbox, tt.checkFunc, tt.timeout)

			// Check results
			if tt.expectError {
				assert.Error(t, err)
				if tt.expectTimeout {
					assert.Contains(t, err.Error(), "timeout")
				}
			} else {
				assert.NoError(t, err)
			}
		})
	}
}

func TestCache_WaitForSandboxSatisfiedWithUpdate(t *testing.T) {
	cache, client := NewTestCache()
	defer cache.Stop()

	// Create a sandbox with Pending phase
	sandbox := &agentsv1alpha1.Sandbox{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-sandbox-update",
			Namespace: "default",
		},
		Status: agentsv1alpha1.SandboxStatus{
			Phase: agentsv1alpha1.SandboxPending,
		},
	}
	_, err := client.ApiV1alpha1().Sandboxes("default").Create(context.Background(), sandbox, metav1.CreateOptions{})
	assert.NoError(t, err)
	time.Sleep(10 * time.Millisecond) // Allow informer to sync

	// Start waiting for the sandbox to become Running
	checkFunc := func(sbx *agentsv1alpha1.Sandbox) (bool, error) {
		return sbx.Status.Phase == agentsv1alpha1.SandboxRunning, nil
	}

	// In a separate goroutine, update the sandbox to Running after a delay
	go func() {
		time.Sleep(50 * time.Millisecond)
		sandbox.Status.Phase = agentsv1alpha1.SandboxRunning
		_, err := client.ApiV1alpha1().Sandboxes("default").Update(context.Background(), sandbox, metav1.UpdateOptions{})
		assert.NoError(t, err)
	}()

	// Wait for the condition to be satisfied, should succeed
	ctx := context.Background()
	err = cache.WaitForSandboxSatisfied(ctx, sandbox, checkFunc, 1*time.Second)
	assert.NoError(t, err)
}
