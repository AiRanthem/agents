# 当前证据与交接

## 设计及阶段

正式设计为 `spec.md` v1，用户已批准，并于 2026-11-11 通过完整独立设计审查，状态为 `implementable`，见 [records/design-review.md](records/design-review.md)。实现完成后，用户明确表示“人工审查通过，帮我创建 PR”。当前源码已提交、推送并创建 PR #1207；AI 独立实现审查未执行，人工结论单独记录。设计正文未改，尚未进行现场运行时复现。

编号 `1-gateway-wakeup-lifecycle` 已发布后迁出本项目，保留其编号，本项使用此前未占用的 `2-sandboxset-create-consistency`。这是针对用户报告的问题建立的独立缺陷工作项；尚未确定对应的原始交付工作项，故 `fixes` 保持空列表，不推测关联。

## 源码证据索引

分析阶段已在 `/Users/sophon/Workspace/OKAWorkspace/agents` 的干净 `develop` 主检出执行成功的 `git pull --ff-only`，得到 `7b86412bf14373963c648a7ceed91d91b5c02ceb`，并成功 `git fetch upstream master`，取得开源分析快照 `3d9af5799d873e278cbfcb8871a0d0a3ec726447`。后续设计讨论核对的 HEAD 与上述值一致。

主会话比较了相关文件与该上游快照：cache、Manager、sandboxcr 核心链路一致；`create.go` 的差异位于无关的 clone storage hook。本记录中的源码行号对应分析时检出，仅作导航，应结合提交读取原文。

| 原文位置 | 已核实事实 |
| --- | --- |
| `pkg/cache/cache.go:395`，`PickSandboxSet` | 通过 informer 客户端的名称索引 List 查询 SandboxSet，未命中立即失败；使用 `indexGetGroup` 合并瞬时查询。 |
| `pkg/cache/interface.go:36`，`Provider` | Get/List 方法只读进程内 informer store；本项保留这一合同。 |
| `pkg/cache/cache.go:162`，`BuildCacheConfig` | Sandbox-family 对象受配置的 namespace 与 label selector 过滤。 |
| `pkg/sandbox-manager/infra/sandboxcr/infra.go:343`，`HasTemplate` | 调用 `PickSandboxSet`，以 `err == nil` 返回 bool。 |
| `pkg/servers/e2b/create.go:103`，`CreateSandbox` | 先检查 SandboxSet，再检查 checkpoint；均未命中时返回 HTTP 400 和 `Template or Checkpoint not found`。 |
| `pkg/sandbox-manager/api.go:141`，`ClaimSandbox` | 在调用 Infra claim 前再次执行 `HasTemplate`。 |
| `pkg/sandbox-manager/infra/sandboxcr/claim.go:636`、`:951` | 库存 revision 优选及冷启动通过同一个 `PickSandboxSet` 查询。 |
| `pkg/servers/e2b/templates.go:101`、`:137` | 模板 GET 和模板删除判定也复用 SandboxSet 查询链，属于已说明的等待延迟影响范围。 |
| `pkg/servers/e2b/sandbox.go:110`，`getNamespaceOfUser` | 普通 team 使用 team 名作为 namespace，管理员使用空 namespace 保持跨 namespace 查询。 |
| `pkg/servers/e2b/keys/utils.go:25`、`pkg/servers/e2b/routes.go:138` | 旧 key 及关闭鉴权的匿名请求均可能采用管理员范围。 |
| `pkg/cache/index.go:116`，`IndexTemplateID` | SandboxSet 模板 ID 索引使用 `metadata.name`。 |
| `pkg/cache/tasks.go:34`，`SandboxUpdateFunc` | 现有部分等待 helper 经 `GetFromInformerOrApiServer` 隐式回源；不能直接用于本项的纯 informer 等待。 |

旁路调用方、命名和 namespace 证据由 Luna（`gpt-6-luna / high`，任务 `01a1c894-b75a-7da1-820b-c21521e0a4b1`）只读枚举；主会话直接检查关键链路并负责设计。该证据收集任务不是独立设计评审。

## 设计完整性反思

已覆盖首次命中、窗口内传播、持续未命中、提前取消或超时、读取错误、并发请求的独立有效期、namespace 与 selector 边界、同名 checkpoint 分支，以及共用方法的 GET 和删除延迟影响。将单次 5 秒窗口与整个创建期限分开，避免不实的端到端上限承诺。Ref 场景遵照用户决定排除；不向上扩展接口或错误协议。

