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

package openai

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"fmt"
	"strconv"
	"strings"
	"time"
)

const (
	headerWebhookID        = "Webhook-Id"
	headerWebhookTimestamp = "Webhook-Timestamp"
	headerWebhookSignature = "Webhook-Signature"
	webhookSecretPrefix    = "whsec_"
	maxWebhookSkew         = 5 * time.Minute
)

func verifyWebhookSignature(secret string, id, timestamp, signature string, body []byte) error {
	if secret == "" || id == "" || timestamp == "" || signature == "" {
		return fmt.Errorf("missing webhook signature headers")
	}
	ts, err := strconv.ParseInt(timestamp, 10, 64)
	if err != nil {
		return fmt.Errorf("invalid webhook timestamp")
	}
	if d := time.Since(time.Unix(ts, 0)); d > maxWebhookSkew || d < -maxWebhookSkew {
		return fmt.Errorf("webhook timestamp is out of range")
	}
	key, err := webhookSecretKey(secret)
	if err != nil {
		return err
	}
	mac := hmac.New(sha256.New, key)
	_, _ = mac.Write([]byte(id + "." + timestamp + "."))
	_, _ = mac.Write(body)
	expected := mac.Sum(nil)
	for _, part := range strings.Split(signature, " ") {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}
		ver, sig, ok := strings.Cut(part, ",")
		if !ok || ver != "v1" {
			continue
		}
		got, err := base64.StdEncoding.DecodeString(sig)
		if err != nil {
			got, err = hex.DecodeString(sig)
			if err != nil {
				continue
			}
		}
		if hmac.Equal(expected, got) {
			return nil
		}
	}
	return fmt.Errorf("invalid webhook signature")
}

func webhookSecretKey(secret string) ([]byte, error) {
	secret = strings.TrimSpace(secret)
	if strings.HasPrefix(secret, webhookSecretPrefix) {
		decoded, err := base64.StdEncoding.DecodeString(strings.TrimPrefix(secret, webhookSecretPrefix))
		if err != nil {
			return nil, fmt.Errorf("invalid webhook secret")
		}
		return decoded, nil
	}
	return []byte(secret), nil
}
