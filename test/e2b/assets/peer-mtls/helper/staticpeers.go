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
	"net"

	"github.com/openkruise/agents/pkg/peers"
)

// staticPeers is a test-only Peers implementation that returns caller-provided
// target IPs so production SyncRouteWithPeers can be aimed at one receiver.
type staticPeers struct {
	list []peers.Peer
}

func newStaticPeers(ips []string) *staticPeers {
	list := make([]peers.Peer, 0, len(ips))
	for _, ip := range ips {
		list = append(list, peers.Peer{IP: ip, Name: ip})
	}
	return &staticPeers{list: list}
}

func (s *staticPeers) Start(context.Context, string, int) error { return nil }

func (s *staticPeers) Stop(context.Context) error { return nil }

func (s *staticPeers) GetPeers() []peers.Peer { return s.list }

func (s *staticPeers) GetAllMembers() []peers.Peer { return s.list }

func (s *staticPeers) LocalAddr() net.IP { return net.IPv4zero }

func (s *staticPeers) LocalPort() int { return 0 }
