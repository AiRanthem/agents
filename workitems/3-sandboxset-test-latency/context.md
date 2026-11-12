# 证据与交接

## 当前事实与关系

本项 `3-sandboxset-test-latency` 为单测耗时回归的独立缺陷，`fixes` 关联已完成的 `2-sandboxset-create-consistency`。原 PR #1207 已于 `2026-11-11T09:45:12Z` 合入上游 master，合并提交为 `91274e22331bd620ce2c0173f1f97cc28d80bf4f`，本轮直接回读 GitHub 与 `git ls-remote upstream refs/heads/master` 确认。

本项源码已实现、验证并经独立 [PR #1208](https://github.com/openkruise/agents/pull/1208) 合入 master。2026-11-12 用户明确要求关闭工作项，本项登记为 `done`，完成与合并证据见末节。开发位置和基线见下节。原工作项 worktree 干净并保留，未在其中继续修复。

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

上述为登记时的原始性能证据，保留其实际输入。当前测试修复与验证如下；未将调查方向登记为已批准的正式设计。

## 实现身份与边界（2026-11-11）

- 实现者：本次 Codex 主会话。依据 `requirement.md` 的测试提速目标及工作项 2 既有生产合同，选择测试内部实现，没有新的生产设计、兼容逻辑或独立设计审批。
- 在原源码主检出保持 `develop`、成功 `git pull --ff-only` 后刷新上游；`git fetch upstream master` 成功，从当时最新的 `91274e22331bd620ce2c0173f1f97cc28d80bf4f` 建立 `fix/sandboxset-test-latency-261111`，初始 HEAD 与该提交一致。发布前再次 fetch，基线未变。
- Worktree：`/Users/sophon/Workspace/OKAWorkspace/projects/oka-daily-open-source/worktrees/3-sandboxset-test-latency`。
- 最终提交：`24e5feb24b8fe1ca4e76b4ff879c4252010d37ee`，已 sign-off、普通推送到 `airanthem`（`AiRanthem/agents`）；远端分支与本地 SHA 匹配，工作树干净。
- 完整差异为 10 个测试/测试支持文件、96 行新增和 16 行删除。核心是 `pkg/cache/cachetest/cachetest.go` 及同目录新回归测试；其余为现有测试的类型适配或明确选择真实 Cache。没有无关源码改动。

工厂现在返回嵌入真实 `*cache.Cache` 的 `cachetest.Cache`。fake client 写入本就立即可见，fake provider 的 SandboxSet 查询按原名称索引和 namespace 读取一次，保留缺失、取消和读取错误语义；其他方法及 wait tasks 沿用嵌入的真实 Cache。真实 informer 等待由现有内部测试继续验证，旧的多模板查询测试显式调用嵌入 Cache 并用 `synctest` 覆盖未命中。

没有改动生产 `pkg/cache/cache.go`、Provider 接口、5 秒窗口、CI workflow、Makefile 或覆盖率阈值。所有 `cachetest` 导入都来自测试文件；测试替身的已知上限及如何测试真实传播等待在相邻 `known-limit:` 注释中说明。

## 最终验证及效率

以下均在新 worktree、现有 Go 1.26.3 工具链运行，`-mod=readonly`；结果绑定上述最终提交。首次批量回归遇到一个显式接受 `*cache.Cache` 的测试回调编译失败；改为传入嵌入 Cache 后，只重跑受影响 Infra 包，其他已通过结果仍有效。

| 包 | 旧 PR CI（race、包串行） | 本次本地 race 验证 | 本次新 PR CI |
| --- | ---: | ---: | ---: |
| cache | 15.040s | 5.167s | 4.334s |
| sandbox-manager | 21.145s | 14.725s | 14.078s |
| sandboxcr | 151.387s | 45.501s | 46.212s |
| e2b | 262.892s | 113.689s | 112.572s |
| sandboxclaim/core | 8.508s | 3.994s | 3.018s |

不同机器的数据不是同机基准；各包已回到接近合入前 master 的执行水平。同一既有缺失模板用例本地实测从 5.05s 恢复为 0.05s，保留原 HTTP 400 及 quota 未调用断言。

实际命令与范围：

- `go test -mod=readonly -race -p 1 ./pkg/cache ./pkg/sandbox-manager ./pkg/sandbox-manager/infra/sandboxcr ./pkg/servers/e2b ./pkg/controller/sandboxclaim/core -count=1`：cache、Manager、E2B、sandboxclaim/core 均通过；Infra 最初的类型编译问题已修正。
- `go test -mod=readonly -race ./pkg/sandbox-manager/infra/sandboxcr -count=1`：修正后的完整 Infra 包通过（45.501s），无遗留失败。
- `go test -mod=readonly ./pkg/sandbox-gateway/filter ./pkg/sandbox-gateway/wake ./pkg/cache/cachetest -run '^$' -count=1` 及 `go test -mod=readonly ./pkg/controller/sandboxclaim ./pkg/utils/csiutils -run '^$' -count=1`：其余工厂消费者编译通过。这些是编译检查，不冒充行为测试。
- `go test -mod=readonly -race ./pkg/cache/cachetest -count=5 -coverprofile=.../latency-fix-helper.cover`：通过（2.999s），测试支持包语句覆盖率 77.8%。新回归用例在虚拟时间中断言 fake 命中、缺失和取消均不消耗传播等待时间。
- `go test -mod=readonly ./pkg/cache -run '^TestPickSandboxSet' -coverprofile=.../latency-fix-real-cache.cover -count=1`：通过（0.870s），真实 `PickSandboxSet` 函数语句覆盖率仍为 100.0%。
- 使用一次性 Go overlay 将 fake provider 恢复为直接调用慢的真实查询，再运行 `TestSandboxSetLookupDoesNotWait`：按预期因消耗 10 秒虚拟时间而失败（实际墙钟约 0.56s）。该负例证明新测试能抓住耗时回归，未修改仓库源码。
- `gofmt`、`git diff --check`、完整 diff 和文件分类检查通过；无生成文件或依赖变动。

以上完整输出保存在前述 `local-storage/sandboxset-create-consistency/` 下：`latency-fix-tests.log`、`latency-fix-infra.log`、`latency-fix-missing-template.jsonl`、`latency-fix-helper.cover`、`latency-fix-real-cache.cover`、`latency-fix-negative.log`。合并这些真实执行结果，不重复运行已稳定且输入未变的检查。

## 发布与剩余边界

已创建 [PR #1208](https://github.com/openkruise/agents/pull/1208)，回读确认 head 为 `24e5feb24b8fe1ca4e76b4ff879c4252010d37ee`、base 为 `master`，改动范围仅上述 10 个文件。新 [CI 单测 job](https://github.com/openkruise/agents/actions/runs/43018062168/job/130514022236) 已完成并通过，单测步骤为 `2026-11-11T12:10:46Z–12:25:30Z`，耗时 14分44秒，低于旧 PR 的 21分45秒；各包 CI 实测见上表。这是两次 CI 的观察值，完整步骤还包含编译/runner 波动，不将全部总时长差异归因于固定等待。

最终回读单测、lint、CodeQL 等检查均成功，Codecov patch 为 81.81818%、项目覆盖率为 84.95%，覆盖率门禁通过。按用户简洁优先的要求，不为其余两行未覆盖错误分支追加测试或追逐硬性 100%。CI 原始日志为前述目录下的 `latency-fix-ci.log`。

上述 CI 与覆盖率结果绑定最终源码提交 `24e5feb24b8fe1ca4e76b4ff879c4252010d37ee`。后续上游合并与用户完成决定如下；未执行 AI 独立实现审查、部署或本地清理，未运行本地 E2E。

## 完成与合并核验（2026-11-12）

用户原文：“PR 合入了，关闭工作项”。直接回读 GitHub 确认 PR #1208 为 MERGED，合并时间 `2026-11-12T03:00:13Z`，目标为 `master`，最终 head 仍为已验证的 `24e5feb24b8fe1ca4e76b4ff879c4252010d37ee`，合并提交为 `2a13009e64e44da79a2b5b4de3eb3262fd6e6294`。同时执行 `git ls-remote upstream refs/heads/master`，上游引用与该合并提交相同。

生产合同未变、单测效率恢复、本地及 CI 验证、独立 PR 与源码交付证据均保留；依据用户的实际关闭决定，本项登记 `done`。用户完成决定与未执行的 AI 独立审查分别记录，不将交付推导为生产部署或现场验证。当前 worktree 干净，未进行源码修改、清理或分支删除。
