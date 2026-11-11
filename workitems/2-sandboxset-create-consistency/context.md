# 当前证据与交接

## 设计及阶段

正式设计为 `spec.md` v1，用户已批准，并于 2026-11-11 通过完整独立设计审查，状态为 `implementable`，见 [records/design-review.md](records/design-review.md)。用户随后授权执行已确认的实现计划；当前已完成源码实现及缓存自检，源码保持未提交，独立实现审查待进行。设计正文未改，尚未进行现场运行时复现。

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

设计独立评审已获授权并通过，当前状态为 `implementable`。实现依据见下节。fake client 测试不能证明真实 informer 传播延迟；独立实现审查、人工验收及源码交付继续分别记录。

源码交付方式尚未指定，人工验收、源码 push、PR、合并、部署和 E2E 结果均未发生。项目配置没有外部同步后端，因此本轮不创建或发送外部系统工作项与消息。

## 实现身份与行为（2026-11-11）

实现者为本次 Codex 主会话；本会话的逐函数自检不构成独立实现审查。

- 源码仓库：OpenKruise Agents；主检出保持干净的 `develop`。本轮成功 `git pull --ff-only` 后主检出仍为 `7b86412bf14373963c648a7ceed91d91b5c02ceb`。
- 本轮核验 upstream 地址、成功 `git fetch upstream master`，从 `3d9af5799d873e278cbfcb8871a0d0a3ec726447` 创建分支 `fix/sandboxset-cache-wait-261111`，初始 HEAD 与基线一致；后续 `git ls-remote upstream refs/heads/master` 核验仍相同。
- 实际 worktree：`/Users/sophon/Workspace/OKAWorkspace/projects/oka-daily-open-source/worktrees/2-sandboxset-create-consistency`。当前 HEAD 等于上述基线，无源码提交。
- 修改：`pkg/cache/cache.go`、`pkg/sandbox-manager/infra/sandboxcr/claim_test.go`；新增未跟踪文件：`pkg/cache/cache_internal_test.go`。没有排除的无关源码改动。
- `PickSandboxSet` 改为每次调用独立的 100ms 轮询和 5 秒窗口；首次立即查询，仅空结果重查，命中返回、父 context 结束或读取错误退出。窗口结束再作一次同步缓存检查以覆盖末次 tick 后到达的对象，不创建新窗口。自身窗口耗尽保持原未找到错误；读取错误与父 context 原因保留。
- 去除此方法的 singleflight 包装；其他方法、namespace/名称索引/informer selector 配置、上层接口与错误映射均未修改。查询没有 APIReader、隐式回源、资源写入或缓存对象修改。
- 仍覆盖原先完整设计审查的源码基线，设计合同及相关依赖未变，没有被上游变化失效的设计覆盖。本段为实现适用性核对，不冒充新独立 Pass。

最终文件 SHA-256：

| 文件 | SHA-256 |
| --- | --- |
| `pkg/cache/cache.go` | `235103a54f7616bcf4a36f16a15c056e208df470261575a5e6b9abedca0d55eb` |
| `pkg/cache/cache_internal_test.go` | `42d7546f8fe2a3d16676248f3a5246dfd2e5df91dab9dbf0ce2020a91620deb9` |
| `pkg/sandbox-manager/infra/sandboxcr/claim_test.go` | `a9053680df10e8c5ca4d3a94667d87cd47c3ea2810a1e33742ff928bf7eb5d97` |

## 实现验证

所有 Go 命令在上述 worktree 执行，Go 工具链为 `go1.26.3`，使用现有模块版本及 `-mod=readonly`。首次沙箱测试因 Go 缓存写权限而未启动，随后经宿主提权运行。首轮新测试暴露 tick 与对象到达同时发生时的调度边界；已改用错开 tick 的确定性样本，并新增窗口末尾到达的最终缓存检查。以下为最终状态的实际结果：

- `gofmt -w pkg/cache/cache.go pkg/cache/cache_internal_test.go`：完成；`git diff --check`：通过。
- `go test -mod=readonly ./pkg/cache -count=1`：通过（14.863s）。
- `go test -mod=readonly -race ./pkg/cache -run '^TestPickSandboxSet' -count=10`：通过（3.316s）。
- `go test -mod=readonly ./pkg/servers/e2b -run '^Test(CreateSandbox_TopLevelMissingTemplateOrCheckpointReturns400|CreateSandboxMemoryPersistence|GetTemplate|DeleteTemplate|TemplateNamespaceIsolationWithSameName)$' -count=1`：通过（61.456s），含 claim/clone 创建分支及原有错误映射。
- `go test -mod=readonly ./pkg/sandbox-manager/infra/sandboxcr -run '^Test(Infra_ClaimSandboxWithNamespace|PickAnAvailableSandbox_PrefersMatchingRevision)$' -count=1`：补齐 fixture 后通过（1.213s）。
- namespace claim 用例初次失败：已有 fixture 仅创建库存 Sandbox，未创建 SandboxSet，在查询 updateRevision 时新增的未命中等待耗尽其原有 100ms claim 期限。按已批准的共用查询等待合同，在该隔离测试中补齐各 namespace 的内嵌模板 SandboxSet，保留原超时与隔离断言，未改生产 claim 行为。
- 扩大回归进一步发现 `TestInfra_ClaimSandbox` 的库存选择用例有同样的缺失 fixture；已在该表中仅为有库存场景补齐 SandboxSet。无 SandboxSet 且只有 50ms claim 期限的场景按合同改为断言提前截止，并新增 `errors.Is(context.DeadlineExceeded)` 原因检查。原有各成功/失败场景、库存和隔离断言均保留。修复后 `go test -mod=readonly ./pkg/sandbox-manager/infra/sandboxcr -run '^TestInfra_ClaimSandbox$' -count=1` 通过（3.938s）。
- `go test -mod=readonly ./pkg/sandbox-manager/infra/sandboxcr -count=1`：最终完整包回归通过（133.231s），日志见下文。缓存和调用方验证均已完成，当前待独立实现审查。

完整失败日志与修复后的定向输出保留在 `/Users/sophon/Workspace/OKAWorkspace/local-storage/sandboxset-create-consistency/` 的 `infra-tests.log`、`claim-table.log`；最终扩大回归输出为 `infra-tests-final.log`。缓存包、race 和 E2B 的结果来自本次实际命令输出；后续只修改了 Infra 测试 fixture，不使这些已通过检查失效。

新增测试使用 `testing/synctest` 与现有 controller-runtime fake/interceptor 能力，覆盖立即命中、延迟可见、4.95 秒可见、持续未命中、namespace 隔离、父取消和提前截止、首次/等待中读取错误，以及独立读取产生的 DeadlineExceeded 不误映射成未找到。并发用例覆盖取消隔离和晚到调用在第 6 秒仍可成功（其自身尚未到第 7 秒期限），并验证空 namespace 跨 namespace 的原语义。各用例 APIReader Get/List 为零；现有 BuildCacheConfig 与名称索引等包测试一并通过。

未进行独立实现审查、真实 informer watch 传播验证、现场复现或 E2E；未声称生产 5 秒覆盖率。项目记录维护使用 `manage-workitems`，普通推送项目分支；源码保持未提交，后续审查必须包含上述未跟踪测试文件。
