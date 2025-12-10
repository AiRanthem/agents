package sandboxcr

import (
	"time"

	"github.com/openkruise/agents/client/clientset/versioned/fake"
	informers "github.com/openkruise/agents/client/informers/externalversions"
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
	done := make(chan struct{})
	go cache.Run(done)
	<-done
	return cache, client
}
