package adapters

import (
	"fmt"
	"strings"

	"github.com/openkruise/agents/pkg/servers/e2b/keys"
)

var (
	UserNoNeedToAuth = "<port-no-need-to-auth>"
	UserUnknown      = "<unknown>"
)

// E2BMapper is part of proxy.RequestAdapter
type E2BMapper interface {
	Map(scheme, authority, path string, port int, headers map[string]string) (
		sandboxID string, sandboxPort int, extraHeaders map[string]string, user string, err error)
	IsSandboxRequest(authority, path string, port int) bool
}

type E2BAdapter struct {
	Keys       *keys.SecretKeyStorage
	Port       int
	native     *NativeE2BAdapter
	customized *CustomizedE2BAdapter
}

func NewE2BAdapter(port int, keys *keys.SecretKeyStorage) *E2BAdapter {
	return &E2BAdapter{
		Keys:       keys,
		Port:       port,
		native:     &NativeE2BAdapter{Keys: keys},
		customized: &CustomizedE2BAdapter{Keys: keys},
	}
}

func (a *E2BAdapter) Map(scheme, authority, path string, port int, headers map[string]string) (
	sandboxID string, sandboxPort int, extraHeaders map[string]string, user string, err error) {
	return a.ChooseAdapter(path).Map(scheme, authority, path, port, headers)
}

func (a *E2BAdapter) Authorize(user, owner string) bool {
	if a.Keys == nil {
		return true
	}
	return user == owner || user == UserNoNeedToAuth
}

func (a *E2BAdapter) IsSandboxRequest(authority, path string, port int) bool {
	return a.ChooseAdapter(path).IsSandboxRequest(authority, path, port)
}

func (a *E2BAdapter) Entry() string {
	return fmt.Sprintf("127.0.0.1:%d", a.Port)
}

func (a *E2BAdapter) ChooseAdapter(path string) E2BMapper {
	if strings.HasPrefix(path, CustomPrefix) {
		return a.customized
	}
	return a.native
}