原作者反思认为当前合同没有未决的阻塞设计问题；接受有限窗口不能保证任意延迟下成功，以及共用调用方的未命中延迟。作者反思本身不是独立 Pass；本轮独立结论及其源码依据单列在审查报告中。未查询现场集群和请求日志，用户报告的现场原因与延迟分布未进行运行时验证。

## 项目文档验证

2026-11-11 使用主工作区 `.venv/bin/python` 和 PyYAML 完成检查：工作项与状态文件的 ID、版本和阶段状态一致，文档路由及本地链接存在，正式设计具备三个约定主章节，所有本轮文件无行尾空白且以换行结尾。设计、实现、人工验收和源码交付状态没有混淆。另执行 `git diff --check`，通过。

审查输入 `spec.md` v1 的 SHA-256 为 `70cb9eee36a6db9a56b57554d1556303573bd9cb933055d4d4ca90904776cd46`；只登记 `design_status: implementable` 后为 `d2e50ca6a0b1c4561d38477f30a65838302572f629b30fd5e238eef75b0ca49a`。独立报告绑定这两个身份，正文不变。审查时再次成功 pull 并 fetch，源码基线仍为上文提交，远端 master 已直接核验；没有执行业务代码测试或 E2E。

## 后续边界

设计独立评审已通过，当前状态为 `implementable`。实现与人工审查依据见下节。fake client 测试不能证明真实 informer 传播延迟；人工代码审查通过不代表线上运行时验收。

源码 push 和 PR 创建已获授权并完成，当前 PR 未合并，部署和运行时 E2E 结果尚未发生。项目配置没有外部同步后端，不创建或发送外部系统工作项与消息。

## 实现身份与行为（2026-11-11）

实现者为本次 Codex 主会话；本会话的逐函数自检不构成独立实现审查。

- 源码仓库：OpenKruise Agents；主检出保持干净的 `develop`。本轮成功 `git pull --ff-only` 后主检出仍为 `7b86412bf14373963c648a7ceed91d91b5c02ceb`。
- 本轮核验 upstream 地址、成功 `git fetch upstream master`，从 `3d9af5799d873e278cbfcb8871a0d0a3ec726447` 创建分支 `fix/sandboxset-cache-wait-261111`，初始 HEAD 与基线一致；后续 `git ls-remote upstream refs/heads/master` 核验仍相同。
- 实际 worktree：`/Users/sophon/Workspace/OKAWorkspace/projects/oka-daily-open-source/worktrees/2-sandboxset-create-consistency`。当前 HEAD 为 `441ac6702e53b37ed9acb611ace8b1147dafbdb5`，工作树干净。
- 相对基线的完整差异为 `pkg/cache/cache.go`、`pkg/cache/cache_internal_test.go`、`pkg/sandbox-manager/infra/sandboxcr/claim_test.go`，共 3 个文件、240 行新增及 10 行删除。没有排除的无关源码改动。
- `PickSandboxSet` 改为每次调用独立的 100ms 轮询和 5 秒窗口；首次立即查询，仅空结果重查，命中返回、父 context 结束或读取错误退出。窗口结束再作一次同步缓存检查以覆盖末次 tick 后到达的对象，不创建新窗口。自身窗口耗尽保持原未找到错误；读取错误与父 context 原因保留。
- 去除此方法的 singleflight 包装；其他方法、namespace/名称索引/informer selector 配置、上层接口与错误映射均未修改。查询没有 APIReader、隐式回源、资源写入或缓存对象修改。
- 仍覆盖原先完整设计审查的源码基线，设计合同及相关依赖未变，没有被上游变化失效的设计覆盖。本段为实现适用性核对，不冒充新独立 Pass。

最终文件 SHA-256：

| 文件 | SHA-256 |
| --- | --- |
| `pkg/cache/cache.go` | `235103a54f7616bcf4a36f16a15c056e208df470261575a5e6b9abedca0d55eb` |
| `pkg/cache/cache_internal_test.go` | `bf58557e4cc28be7b108683cc46215d5aaff2a514e40adcbc94d7a35e01ce5f0` |
| `pkg/sandbox-manager/infra/sandboxcr/claim_test.go` | `0cba816488a69152c1e009f9373b8619f2b8d9cbf6e42a5b027fdb954f412cb1` |

