package adapters

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"

	"github.com/openkruise/agents/pkg/servers/e2b/keys"
	"github.com/openkruise/agents/pkg/servers/e2b/models"
)

type NativeE2BAdapter struct {
	Keys *keys.SecretKeyStorage // If nil, authentication is disabled
}

var hostRegex = regexp.MustCompile(`^(\d+)-([a-zA-Z0-9\-]+)\.`)

// Map maps authorities like 3000-sandbox1234.example.com to sandboxID=sandbox1234 and port=3000
func (a *NativeE2BAdapter) Map(_, authority, _ string, _ int, headers map[string]string) (
	sandboxID string, sandboxPort int, extraHeaders map[string]string, user string, err error) {
	matches := hostRegex.FindStringSubmatch(authority)
	if len(matches) != 3 {
		err = fmt.Errorf("invalid authority format: %s", authority)
		return sandboxID, sandboxPort, extraHeaders, user, err
	}

	// Extract port number and sandboxID
	sandboxPort, err = strconv.Atoi(matches[1])
	if err != nil {
		return sandboxID, sandboxPort, extraHeaders, user, err
	}
	sandboxID = matches[2]

	if a.Keys == nil {
		return sandboxID, sandboxPort, extraHeaders, user, err
	}

	// Parse user
	if sandboxPort == models.CDPPort || sandboxPort == models.VNCPort {
		// no auth for CDP
		user = UserNoNeedToAuth
		return sandboxID, sandboxPort, extraHeaders, user, err
	}

	token := headers["x-access-token"] // from sandbox.EnvdAccessToken
	key, ok := a.Keys.LoadByKey(token)
	if ok {
		user = key.ID.String()
	} else {
		user = UserUnknown
	}
	return sandboxID, sandboxPort, extraHeaders, user, err
}

func (a *NativeE2BAdapter) IsSandboxRequest(authority, _ string, _ int) bool {
	return !strings.HasPrefix(authority, "api.")
}
