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

package quota

import (
	"context"
	"errors"
	"fmt"
	"strconv"
	"time"

	"github.com/redis/go-redis/v9"
)

const (
	defaultAcquireTimeout              = 50 * time.Millisecond
	defaultMaintenanceOperationTimeout = 30 * time.Second

	acquireScript = `
if redis.call('HEXISTS', KEYS[1], ARGV[1]) == 1 then return 'OK' end
local lim = tonumber(ARGV[2])
if lim == 0 then return 'REJECTED' end
if lim > 0 and redis.call('HLEN', KEYS[1]) + 1 > lim then return 'REJECTED' end
redis.call('HSET', KEYS[1], ARGV[1], redis.call('TIME')[1])
return 'OK'
`

	releaseScript = `
return redis.call('HDEL', KEYS[1], ARGV[1])
`
)

var (
	redisAcquireScript    = redis.NewScript(acquireScript)
	redisReleaseScript    = redis.NewScript(releaseScript)
	errNilRedisClient     = errors.New("redis client is nil")
	errUnexpectedLuaReply = errors.New("unexpected quota lua reply")
)

type RedisBackend struct {
	client  *redis.Client
	timeout time.Duration
}

func NewRedisBackend(client *redis.Client, timeout time.Duration) *RedisBackend {
	if timeout <= 0 {
		timeout = defaultAcquireTimeout
	}
	return &RedisBackend{
		client:  client,
		timeout: timeout,
	}
}

func (b *RedisBackend) Acquire(ctx context.Context, apiKeyID, lockString string, limit int64) error {
	if b == nil || b.client == nil {
		backendErrorsTotal.WithLabelValues(backendOperationAcquire).Inc()
		return fmt.Errorf("%w: %v", ErrBackendUnavailable, errNilRedisClient)
	}

	ctx, cancel := context.WithTimeout(ctx, b.timeout)
	defer cancel()

	result, err := redisAcquireScript.Run(ctx, b.client, []string{liveKey(apiKeyID)}, lockString, strconv.FormatInt(limit, 10)).Result()
	if err != nil {
		backendErrorsTotal.WithLabelValues(backendOperationAcquire).Inc()
		return fmt.Errorf("%w: %v", ErrBackendUnavailable, err)
	}

	switch result {
	case "OK":
		return nil
	case "REJECTED":
		return ErrQuotaExceeded
	default:
		return fmt.Errorf("%w: %v", errUnexpectedLuaReply, result)
	}
}

func (b *RedisBackend) Release(ctx context.Context, apiKeyID, lockString string) error {
	if b == nil || b.client == nil {
		releaseTotal.WithLabelValues(releaseResultError).Inc()
		backendErrorsTotal.WithLabelValues(backendOperationRelease).Inc()
		return fmt.Errorf("%w: %v", ErrBackendUnavailable, errNilRedisClient)
	}

	ctx, cancel := maintenanceContext(ctx)
	defer cancel()

	result, err := redisReleaseScript.Run(ctx, b.client, []string{liveKey(apiKeyID)}, lockString).Result()
	if err != nil {
		releaseTotal.WithLabelValues(releaseResultError).Inc()
		backendErrorsTotal.WithLabelValues(backendOperationRelease).Inc()
		return fmt.Errorf("%w: %v", ErrBackendUnavailable, err)
	}

	removed, err := redisInt64(result)
	if err != nil {
		releaseTotal.WithLabelValues(releaseResultError).Inc()
		return err
	}
	if removed > 0 {
		releaseTotal.WithLabelValues(releaseResultReleased).Inc()
		return nil
	}

	releaseTotal.WithLabelValues(releaseResultNoop).Inc()
	return nil
}

func (b *RedisBackend) AddObserved(ctx context.Context, apiKeyID, lockString string, acquiredAt time.Time) error {
	if b == nil || b.client == nil {
		backendErrorsTotal.WithLabelValues(backendOperationAddObserved).Inc()
		return fmt.Errorf("%w: %v", ErrBackendUnavailable, errNilRedisClient)
	}

	ctx, cancel := maintenanceContext(ctx)
	defer cancel()

	if err := b.client.HSet(ctx, liveKey(apiKeyID), lockString, acquiredAt.Unix()).Err(); err != nil {
		backendErrorsTotal.WithLabelValues(backendOperationAddObserved).Inc()
		return fmt.Errorf("%w: %v", ErrBackendUnavailable, err)
	}
	return nil
}

func (b *RedisBackend) List(ctx context.Context, apiKeyID string) (map[string]time.Time, error) {
	if b == nil || b.client == nil {
		backendErrorsTotal.WithLabelValues(backendOperationList).Inc()
		return nil, fmt.Errorf("%w: %v", ErrBackendUnavailable, errNilRedisClient)
	}

	ctx, cancel := maintenanceContext(ctx)
	defer cancel()

	entries, err := b.client.HGetAll(ctx, liveKey(apiKeyID)).Result()
	if err != nil {
		backendErrorsTotal.WithLabelValues(backendOperationList).Inc()
		return nil, fmt.Errorf("%w: %v", ErrBackendUnavailable, err)
	}

	result := make(map[string]time.Time, len(entries))
	for lockString, rawUnix := range entries {
		acquiredAtUnix, err := strconv.ParseInt(rawUnix, 10, 64)
		if err != nil {
			return nil, fmt.Errorf("parse acquire timestamp for lockstring %q: %w", lockString, err)
		}
		result[lockString] = time.Unix(acquiredAtUnix, 0)
	}
	return result, nil
}

func (b *RedisBackend) DeleteSubject(ctx context.Context, apiKeyID string) error {
	if b == nil || b.client == nil {
		backendErrorsTotal.WithLabelValues(backendOperationDeleteSubject).Inc()
		return fmt.Errorf("%w: %v", ErrBackendUnavailable, errNilRedisClient)
	}

	ctx, cancel := maintenanceContext(ctx)
	defer cancel()

	if err := b.client.Del(ctx, liveKey(apiKeyID)).Err(); err != nil {
		backendErrorsTotal.WithLabelValues(backendOperationDeleteSubject).Inc()
		return fmt.Errorf("%w: %v", ErrBackendUnavailable, err)
	}
	return nil
}

func liveKey(apiKeyID string) string {
	return "q:live:{" + apiKeyID + "}"
}

func maintenanceContext(ctx context.Context) (context.Context, context.CancelFunc) {
	if _, ok := ctx.Deadline(); ok {
		return ctx, func() {}
	}
	return context.WithTimeout(ctx, defaultMaintenanceOperationTimeout)
}

func redisInt64(result interface{}) (int64, error) {
	switch value := result.(type) {
	case int64:
		return value, nil
	case int:
		return int64(value), nil
	case uint64:
		if value > uint64(^uint64(0)>>1) {
			return 0, fmt.Errorf("redis integer result overflows int64: %d", value)
		}
		return int64(value), nil
	default:
		return 0, fmt.Errorf("unexpected redis integer result %T: %v", result, result)
	}
}
