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
	"encoding/hex"
	"fmt"
	"strings"
	"testing"

	"github.com/google/uuid"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/openkruise/agents/pkg/servers/e2b/models"
)

func TestIsE2BSDKCompatible(t *testing.T) {
	tests := []struct {
		name string
		key  string
		want bool
	}{
		{name: "e2b prefix with lowercase hex", key: "e2b_abc123", want: true},
		{name: "encoded compatible key", key: expectedE2BSDKCompatibleKey("admin-987654321"), want: true},
		{name: "missing prefix", key: "abc123", want: false},
		{name: "empty suffix", key: "e2b_", want: false},
		{name: "uppercase prefix", key: "E2B_abc123", want: false},
		{name: "uppercase hex", key: "e2b_ABC123", want: false},
		{name: "non hex suffix", key: "e2b_not-hex", want: false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.want, IsE2BSDKCompatible(tt.key))
		})
	}
}

func TestEncodeDecodeFromE2BSDKCompatible(t *testing.T) {
	tests := []struct {
		name string
		raw  string
	}{
		{name: "legacy admin key", raw: "admin-987654321"},
		{name: "uuid key", raw: uuid.MustParse("11111111-2222-3333-4444-555555555555").String()},
		{name: "empty key", raw: ""},
		{name: "utf8 key uses byte length", raw: "key-with-\xe4\xb8\xad"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			encoded := EncodeForE2BSDK(tt.raw)

			require.Equal(t, expectedE2BSDKCompatibleKey(tt.raw), encoded)
			assert.True(t, IsE2BSDKCompatible(encoded))
			assert.True(t, strings.HasPrefix(encoded, "e2b_6f6b616701"))

			decoded, ok := DecodeFromE2BSDKCompatible(encoded)
			require.True(t, ok)
			assert.Equal(t, tt.raw, decoded)
		})
	}
}

func TestDecodeFromE2BSDKCompatibleRejectsInvalidEncoding(t *testing.T) {
	valid := EncodeForE2BSDK("raw-key")
	tests := []struct {
		name string
		key  string
	}{
		{name: "raw key", key: "raw-key"},
		{name: "sdk compatible but not openkruise encoding", key: "e2b_abc123"},
		{name: "wrong magic", key: "e2b_0000000001000000077261772d6b6579" + checksumForTest("raw-key")},
		{name: "wrong version", key: strings.Replace(valid, "01", "02", 1)},
		{name: "length mismatch", key: strings.Replace(valid, "00000007", "00000008", 1)},
		{name: "checksum mismatch", key: flipLastHexForTest(valid)},
		{name: "uppercase hex", key: strings.ToUpper(valid)},
		{name: "trailing bytes", key: valid + "00"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			decoded, ok := DecodeFromE2BSDKCompatible(tt.key)
			assert.False(t, ok)
			assert.Empty(t, decoded)
		})
	}
}

func TestToStoredRawAPIKey(t *testing.T) {
	encoded := EncodeForE2BSDK("raw-key")
	tests := []struct {
		name      string
		presented string
		wantKey   string
	}{
		{name: "raw key is unchanged", presented: "raw-key", wantKey: "raw-key"},
		{name: "encoded key returns raw key", presented: encoded, wantKey: "raw-key"},
		{name: "invalid e2b key is unchanged", presented: "e2b_abc123", wantKey: "e2b_abc123"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.wantKey, ToStoredRawAPIKey(tt.presented))
		})
	}
}

func TestPresentCreatedAPIKeyReturnsCopyWithCompatibleKey(t *testing.T) {
	rawKey := "raw-admin-key"
	original := &models.CreatedTeamAPIKey{
		ID:   uuid.New(),
		Key:  rawKey,
		Name: "admin",
		Team: &models.Team{
			ID:   uuid.New(),
			Name: "team-a",
		},
		CreatedBy: &models.TeamUser{ID: uuid.New()},
	}

	presented := ConvertToE2BCompatableCreatedAPIKey(original)

	require.NotNil(t, presented)
	assert.NotSame(t, original, presented)
	assert.Equal(t, rawKey, original.Key)
	assert.Equal(t, EncodeForE2BSDK(rawKey), presented.Key)
	assert.NotSame(t, original.Team, presented.Team)
	assert.NotSame(t, original.CreatedBy, presented.CreatedBy)
}

func expectedE2BSDKCompatibleKey(raw string) string {
	rawBytes := []byte(raw)
	return fmt.Sprintf("e2b_6f6b616701%08x%s%s", len(rawBytes), hex.EncodeToString(rawBytes), checksumForTest(raw))
}

func checksumForTest(raw string) string {
	payload := append([]byte("openkruise-agents/e2b-key-compat/v1"), []byte(raw)...)
	checksum := sha256.Sum256(payload)
	return hex.EncodeToString(checksum[:8])
}

func flipLastHexForTest(value string) string {
	if value[len(value)-1] == '0' {
		return value[:len(value)-1] + "1"
	}
	return value[:len(value)-1] + "0"
}
