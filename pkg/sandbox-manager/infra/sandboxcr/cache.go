package sandboxcr

import (
	"context"
	"fmt"
	"sync"
	"time"

	agentsv1alpha1 "github.com/openkruise/agents/api/v1alpha1"
	informers "github.com/openkruise/agents/client/informers/externalversions"
	"github.com/openkruise/agents/pkg/sandbox-manager/consts"
	"github.com/openkruise/agents/pkg/utils"
	managerutils "github.com/openkruise/agents/pkg/utils/sandbox-manager"
	"k8s.io/client-go/tools/cache"
	"k8s.io/klog/v2"
	"sigs.k8s.io/controller-runtime/pkg/client"
)

type checkFunc func(sbx *agentsv1alpha1.Sandbox) (bool, error)

type Cache struct {
	informerFactory    informers.SharedInformerFactory
	sandboxInformer    cache.SharedIndexInformer
	sandboxSetInformer cache.SharedIndexInformer
	stopCh             chan struct{}
	waitHooks          sync.Map
}

func NewCache(informerFactory informers.SharedInformerFactory, sandboxInformer, sandboxSetInformer cache.SharedIndexInformer) (*Cache, error) {
	if err := AddLabelSelectorIndexerToInformer(sandboxInformer); err != nil {
		return nil, err
	}
	c := &Cache{
		informerFactory:    informerFactory,
		sandboxInformer:    sandboxInformer,
		sandboxSetInformer: sandboxSetInformer,
		stopCh:             make(chan struct{}),
	}
	return c, nil
}

func (c *Cache) Run(ctx context.Context) error {
	log := klog.FromContext(ctx)
	_, err := c.sandboxInformer.AddEventHandler(cache.ResourceEventHandlerFuncs{
		UpdateFunc: func(oldObj, newObj interface{}) {
			c.watchSandboxSatisfied(newObj)
		},
		AddFunc: func(obj interface{}) {
			c.watchSandboxSatisfied(obj)
		},
		DeleteFunc: func(obj interface{}) {
			c.watchSandboxSatisfied(obj)
		},
	})
	if err != nil {
		log.Error(err, "failed to create waiter handler")
		return err
	}
	c.informerFactory.Start(c.stopCh)
	log.Info("Cache informer started")
	c.informerFactory.WaitForCacheSync(c.stopCh)
	log.Info("Cache informer synced")
	return nil
}

func (c *Cache) Stop() {
	close(c.stopCh)
	klog.Info("Cache informer stopped")
}

func (c *Cache) AddSandboxEventHandler(handler cache.ResourceEventHandlerFuncs) {
	_, err := c.sandboxInformer.AddEventHandler(handler)
	if err != nil {
		panic(err)
	}
}

func (c *Cache) ListSandboxWithUser(user string) ([]*agentsv1alpha1.Sandbox, error) {
	return managerutils.SelectObjectWithIndex[*agentsv1alpha1.Sandbox](c.sandboxInformer, IndexUser, user)
}

func (c *Cache) ListAvailableSandboxes(pool string) ([]*agentsv1alpha1.Sandbox, error) {
	return managerutils.SelectObjectWithIndex[*agentsv1alpha1.Sandbox](c.sandboxInformer, IndexPoolAvailable, pool)
}

func (c *Cache) GetSandbox(sandboxID string) (*agentsv1alpha1.Sandbox, error) {
	list, err := managerutils.SelectObjectWithIndex[*agentsv1alpha1.Sandbox](c.sandboxInformer, IndexSandboxID, sandboxID)
	if err != nil {
		return nil, err
	}
	if len(list) == 0 {
		return nil, fmt.Errorf("sandbox %s not found in cache", sandboxID)
	}
	if len(list) > 1 {
		return nil, fmt.Errorf("multiple sandboxes found with id %s", sandboxID)
	}
	return list[0], nil
}

func (c *Cache) AddSandboxSetEventHandler(handler cache.ResourceEventHandlerFuncs) {
	if c.sandboxSetInformer == nil {
		panic("SandboxSet is not cached")
	}
	_, err := c.sandboxSetInformer.AddEventHandler(handler)
	if err != nil {
		panic(err)
	}
}

func (c *Cache) Refresh() {
	c.informerFactory.WaitForCacheSync(c.stopCh)
}

type satisfiedResult struct {
	ok  bool
	err error
}

type waitEntry struct {
	ctx     context.Context
	ch      chan satisfiedResult
	checker checkFunc
}

func (c *Cache) WaitForSandboxSatisfied(ctx context.Context, sbx *agentsv1alpha1.Sandbox, satisfiedFunc checkFunc, timeout time.Duration) error {
	key := client.ObjectKeyFromObject(sbx)
	log := klog.FromContext(ctx).V(consts.DebugLogLevel).WithValues("key", key)
	ch := make(chan satisfiedResult, 1)

	entry := &waitEntry{
		ctx:     ctx,
		ch:      ch,
		checker: satisfiedFunc,
	}
	_, exists := c.waitHooks.LoadOrStore(key, entry)
	if exists {
		log.Error(nil, "wait hook already exists")
		return fmt.Errorf("wait hook for %s already exists", key)
	}
	log.Info("wait hook created")

	timer := time.NewTimer(timeout)
	defer func() {
		timer.Stop()
		c.waitHooks.Delete(key)
		log.Info("wait hook deleted")
	}()

	select {
	case <-timer.C:
		log.Error(nil, "timeout waiting for sandbox satisfied")
		return fmt.Errorf("timeout waiting for sandbox satisfied")
	case result := <-ch:
		log.Info("got wait result", "satisfied", result.ok, "err", result.err)
		if result.err != nil {
			log.Error(result.err, "wait hook failed")
			return result.err
		}
		return nil
	}
}

func (c *Cache) watchSandboxSatisfied(obj interface{}) {
	sbx, ok := obj.(*agentsv1alpha1.Sandbox)
	if !ok {
		return
	}
	key := client.ObjectKeyFromObject(sbx)
	value, ok := c.waitHooks.Load(key)
	if !ok {
		return
	}
	entry := value.(*waitEntry)
	log := klog.FromContext(entry.ctx).V(consts.DebugLogLevel).WithValues("key", key)
	satisfied, err := entry.checker(sbx)
	log.Info("watch sandbox satisfied result",
		"satisfied", satisfied, "err", err, "resourceVersion", sbx.GetResourceVersion())
	if satisfied || err != nil {
		utils.WriteChannelSafely(entry.ch, satisfiedResult{satisfied, err})
		return
	}
}
