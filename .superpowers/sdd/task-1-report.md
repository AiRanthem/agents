# Task 1 Report: Data layer — model + key-store persistence + validation + wire JSON

## Status
DONE_WITH_CONCERNS

## Commit
- `bbef19a7` `feat(quota): rewrite data model + key-store persistence to (dimension, scope)`

## Implementation
Implemented the Task 1 data/key-store rewrite to the `(dimension, scope)` quota model.

### What changed
- Rewrote `pkg/servers/e2b/models/quota.go`:
  - replaced count-only/public-specific model with internal `QuotaSpec{Limits []QuotaLimit}`
  - added dimensions `sandbox.count`, `limits.cpu`, `limits.memory`
  - added scopes `all`, `running`
  - added `NormalizeQuotaSpec`, `DecodeQuotaSpec`, `MarshalQuotaSpec`, `QuotaSpecFromWire`, `WireFromQuotaSpec`, `IsLimited`, `LimitedPairs`, `DeepCopy`
  - validation now rejects negative limits, duplicate `(dimension, scope)`, unsupported dimensions, and unsupported scopes
- Migrated `pkg/servers/e2b/models/api_key.go`:
  - request/response `Quota` fields now use `json.RawMessage`
  - `CreatedTeamAPIKey.MarshalJSON()` now emits the nested wire JSON via `WireFromQuotaSpec`
- Migrated Secret key storage in `pkg/servers/e2b/keys/secret.go`:
  - storage still persists internal normalized quota JSON via `MarshalQuotaSpec` / `DecodeQuotaSpec`
  - in-memory/public `Quota` field now uses `WireFromQuotaSpec`
- Migrated MySQL key storage in `pkg/servers/e2b/keys/mysql.go`:
  - same persistence split as Secret storage
  - all returned/cached API-key models now expose nested wire JSON in `Quota`
- Rewrote/updated tests in:
  - `pkg/servers/e2b/models/quota_test.go`
  - `pkg/servers/e2b/keys/secret_test.go`
  - `pkg/servers/e2b/keys/mysql_test.go`
  - removed count-only assumptions and replaced them with multi-dimension, multi-scope assertions
- Updated docs in:
  - `config/sandbox-manager/README.md`
  - `config/sandbox-manager/README_zh-CH.md`
  - quota section now documents nested wire JSON and normalized persistence shape

## RED / GREEN TDD Evidence

### RED
Command:
```bash
GOCACHE=/private/tmp/go-build-cache go test ./pkg/servers/e2b/models/ ./pkg/servers/e2b/keys/ -run 'Quota' -v
```

Relevant output:
```text
# github.com/openkruise/agents/pkg/servers/e2b/models [github.com/openkruise/agents/pkg/servers/e2b/models.test]
pkg/servers/e2b/models/quota_test.go:41:16: undefined: ScopeAll
pkg/servers/e2b/models/quota_test.go:60:16: undefined: DimLimitsCPU
...
# github.com/openkruise/agents/pkg/servers/e2b/keys [github.com/openkruise/agents/pkg/servers/e2b/keys.test]
pkg/servers/e2b/keys/mysql_test.go:533:22: undefined: models.QuotaSpecFromWire
...
FAIL	github.com/openkruise/agents/pkg/servers/e2b/models [build failed]
FAIL	github.com/openkruise/agents/pkg/servers/e2b/keys [build failed]
```

Interpretation:
- failure was expected
- tests failed because the new `(dimension, scope)` API and wire helpers did not exist yet

### GREEN
Command:
```bash
GOCACHE=/private/tmp/go-build-cache go test ./pkg/servers/e2b/models/ ./pkg/servers/e2b/keys/ -run 'Quota' -v
```

Relevant output:
```text
=== RUN   TestNormalizeQuotaSpec
--- PASS: TestNormalizeQuotaSpec (0.00s)
=== RUN   TestQuotaSpecWireRoundTrip
--- PASS: TestQuotaSpecWireRoundTrip (0.00s)
=== RUN   TestMarshalCreatedTeamAPIKeyQuotaUsesWireJSON
--- PASS: TestMarshalCreatedTeamAPIKeyQuotaUsesWireJSON (0.00s)
PASS
ok  	github.com/openkruise/agents/pkg/servers/e2b/models	0.678s
...
=== RUN   TestMySQL_QuotaMarshalAndLimitedList
--- PASS: TestMySQL_QuotaMarshalAndLimitedList (0.00s)
=== RUN   TestMySQL_ListByOwnerTeamIncludesQuota
--- PASS: TestMySQL_ListByOwnerTeamIncludesQuota (0.00s)
=== RUN   TestSecretKeyStorage_QuotaPersistenceAndLimitedList
--- PASS: TestSecretKeyStorage_QuotaPersistenceAndLimitedList (0.00s)
PASS
ok  	github.com/openkruise/agents/pkg/servers/e2b/keys	(cached)
```

Formatting command:
```bash
gofmt -w pkg/servers/e2b/models/quota.go pkg/servers/e2b/models/api_key.go pkg/servers/e2b/models/quota_test.go pkg/servers/e2b/keys/secret.go pkg/servers/e2b/keys/mysql.go pkg/servers/e2b/keys/secret_test.go pkg/servers/e2b/keys/mysql_test.go
if command -v goimports >/dev/null 2>&1; then goimports -w ...; fi
```

