package utils

import (
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/tools/cache"
)

func SelectObjectWithIndex[T metav1.Object](informer cache.SharedIndexInformer, key, value string) ([]T, error) {
	objs, err := informer.GetIndexer().ByIndex(key, value)
	if err != nil {
		return nil, err
	}

	results := make([]T, 0, len(objs))
	for _, obj := range objs {
		got, ok := obj.(T)
		if !ok {
			continue
		}
		results = append(results, got)
		ResourceVersionExpectationObserve(got)
	}
	return results, nil
}
