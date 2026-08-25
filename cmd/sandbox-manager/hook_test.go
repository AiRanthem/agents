package main

import (
	"context"
	"testing"

	"github.com/stretchr/testify/require"
	"k8s.io/client-go/rest"
)

func TestDefaultStartupHook(t *testing.T) {
	require.NoError(t, defaultStartupHook(context.Background(), &rest.Config{}))
}
