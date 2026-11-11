# 证据与交接

## 当前事实与关系

本项 `3-sandboxset-test-latency` 为单测耗时回归的独立缺陷，`fixes` 关联已完成的 `2-sandboxset-create-consistency`。原 PR #1207 已于 `2026-11-11T09:45:12Z` 合入上游 master，合并提交为 `91274e22331bd620ce2c0173f1f97cc28d80bf4f`，本轮直接回读 GitHub 与 `git ls-remote upstream refs/heads/master` 确认。

当前没有本项开发分支或 worktree；正式设计、修复实现和新 PR 尚未开始。合并提交只是登记时的上游快照，创建分支前仍须重新执行项目规定的 fetch 和基线核验。原工作项 worktree 干净并保留，未在其中继续修复。

## CI 耗时对照

使用同一 `CI` workflow、`ubuntu-24.04` runner label；原 PR 未修改 `.github/workflows/ci.yaml` 或 `Makefile`。CI 的 `make test` 执行 `go test -race -p 1 ./pkg/... -coverprofile raw-cover.out`，包串行运行，重复真实等待会累加。不同 runner 的完整步骤耗时不构成严格同机基准，下面的包级和 A/B 证据用于补强归因。

| 观察 | 合入前 master 基线 | 原 PR 首版 | 原 PR 最终 head |
| --- | ---: | ---: | ---: |
| 源码提交 | `3d9af5799d873e278cbfcb8871a0d0a3ec726447` | `d1c59b668ccff1ea9ae03e7dcc016ccaaf0d4037` | `441ac6702e53b37ed9acb611ace8b1147dafbdb5` |
| 单测步骤 | 17分02秒 | 20分27秒 | 21分45秒 |
| E2B 包 | 118.184s | 260.851s | 262.892s |
| sandboxcr 包 | 51.345s | 150.042s | 151.387s |
| cache 包 | 4.784s | 14.671s | 15.040s |
| Manager 包 | 15.153s | 20.085s | 21.145s |
| sandboxclaim/core 包 | 3.495s | 8.257s | 8.508s |

原始 CI：

- [master 基线单测 job](https://github.com/openkruise/agents/actions/runs/42497282149/job/128782242365)，单测步骤 `2026-11-08T15:56:23Z–16:13:25Z`。
- [相邻 master 对照](https://github.com/openkruise/agents/actions/runs/42496965281/job/128781272785)，提交 `010f806f32934c67e10323780c5a0767b29737e7`，单测步骤 17分06秒；E2B 118.136s、sandboxcr 50.658s、cache 4.808s。
- [原 PR 首版单测 job](https://github.com/openkruise/agents/actions/runs/42987665443/job/130412618501)。
- [原 PR 最终 head 单测 job](https://github.com/openkruise/agents/actions/runs/42992257580/job/130427716743)，单测步骤 `2026-11-11T09:06:07Z–09:27:52Z`。

最终 PR 相对基线单测步骤增加 4分43秒，包执行时间之和由 389.115s 增至 656.450s，增加 267.335s；主要增量为 E2B 144.708s、sandboxcr 100.042s。明显增量在原 PR 首版已经出现，最后只补覆盖率的提交不是主要来源。不能用“同一 PR 前后仅差约 1 分钟”排除相对 master 的回归。

## 单用例 A/B 与原因

本轮之前已对既有 `TestCreateSandbox_TopLevelMissingTemplateOrCheckpointReturns400` 作只读 Go overlay A/B：其他输入保持相同，只将构建输入 `pkg/cache/cache.go` 替换为合入前 master 的实现。

- master 查询实现：pass，0.05s。
- PR 查询实现：pass，5.05s。

两边执行 `go test -mod=readonly -json ./pkg/servers/e2b -run '^TestCreateSandbox_TopLevelMissingTemplateOrCheckpointReturns400$' -count=1`，master 对照另带 `-overlay=.../cache-master-overlay.json`；未修改仓库源码。该用例新增恰好 5 秒，结合包耗时与生产差异，确认原本只需判断缺失的测试反复等待缓存传播窗口，构成已引入的耗时回归，不是测试卡死。需要在测试职责处修复，保持生产合同和必要验证。

## 证据文件及实现导航

原始文件位于 `/Users/sophon/Workspace/OKAWorkspace/local-storage/sandboxset-create-consistency/`：

- `master-3d9af57-unit.log`、`master-010f806-unit.log`、`pr-d1c59b6-unit.log`、`unit-441ac6702.log`：完整 CI 日志，含包耗时。
- `ab-master.jsonl`、`ab-pr.jsonl`：单用例 A/B 原始输出。
- `cache-master-overlay.json`、`cache-master.go`：A/B 构建输入快照，不是开发分支。

源码导航（原 PR 最终 head，仅作为下一轮调查起点）：

- `pkg/cache/cache.go` 的 `PickSandboxSet`：每次查询最多 5 秒，普通空结果轮询，最终再查一次缓存。
- `pkg/cache/cache_internal_test.go`：已有 `testing/synctest` 等待、取消、错误与独立调用验证；无需为提速削弱这些断言。
- `pkg/cache/cachetest/cachetest.go`：复用 fake client 的测试 cache 工厂；`pkg/cache/controllers/test_helpers.go` 提供 MockManager 和 wait simulation。
- `pkg/servers/e2b/core_test.go`、`pkg/sandbox-manager/infra/sandboxcr/infra_test.go`：上层测试初始化；`pkg/cache/cache_test.go` 有会触发未命中等待的既有用例。

本轮登记原工作项完成及本项需求，没有源码写入或新增实现验证。此前修复调查仍处于读取上下文阶段，已有修复请求和另提 PR 的要求作为本项后续任务保留；不把调查方向登记为已批准设计或已实施修复。
