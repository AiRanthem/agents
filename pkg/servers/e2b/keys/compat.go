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

package keys

import (
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"fmt"
	"regexp"
	"strconv"
	"strings"

	"github.com/openkruise/agents/pkg/servers/e2b/models"
)

const (
	e2bSDKPrefix             = "e2b_"
	e2bSDKCompatMagic        = "6f6b6167"
	e2bSDKCompatVersion      = "01"
	e2bSDKCompatChecksumSalt = "openkruise-agents/e2b-key-compat/v1"
	e2bSDKCompatLengthSize   = 8
	e2bSDKCompatChecksumSize = 16
)

var e2bSDKCompatiblePattern = regexp.MustCompile(`^e2b_[0-9a-f]+$`)

// IsE2BSDKCompatible returns whether an API key satisfies the E2B SDK format.
func IsE2BSDKCompatible(apiKey string) bool {
	return e2bSDKCompatiblePattern.MatchString(apiKey)
}

// EncodeForE2BSDK wraps a raw OpenKruise Agents API key in an E2B SDK-compatible form.
// Callers must pass a regular API key (UUID or admin key, well under 4 GB). Inputs
// larger than 4 GB would overflow the 8-hex-character length field; such inputs are
// not produced by any backend in this project, so the function does not guard for them.
func EncodeForE2BSDK(raw string) string {
	rawBytes := []byte(raw)
	return fmt.Sprintf("%s%s%s%08x%s%s",
		e2bSDKPrefix,
		e2bSDKCompatMagic,
		e2bSDKCompatVersion,
		len(rawBytes),
		hex.EncodeToString(rawBytes),
		e2bSDKCompatChecksum(rawBytes),
	)
}

// DecodeFromE2BSDKCompatible decodes an OpenKruise Agents-compatible E2B SDK key.
func DecodeFromE2BSDKCompatible(apiKey string) (string, bool) {
	if !IsE2BSDKCompatible(apiKey) {
		return "", false
	}

	payload := strings.TrimPrefix(apiKey, e2bSDKPrefix)
	headerSize := len(e2bSDKCompatMagic) + len(e2bSDKCompatVersion) + e2bSDKCompatLengthSize
	minPayloadSize := headerSize + e2bSDKCompatChecksumSize
	if len(payload) < minPayloadSize {
		return "", false
	}
	if !strings.HasPrefix(payload, e2bSDKCompatMagic+e2bSDKCompatVersion) {
		return "", false
	}

	lengthHexStart := len(e2bSDKCompatMagic) + len(e2bSDKCompatVersion)
	lengthHexEnd := lengthHexStart + e2bSDKCompatLengthSize
	rawLength, err := strconv.ParseUint(payload[lengthHexStart:lengthHexEnd], 16, 32)
	if err != nil {
		return "", false
	}
	maxInt := int(^uint(0) >> 1)
	rawHexStart := lengthHexEnd
	// Guard against int overflow on 32-bit systems: rawHexStart + int(rawLength)*2 + checksumSize must fit in int.
	// Which is nearly impossible given the 4 GB limit on rawLength, but let's be strict.
	if rawLength > uint64((maxInt-rawHexStart-e2bSDKCompatChecksumSize)/2) {
		return "", false
	}

	rawHexEnd := rawHexStart + int(rawLength)*2
	checksumEnd := rawHexEnd + e2bSDKCompatChecksumSize
	if len(payload) != checksumEnd {
		return "", false
	}

	rawBytes, err := hex.DecodeString(payload[rawHexStart:rawHexEnd])
	if err != nil || len(rawBytes) != int(rawLength) {
		return "", false
	}
	checksum := e2bSDKCompatChecksum(rawBytes)
	if subtle.ConstantTimeCompare([]byte(payload[rawHexEnd:checksumEnd]), []byte(checksum)) != 1 {
		return "", false
	}
	return string(rawBytes), true
}

// ToStoredRawAPIKey returns the raw key that storage should use for lookup.
// If apiKey is a valid OpenKruise-compatible encoded key, the decoded raw key is
// returned; otherwise the input is returned unchanged.
func ToStoredRawAPIKey(apiKey string) string {
	if rawKey, ok := DecodeFromE2BSDKCompatible(apiKey); ok {
		return rawKey
	}
	return apiKey
}

// ConvertToE2BCompatableCreatedAPIKey returns a response copy with Key encoded for the E2B SDK.
func ConvertToE2BCompatableCreatedAPIKey(apiKey *models.CreatedTeamAPIKey) *models.CreatedTeamAPIKey {
	presented := cloneCreatedTeamAPIKey(apiKey)
	if presented == nil {
		return nil
	}
	presented.Key = EncodeForE2BSDK(apiKey.Key)
	return presented
}

func e2bSDKCompatChecksum(raw []byte) string {
	payload := append([]byte(e2bSDKCompatChecksumSalt), raw...)
	checksum := sha256.Sum256(payload)
	return hex.EncodeToString(checksum[:8])
}