## 实现验证

所有 Go 命令在上述 worktree 执行，Go 工具链为 `go1.26.3`，使用现有模块版本及 `-mod=readonly`。首次沙箱测试因 Go 缓存写权限而未启动，随后经宿主提权运行。首轮新测试暴露 tick 与对象到达同时发生时的调度边界；已改用错开 tick 的确定性样本，并新增窗口末尾到达的最终缓存检查。以下为最终状态的实际结果：

- `gofmt -w pkg/cache/cache.go pkg/cache/cache_internal_test.go`：完成；`git diff --check`：通过。
- `go test -mod=readonly ./pkg/cache -count=1`：通过（14.863s）。
- `go test -mod=readonly -race ./pkg/cache -run '^TestPickSandboxSet' -count=10`：通过（3.316s）。
- `go test -mod=readonly ./pkg/servers/e2b -run '^Test(CreateSandbox_TopLevelMissingTemplateOrCheckpointReturns400|CreateSandboxMemoryPersistence|GetTemplate|DeleteTemplate|TemplateNamespaceIsolationWithSameName)$' -count=1`：通过（61.456s），含 claim/clone 创建分支及原有错误映射。
- `go test -mod=readonly ./pkg/sandbox-manager/infra/sandboxcr -run '^Test(Infra_ClaimSandboxWithNamespace|PickAnAvailableSandbox_PrefersMatchingRevision)$' -count=1`：补齐 fixture 后通过（1.213s）。
- namespace claim 用例初次失败：已有 fixture 仅创建库存 Sandbox，未创建 SandboxSet，在查询 updateRevision 时新增的未命中等待耗尽其原有 100ms claim 期限。按已批准的共用查询等待合同，在该隔离测试中补齐各 namespace 的内嵌模板 SandboxSet，保留原超时与隔离断言，未改生产 claim 行为。
- 扩大回归进一步发现 `TestInfra_ClaimSandbox` 的库存选择用例有同样的缺失 fixture；已在该表中仅为有库存场景补齐 SandboxSet。无 SandboxSet 且只有 50ms claim 期限的场景按合同改为断言提前截止，并新增 `errors.Is(context.DeadlineExceeded)` 原因检查。原有各成功/失败场景、库存和隔离断言均保留。修复后 `go test -mod=readonly ./pkg/sandbox-manager/infra/sandboxcr -run '^TestInfra_ClaimSandbox$' -count=1` 通过（3.938s）。
- `go test -mod=readonly ./pkg/sandbox-manager/infra/sandboxcr -count=1`：实现阶段完整包回归通过（133.231s），日志见下文；人工审查后的测试调整与针对性重新验证见下一节。

完整失败日志与修复后的定向输出保留在 `/Users/sophon/Workspace/OKAWorkspace/local-storage/sandboxset-create-consistency/` 的 `infra-tests.log`、`claim-table.log`；最终扩大回归输出为 `infra-tests-final.log`。缓存包、race 和 E2B 的结果来自本次实际命令输出；后续只修改了 Infra 测试 fixture，不使这些已通过检查失效。

新增测试使用 `testing/synctest` 与现有 controller-runtime fake/interceptor 能力，覆盖立即命中、延迟可见、4.95 秒可见、持续未命中、namespace 隔离、父取消和提前截止、首次/等待中读取错误，以及独立读取产生的 DeadlineExceeded 不误映射成未找到。并发用例覆盖取消隔离和晚到调用在第 6 秒仍可成功（其自身尚未到第 7 秒期限），并验证空 namespace 跨 namespace 的原语义。各用例 APIReader Get/List 为零；现有 BuildCacheConfig 与名称索引等包测试一并通过。

未进行 AI 独立实现审查、真实 informer watch 传播验证、现场复现或本地 E2E；未声称生产 5 秒覆盖率。项目记录维护使用 `manage-workitems`/`complete-workitem`，普通推送项目分支。

## 人工结论与 PR 交付（2026-11-11）

