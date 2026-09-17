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
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"syscall"

	"github.com/openkruise/agents/pkg/utils/logs"
)

const (
	adminAddr = ":18081"
	probeAddr = ":18082"
	echoAddr  = ":18080"
	// serverName is the production peer TLS identity from pkg/peersecurity.
	serverName = "agentruntime.sandbox.agents.kruise.io"
	nodePrefix = "tw-"
)

func main() {
	mode := flag.String("mode", "", "witness, echo, or tls-refresh")
	flag.Parse()
	if *mode == "" {
		*mode = os.Getenv("PEER_MTLS_HELPER_MODE")
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	var err error
	switch *mode {
	case "witness":
		err = runWitness(ctx)
	case "echo":
		err = runEcho(ctx)
	case "tls-refresh":
		err = runTLSRefresh(ctx)
	default:
		err = fmt.Errorf("unknown mode %q", *mode)
	}
	if err != nil {
		log.Fatalf("peer-mtls helper: %s", logs.SanitizeValue(err.Error()))
	}
}
