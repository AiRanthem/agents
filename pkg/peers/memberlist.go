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

package peers

import (
	"context"
	"errors"
	"fmt"
	"net"
	"os"
	"sort"
	"strconv"
	"sync"
	"time"

	"github.com/hashicorp/memberlist"
	agentsv1alpha1 "github.com/openkruise/agents/api/v1alpha1"
	"github.com/openkruise/agents/pkg/sandbox-manager/logs"
	"github.com/openkruise/agents/pkg/utils"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/labels"
	"k8s.io/klog/v2"
	ctrlclient "sigs.k8s.io/controller-runtime/pkg/client"
)

const (
	// DefaultProbeInterval is the interval between gossip probes
	DefaultProbeInterval = 500 * time.Millisecond
	// DefaultProbeTimeout is the timeout for gossip probes
	DefaultProbeTimeout = 200 * time.Millisecond
	// DefaultGossipInterval is the interval between gossip messages
	DefaultGossipInterval = 500 * time.Millisecond
	// DefaultGossipNodes is the number of nodes to gossip to
	DefaultGossipNodes = 3
	// DefaultSuspicionMult is the multiplier for determining the time to wait before considering a node suspect
	DefaultSuspicionMult = 4
	// DefaultRetransmitMult is the multiplier for the number of retransmissions
	DefaultRetransmitMult = 4
	// DefaultJoinRetryInterval is the delay between peer discovery attempts.
	DefaultJoinRetryInterval = 10 * time.Second
	// DefaultLeaveTimeout bounds graceful memberlist departure.
	DefaultLeaveTimeout = 5 * time.Second
)

type memberlistHandle interface {
	Join(existing []string) (int, error)
	Leave(timeout time.Duration) error
	Shutdown() error
	Members() []*memberlist.Node
	LocalNode() *memberlist.Node
}

// MemberlistPeers discovers peers through hashicorp memberlist.
//
// Lifecycle contract: Start is called exactly once, Stop is called at most
// once, and the two never run concurrently; the only breach is Stop arriving
// before Start, because shutdown signals can land while the owner is still
// starting. mu plus stopped then keep a stopped peer from ever starting.
type MemberlistPeers struct {
	apiReader ctrlclient.Reader

	localName    string
	peerSelector string
	sysNs        string

	retryInterval time.Duration

	// mu guards stopped and the lifecycle fields below; see the type doc.
	mu              sync.Mutex
	stopped         bool
	list            memberlistHandle
	lifecycleCancel context.CancelFunc
	// lifecycleDone carries the cleanup result; buffered so the lifecycle
	// goroutine never blocks on delivery when Stop gives up waiting.
	// A non-nil lifecycleDone deliberately doubles as the "started" marker:
	// Start assigns it right before launching the goroutine, so Stop needs
	// no separate started flag.
	lifecycleDone chan error
}

// NewMemberlistPeers lists selector-matching seed Pods through reader until a
// join succeeds. Production passes a live uncached client; tests may pass a fake.
func NewMemberlistPeers(apiReader ctrlclient.Reader, nodeName string, namespace, peerSelector string) *MemberlistPeers {
	return &MemberlistPeers{
		apiReader:     apiReader,
		sysNs:         namespace,
		peerSelector:  peerSelector,
		localName:     nodeName,
		retryInterval: DefaultJoinRetryInterval,
	}
}

func FindPodIP() (string, error) {
	podIP := os.Getenv("POD_IP")
	if podIP == "" {
		podIP = utils.GetFirstNonLoopbackIP()
	}
	if podIP == "" {
		return "", fmt.Errorf("failed to determine local IP for memberlist")
	}
	return podIP, nil
}