用户原文为“人工审查通过，帮我创建 PR”；按人工代码审查接受记录，不虚构审查者姓名或 AI 独立实现审查 Pass。发布时核验当前生产代码指纹与实现阶段相同。现有测试修改保留：缓存并发用例合并取消与晚到窗口验证；表驱动用例精简并直接模拟读取截止；claim fixture 复用 `sandboxSetForTest`，提前截止用例保留业务错误及 `errors.Is` 原因断言。文件差异不单独作为作者身份的证据。

最终测试在同一 worktree 实际重跑并通过：

- `go test -mod=readonly ./pkg/cache -count=1`（11.792s）。
- `go test -mod=readonly -race ./pkg/cache -run '^TestPickSandboxSet' -count=10`（2.799s）。
- `go test -mod=readonly ./pkg/sandbox-manager/infra/sandboxcr -run '^Test(Infra_ClaimSandbox|Infra_ClaimSandboxWithNamespace)$' -count=1`（3.740s）。
- `gofmt -l` 对三个变更文件无输出；`git diff --check` 通过。上次 E2B 回归及 Infra 包其他未改场景的覆盖保留，没有重复运行全部检查。

创建前成功刷新 upstream/master，仍为开发基线提交；无需 rebase，最终分支与该上游基线无冲突。分类脚本确认三个文件全为开源文件；自动解析脚本在多个 fork 中返回了 `ywexcellent`，经项目配置、实际 remote URL 及登录账号核验，发布目标按用户项目选定的 `AiRanthem/agents`，使用实际 remote `airanthem`，没有推到 GitLab。

源码已 sign-off 提交并普通推送，`git ls-remote airanthem refs/heads/fix/sandboxset-cache-wait-261111` 与本地提交均为 `d1c59b668ccff1ea9ae03e7dcc016ccaaf0d4037`。GitHub 连接器创建 PR 返回集成权限不足 403，随后使用已登录的 GitHub CLI 成功创建 [PR #1207](https://github.com/openkruise/agents/pull/1207)。创建后经连接器及 CLI 回读确认：OPEN、非草稿、base 为 `openkruise/agents:master`、head 为 `AiRanthem:fix/sandboxset-cache-wait-261111` 且 SHA 匹配，完整差异仅三个文件。

回读时 PR 可合并，CI 和 Tide 仍在运行/等待，未把这一状态写成已通过、已合并或 E2E 已验证。未手动请求 reviewer、未合并、未部署、未清理 worktree。

## 覆盖率补充（2026-11-11）

用户要求“CI显示单测覆盖率不够，帮我补到100%，以最少的代码”。实际 CI 的单测已通过，失败项为 Codecov patch：`d1c59b668` 的新增代码行覆盖率 69.23077%，8 行缺失或部分覆盖，全部位于 `pkg/cache/cache.go`。本次目标为 PR 新增代码 100%，不扩展为全仓库覆盖率改造。

只修改已有 `pkg/cache/cache_internal_test.go`，21 行新增、4 行删除（净增 17 行）：复用表驱动用例补充已结束的 context、最终缓存检查失败和取消，控制原末尾可见用例走最终检查成功分支。每例仍检查错误原因、结果、虚拟耗时与 APIReader 零调用；未修改生产代码、公开合同、覆盖率配置或阈值。人工审查结论继续绑定此前 `d1c59b668`，本次测试补充来自新的用户授权，不虚构新的人工结论。

在源码 worktree 实际验证：

- `go test -mod=readonly ./pkg/cache -run '^TestPickSandboxSet' -coverprofile=/private/tmp/sandboxset-after.cover -count=1`：通过（0.952s）。
- `go tool cover -func=/private/tmp/sandboxset-after.cover`：`PickSandboxSet` 为 100.0%；逐块核验该函数 23 个 instrumented blocks、29 条语句全部命中。
- 原始覆盖率文件另存为 `/Users/sophon/Workspace/OKAWorkspace/local-storage/sandboxset-create-consistency/lookup-441ac6702.cover`。
- `go test -mod=readonly -race ./pkg/cache -run '^TestPickSandboxSet' -count=10`：通过（2.922s）。
- `gofmt`、`git diff --check` 及文件分类检查通过。源码仅测试变更，其余仍有效的回归覆盖保留。

补充提交 `441ac6702e53b37ed9acb611ace8b1147dafbdb5` 已普通推送到原 fork 分支，PR head 回读匹配，新的 CI 单测正在运行。本地函数语句 100% 与 Codecov patch 行覆盖率分别记录，远端报告待回读。
