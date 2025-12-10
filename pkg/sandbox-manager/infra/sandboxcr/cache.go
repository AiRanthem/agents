package sandboxcr

import (
	"fmt"

	agentsv1alpha1 "github.com/openkruise/agents/api/v1alpha1"
	informers "github.com/openkruise/agents/client/informers/externalversions"
	utils "github.com/openkruise/agents/pkg/utils/sandbox-manager"
	"k8s.io/client-go/tools/cache"
	"k8s.io/klog/v2"
)

type Cache struct {
	informerFactory    informers.SharedInformerFactory
	sandboxInformer    cache.SharedIndexInformer
	sandboxSetInformer cache.SharedIndexInformer
	stopCh             chan struct{}
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

func (c *Cache) Run(done chan<- struct{}) {
	c.informerFactory.Start(c.stopCh)
	klog.Info("Cache informer started")
	go func() {
		c.informerFactory.WaitForCacheSync(c.stopCh)
		if done != nil {
			done <- struct{}{}
		}
		klog.Info("Cache informer synced")
	}()
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
	return utils.SelectObjectWithIndex[*agentsv1alpha1.Sandbox](c.sandboxInformer, IndexUser, user)
}

func (c *Cache) ListAvailableSandboxes(pool string) ([]*agentsv1alpha1.Sandbox, error) {
	return utils.SelectObjectWithIndex[*agentsv1alpha1.Sandbox](c.sandboxInformer, IndexPoolAvailable, pool)
}

func (c *Cache) GetSandbox(sandboxID string) (*agentsv1alpha1.Sandbox, error) {
	list, err := utils.SelectObjectWithIndex[*agentsv1alpha1.Sandbox](c.sandboxInformer, IndexSandboxID, sandboxID)
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