// Start creates the memberlist listener and starts peer discovery in the
// background. It must be called exactly once and fails when Stop has already
// run.
func (m *MemberlistPeers) Start(ctx context.Context, bindAddress string, bindPort int) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.stopped {
		return errors.New("peer discovery is stopped")
	}
	log := klog.FromContext(ctx)
	if err := ctx.Err(); err != nil {
		return err
	}
	if m.apiReader == nil {
		return fmt.Errorf("peer reader is not configured")
	}
	if m.sysNs == "" {
		return fmt.Errorf("peer namespace is empty")
	}
	if m.peerSelector == "" {
		return fmt.Errorf("peer selector is empty")
	}
	selector, err := labels.Parse(m.peerSelector)
	if err != nil {
		return fmt.Errorf("failed to parse peer selector: %w", err)
	}

	localIP := bindAddress
	if localIP == "" {
		localIP, err = FindPodIP()
		if err != nil {
			return fmt.Errorf("failed to determine local IP for memberlist: %w", err)
		}
	}

	localURL := net.JoinHostPort(localIP, strconv.Itoa(bindPort))

	// Create memberlist config
	config := memberlist.DefaultLANConfig()
	config.Name = m.localName
	config.BindAddr = localIP
	config.BindPort = bindPort
	config.AdvertisePort = bindPort
	if bindAddress != "" {
		config.AdvertiseAddr = localIP
	}

	// Tuning for faster failure detection and convergence
	config.ProbeInterval = DefaultProbeInterval
	config.ProbeTimeout = DefaultProbeTimeout
	config.GossipInterval = DefaultGossipInterval
	config.GossipNodes = DefaultGossipNodes
	config.SuspicionMult = DefaultSuspicionMult
	config.RetransmitMult = DefaultRetransmitMult

	// Set up event delegate to track membership changes
	config.Events = &eventDelegate{
		parent: m,
		logCtx: logs.NewContext(),
	}

	// Disable logging from memberlist itself (we use klog)
	config.LogOutput = nil
	config.Logger = nil

	// Create the memberlist
	list, err := memberlist.Create(config)
	if err != nil {
		return fmt.Errorf("failed to create memberlist: %w", err)
	}
	m.list = list
	lifecycleCtx, cancel := context.WithCancel(ctx)
	m.lifecycleCancel = cancel
	m.lifecycleDone = make(chan error, 1)
	go m.runLifecycle(lifecycleCtx, selector, bindPort, localURL)
	log.Info("memberlist started", "addr", localIP, "port", bindPort, "name", m.localName)

	return nil
}

func (m *MemberlistPeers) runLifecycle(ctx context.Context, selector labels.Selector, bindPort int, localURL string) {
	ticker := time.NewTicker(m.retryInterval)
	for ctx.Err() == nil {
		if m.tryJoin(ctx, selector, bindPort, localURL) {
			break
		}
		select {
		case <-ctx.Done():
		case <-ticker.C:
		}
	}
	ticker.Stop()
	<-ctx.Done()
	m.lifecycleDone <- m.cleanup()
}

// tryJoin lists candidate seed Pods once and joins them one by one in stable
// order until one join succeeds. It reports whether this peer has joined.
func (m *MemberlistPeers) tryJoin(ctx context.Context, selector labels.Selector, bindPort int, localURL string) bool {
	log := klog.FromContext(ctx)
	peerList := &corev1.PodList{}
	err := m.apiReader.List(ctx, peerList, &ctrlclient.ListOptions{
		Namespace:     m.sysNs,
		LabelSelector: selector,
	})
	if err != nil {
		if ctx.Err() == nil {
			log.Error(err, "failed to list peer pods")
		}
		return false
	}
	// Join one seed at a time: a bulk Join probes every address serially
	// without short-circuiting, while per-seed calls stop at the first live
	// seed and honor cancellation between attempts.
	for _, seed := range trustedSeedAddresses(peerList.Items, localURL, bindPort) {
		if ctx.Err() != nil {
			return false
		}
		count, joinErr := m.list.Join([]string{seed})
		if joinErr != nil {
			log.Error(joinErr, "failed to join peer", "peer", seed, "joined", count)
		}
		if count > 0 {
			log.Info("successfully joined peer", "peer", seed, "count", count)
			return true
		}
	}
	return false
}

func trustedSeedAddresses(pods []corev1.Pod, localURL string, bindPort int) []string {
	seen := make(map[string]struct{}, len(pods))
	seeds := make([]string, 0, len(pods))
	for i := range pods {
		podIP := net.ParseIP(pods[i].Status.PodIP)
		if podIP == nil || podIP.To4() == nil {
			continue
		}
		podIP = podIP.To4()
		seed := net.JoinHostPort(podIP.String(), strconv.Itoa(bindPort))
		if annotated := pods[i].Annotations[agentsv1alpha1.AnnotationMemberlistURL]; annotated != "" {
			override, ok := parseMemberlistURL(annotated, podIP)
			if !ok {
				continue
			}
			seed = override
		}
		if seed == localURL {
			continue
		}
		if _, exists := seen[seed]; exists {
			continue
		}
		seen[seed] = struct{}{}
		seeds = append(seeds, seed)
	}
	sort.Strings(seeds)
	return seeds
}