## Files Changed
- `pkg/servers/e2b/models/quota.go`
- `pkg/servers/e2b/models/api_key.go`
- `pkg/servers/e2b/models/quota_test.go`
- `pkg/servers/e2b/keys/secret.go`
- `pkg/servers/e2b/keys/mysql.go`
- `pkg/servers/e2b/keys/secret_test.go`
- `pkg/servers/e2b/keys/mysql_test.go`
- `config/sandbox-manager/README.md`
- `config/sandbox-manager/README_zh-CH.md`

## Self-review
- Scope stayed inside the owned write set plus the required report file.
- Persistence format remains the internal normalized `limits` list for Secret/MySQL.
- Public/request/response shape is now nested raw JSON, not the old count-only struct.
- Old no-quota payloads still decode as unlimited.
- Invalid persisted quota payloads still degrade to unlimited in key storage, with logs.
- No migration shim was added for the old unreleased count-only internal shape, matching the brief.

## Concerns
- The GREEN run includes expected error logs from invalid-payload tests in Secret/MySQL; tests pass, but the log noise remains by design.
- Per task brief, only the data/key-store layer was updated and verified. Later quota/e2b packages may still need follow-up adaptation outside this task.

## Task 1 follow-up fix: Critical + Important findings

### Review findings fixed
- Critical: malformed persisted quota payloads in Secret/MySQL no longer degrade to unlimited. Secret refresh rejects the bad key from in-memory indexes, Secret `ListLimited` now returns an error, and MySQL load/list paths now return an error for malformed stored quota. Nil or missing quota still stays unlimited.
- Important: `models.CreatedTeamAPIKey.Quota` remains the single marshal boundary. Response construction still sets `Quota = WireFromQuotaSpec(normalized)`, but `CreatedTeamAPIKey` marshal no longer rebuilds quota from `QuotaSpec`.

### RED
Command:
```bash
GOCACHE=/private/tmp/go-build-cache go test ./pkg/servers/e2b/models/ ./pkg/servers/e2b/keys/ -run 'Quota|APIKey' -v
```
Relevant output:
```text
--- FAIL: TestMarshalCreatedTeamAPIKeyQuotaKeepsExistingRawMessage
json: error calling MarshalJSON for type models.CreatedTeamAPIKey: unsupported quota dimension "limits.gpu"
...
E... mysql.go:367] "failed to decode api-key quota from db, treat key as unlimited"
Error: An error is expected but got nil.
...
E... secret.go:234] "failed to decode api-key quota, treat key as unlimited"
Error: Should be false
FAIL
```

### GREEN
Command:
```bash
GOCACHE=/private/tmp/go-build-cache go test ./pkg/servers/e2b/models/ ./pkg/servers/e2b/keys/ -run 'Quota|APIKey' -v
```
Relevant output:
```text
=== RUN   TestMarshalCreatedTeamAPIKeyQuotaKeepsExistingRawMessage
--- PASS: TestMarshalCreatedTeamAPIKeyQuotaKeepsExistingRawMessage (0.00s)
...
=== RUN   TestMySQL_InvalidQuotaPayloadIsRejected
--- PASS: TestMySQL_InvalidQuotaPayloadIsRejected (0.00s)
...
=== RUN   TestSecretKeyStorage_InvalidQuotaPayloadIsRejected
--- PASS: TestSecretKeyStorage_InvalidQuotaPayloadIsRejected (0.00s)
PASS
ok   github.com/openkruise/agents/pkg/servers/e2b/models
ok   github.com/openkruise/agents/pkg/servers/e2b/keys
```

Formatting command:
```bash
gofmt -w pkg/servers/e2b/models/api_key.go pkg/servers/e2b/models/quota.go pkg/servers/e2b/models/quota_test.go pkg/servers/e2b/keys/secret.go pkg/servers/e2b/keys/mysql.go pkg/servers/e2b/keys/secret_test.go pkg/servers/e2b/keys/mysql_test.go
if command -v goimports >/dev/null 2>&1; then goimports -w pkg/servers/e2b/models/api_key.go pkg/servers/e2b/models/quota.go pkg/servers/e2b/models/quota_test.go pkg/servers/e2b/keys/secret.go pkg/servers/e2b/keys/mysql.go pkg/servers/e2b/keys/secret_test.go pkg/servers/e2b/keys/mysql_test.go; fi
```

### Files changed
- `pkg/servers/e2b/models/api_key.go`
- `pkg/servers/e2b/models/quota.go`
- `pkg/servers/e2b/models/quota_test.go`
- `pkg/servers/e2b/keys/secret.go`
- `pkg/servers/e2b/keys/mysql.go`
- `pkg/servers/e2b/keys/secret_test.go`
- `pkg/servers/e2b/keys/mysql_test.go`
- `.superpowers/sdd/task-1-report.md`

### Self-review
- Kept the diff inside the owned write set.
- Removed the double quota boundary by deleting marshal-time quota rebuilding from `CreatedTeamAPIKey`.
- Tightened stored-quota decoding so non-`limits` persisted shapes now fail loudly instead of silently becoming unlimited.
- Preserved the intended unlimited behavior only for nil or missing stored quota.
- Secret behavior is intentionally asymmetric: refresh rejects malformed keys from indexes, while `ListLimited` returns an explicit error because that API already has an error channel.