// parseMemberlistURL parses the memberlist-url annotation into a seed address
// for the peer with the given Pod IP. The annotation may only override the
// port: its host must equal the Pod's status.podIP, so an annotation cannot
// redirect peer traffic outside the selected Pod identity. It returns false
// when the annotated address is invalid.
func parseMemberlistURL(annotated string, podIP net.IP) (string, bool) {
	host, port, err := net.SplitHostPort(annotated)
	if err != nil {
		return "", false
	}
	annotatedIP := net.ParseIP(host)
	if annotatedIP == nil || !annotatedIP.Equal(podIP) {
		return "", false
	}
	portNumber, err := strconv.Atoi(port)
	if err != nil || portNumber < 1 || portNumber > 65535 {
		return "", false
	}
	return net.JoinHostPort(podIP.String(), strconv.Itoa(portNumber)), true
}

func (m *MemberlistPeers) cleanup() error {
	if m.list == nil {
		return nil
	}
	var errs []error
	if err := m.list.Leave(DefaultLeaveTimeout); err != nil {
		errs = append(errs, fmt.Errorf("failed to leave memberlist: %w", err))
	}
	if err := m.list.Shutdown(); err != nil {
		errs = append(errs, fmt.Errorf("failed to shutdown memberlist: %w", err))
	}
	return errors.Join(errs...)
}

// Stop cancels peer discovery and waits for its cleanup result. It is called
// at most once and never concurrently with Start; it may still arrive before
// Start, in which case it marks the peer stopped so a later Start fails.
// Stopping a peer that never started returns nil: callers shut down whole
// components even when startup failed before Start.
func (m *MemberlistPeers) Stop(ctx context.Context) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.stopped = true
	// Nil lifecycleDone means Start never succeeded; it doubles as the
	// started marker, so there is intentionally no separate started flag.
	if m.lifecycleDone == nil {
		return nil
	}
	m.lifecycleCancel()
	select {
	case err := <-m.lifecycleDone:
		return err
	case <-ctx.Done():
		return ctx.Err()
	}
}

// GetPeers returns the current list of alive peers (excluding self)
func (m *MemberlistPeers) GetPeers() []Peer {
	if m.list == nil {
		return nil
	}

	peers := make([]Peer, 0, len(m.list.Members()))
	for _, member := range m.list.Members() {
		if member.Name == m.localName {
			continue
		}
		if member.State == memberlist.StateAlive {
			peers = append(peers, Peer{
				IP:   member.Addr.String(),
				Name: member.Name,
			})
		}
	}
	return peers
}

// GetAllMembers returns all members including self
func (m *MemberlistPeers) GetAllMembers() []Peer {
	if m.list == nil {
		return nil
	}

	members := make([]Peer, 0, len(m.list.Members()))
	for _, member := range m.list.Members() {
		members = append(members, Peer{
			IP:   member.Addr.String(),
			Name: member.Name,
		})
	}
	return members
}

// LocalAddr returns the local node's address
func (m *MemberlistPeers) LocalAddr() net.IP {
	if m.list == nil {
		return nil
	}
	return m.list.LocalNode().Addr
}

// LocalPort returns the local node's port
func (m *MemberlistPeers) LocalPort() int {
	if m.list == nil {
		return 0
	}
	return int(m.list.LocalNode().Port)
}

// LocalName returns the local node's memberlist name.
func (m *MemberlistPeers) LocalName() string {
	return m.localName
}

// eventDelegate handles memberlist membership change events
type eventDelegate struct {
	parent *MemberlistPeers
	logCtx context.Context
}

func (e *eventDelegate) NotifyJoin(node *memberlist.Node) {
	if node.Name == e.parent.localName {
		return
	}
	klog.FromContext(e.logCtx).Info("peer joined", "name", node.Name, "ip", node.Addr.String())
}

func (e *eventDelegate) NotifyLeave(node *memberlist.Node) {
	if node.Name == e.parent.localName {
		return
	}
	klog.FromContext(e.logCtx).Info("peer left", "name", node.Name, "ip", node.Addr.String())
}

func (e *eventDelegate) NotifyUpdate(*memberlist.Node) {
	// Handle metadata updates if needed in the future
}

// Ensure MemberlistPeers implements Peers
var _ Peers = (*MemberlistPeers)(nil)
