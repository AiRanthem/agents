# 设计依据

设计核对的 OpenKruise Agents 上游 master 提交为 `3fc1216cea513df40b68f77171b042dc1ef7e8e3`。以下为源码证据。

- 令牌签发通过 `WithoutCancel` 保留请求的上下文值，并单独接入 Manager 停机取消；各调用方独立等待共享结果。仓库已有用例覆盖一个等待者取消后另一个等待者仍拿到令牌。[等待分支](https://github.com/openkruise/agents/blob/3fc1216cea513df40b68f77171b042dc1ef7e8e3/pkg/sandbox-manager/traffic_token.go#L77-L135) · [签发生命周期](https://github.com/openkruise/agents/blob/3fc1216cea513df40b68f77171b042dc1ef7e8e3/pkg/sandbox-manager/traffic_token.go#L205-L221) · [既有用例](https://github.com/openkruise/agents/blob/3fc1216cea513df40b68f77171b042dc1ef7e8e3/pkg/sandbox-manager/traffic_token_test.go#L259-L308)
- 令牌 API 将不可用错误映射为统一响应，Web 框架记录转换后的 `ApiError`。响应文字不足以恢复原始来源。[API 映射](https://github.com/openkruise/agents/blob/3fc1216cea513df40b68f77171b042dc1ef7e8e3/pkg/servers/e2b/traffic_token.go#L54-L72) · [请求结果日志](https://github.com/openkruise/agents/blob/3fc1216cea513df40b68f77171b042dc1ef7e8e3/pkg/servers/web/framework.go#L159-L171)
- Pause/Resume 的等待错误分支检查当前 `ctx.Err()` 并使用客户端取消文案。Claim 则有自己的期限，等 worker 时的错误文案包含 “context canceled”。归因需要区分退出原因和记录时的状态。[Pause](https://github.com/openkruise/agents/blob/3fc1216cea513df40b68f77171b042dc1ef7e8e3/pkg/sandbox-manager/infra/sandboxcr/sandbox.go#L585-L596) · [Resume](https://github.com/openkruise/agents/blob/3fc1216cea513df40b68f77171b042dc1ef7e8e3/pkg/sandbox-manager/infra/sandboxcr/sandbox.go#L663-L675) · [Claim 期限](https://github.com/openkruise/agents/blob/3fc1216cea513df40b68f77171b042dc1ef7e8e3/pkg/sandbox-manager/infra/sandboxcr/infra.go#L149-L165) · [Claim 等待](https://github.com/openkruise/agents/blob/3fc1216cea513df40b68f77171b042dc1ef7e8e3/pkg/sandbox-manager/infra/sandboxcr/claim.go#L374-L381)

设计作者为 Codex。下文保留 v1 的独立设计评审及其原始验证范围。当前实现依据用户直接修改的 v2。

## 2026-11-25 独立设计评审

**结论：通过（`pass`），无阻塞项。** 当前设计状态登记为 `implementable`；这表示已确认设计经过独立可实现性评审，不代表实现授权、源码交付或人工验收。

### 评审身份与输入

- 评审者：Qoder（本会话未参与原设计或任何实质修订）。设计作者仍为 Codex；本次登记不增加设计作者。
- 辅助 Explore 代理仅定位其余取消日志入口并提供基线证据，未承担独立通过结论；主评审者自行核对关键源码、错误包装及测试断言。未声明跨模型评审。
- 评审与登记授权来自[用户决定](decision.md#2026-11-25-评审与登记授权)。
- 评审输入：项目提交 `c8c55f3cf99c259fdfcb83283223abdb1ed5693e` 中的 `requirement.md`、完整 `spec.md` v1、`decision.md` 和源码依据；适用项目、主工作区及源码仓库的原始指令。
- 输入设计 SHA256：`144ba8829edacb9df65c87a1c2ed4da51d1000e9a83f6bb60d88ca6192a99a88`。
- 输入需求 SHA256：`4b207b329c5286cbc0e2ce4f80250e9a725f1fb46d626f674e80d2551dd7a695`。
- 源码基线：`3fc1216cea513df40b68f77171b042dc1ef7e8e3`。源码主检出为 `62532a56c593cc30c8690c2a45bb4d424da86c46`（`develop`），与设计基线不同；评审通过 Git 固定对象及对应文件差异校准证据，没有将主检出视作上游基线。

### 覆盖与依据

- 共享令牌的请求等待与独立签发分别归因；请求退出不取消其他等待者，Manager 停机取消签发，两个退出分支同时就绪时以实际采用的分支及原因确定来源。核对 `pkg/sandbox-manager/traffic_token.go:77-135,205-221` 及既有取消、签发超时和停止排空测试。
- 原始取消错误与归因需跨 Manager 错误包装、API 消息转换保留，且不能泄漏到 HTTP 响应。核对 `pkg/sandbox-manager/errors/error.go`、`pkg/sandbox-manager/api.go`、`pkg/servers/e2b/traffic_token.go:54-70`、创建及 Pause/Resume 的错误映射，以及 `pkg/servers/web/framework.go:159-171`。
- Pause/Resume 等待会二次检查对象；取消信号不一定等于最终失败原因，也可能最终成功或返回冲突。核对 `pkg/cache/utils/wait.go:183-260`、等待相关测试和基线 `pkg/sandbox-manager/infra/sandboxcr/sandbox.go`。设计要求冲突、超时、成功省略字段，与这一边界一致。
- Claim/Clone 自有期限、重试和错误文案不能替代取消证据。核对 Infra 等待、错误分类、最终错误包装及清理路径，要求保留本地可取得的原因，不改变已有超时、重试和状态码规则。
- 核对 quota、配置/密钥存储、生命周期、后台清理和既有静默取消入口。设计保留原日志级别及静默路径，不要求新增取消日志；成功后的常规 `cancel()` 清理不应产生 `cancelSource=internal`。
- `unknown` 仅用于确认取消但来源证据不足的情况；请求 ID、错误文本或写日志时的 context 状态都不能单独定因。未发现必需的未决设计选择或阻塞性可实现性缺口。

### 实现交接注意

以下是已确认合同的验证重点，不是设计阻塞项或新增需求：

1. 验证取消归因经过 API 映射后仍保留，同时 HTTP 状态码、JSON 字段及响应消息沿用现有行为。
2. 验证后到取消不覆盖已确定的来源；覆盖共享签发失败与请求取消交错，以及等待二次检查返回成功、冲突和普通超时的字段省略场景。

### 实际检查与限制

执行了 `git status`、`git rev-parse`、`git ls-tree`、`git show`、针对性 `git diff` 和 `shasum -a 256`，结合原文件阅读核验输入身份、基线及关键路径；评审结束时需求、设计指纹保持不变，项目与源码工作树均无改动。参考 Go context 文档核对取消脱离、回调及首个取消原因的语义。

本轮为只读设计评审，未修改源码、运行测试、启动应用或进行现场验证；既有测试只核对其行为与断言，未将其视为本次运行通过。设计可实现性通过不代替后续独立实现评审、人工验收或交付。

本次登记仅将 `spec.md` 的 `design_status` 从 `review-pending` 改为 `implementable`，正文、需求、版本和源码基线保持不变；最终登记指纹保存于 metadata 和 state。

## 2026-11-25 设计 v2 与源码实现

用户要求在取消导致的 API 错误响应中体现原因，并明确这项直接修改免于再次设计审查。完整决定见 [decision.md](decision.md)。源码实现由 Codex 完成，保留在项目内的 `worktrees/5-sandbox-manager-cancel-source`，本地分支为 `feat/sandbox-manager-cancel-source-261125`。创建前已刷新并核验 `upstream/master`，本次基线和工作树 HEAD 均为 `37351888a0cf561a57d694f3fc6baf077f3c9db8`。

- HTTP 入口标记请求的取消通道。在实际选择退出分支时记录来源。请求停止等待和 Manager 停止共享签发各自携带原因。依赖若仅返回裸的或包装的 `context.Canceled`，其来源为 `unknown`。已断开的请求与脱离请求的后台操作即使都已取消，仍然分别归因。
- Cache 和 Infra 在 Pause/Resume 的二次检查、Claim/Clone 的工作线程等待、重试及限流处保留实际返回结果。后到的请求取消或清理失败不会改写已有的冲突或普通失败。配额与密钥存储的脱敏错误只传递来源。
- Web 框架对取消错误返回顶层 JSON 字段 `cancelSource`，并在已有的 `API Error` 日志使用相同值。中间件提前返回也使用该响应格式。原有状态码和消息保留，普通超时、业务失败和成功响应省略该字段。

工作树含 51 个已跟踪修改和 1 个新文件 `pkg/utils/logs/cancellation.go`，共 52 个开源文件。为复核未提交源码，在该工作树运行下式得到内容指纹 `046546f8f0ced83f02d8a40fd79f05aa4ab6460ec21d496925d739a5f5b7662e`。完整差异可用 `git diff HEAD` 配合新文件查阅。

```sh
git ls-files -m -o --exclude-standard | LC_ALL=C sort | xargs shasum -a 256 | shasum -a 256
```

源码保持在本地工作树，独立实现审查、人工验收、源码发布及部署尚未进行。

### 实现验证

在上述指纹对应的源码工作树中使用 Go 1.26.3、`GOCACHE=/private/tmp/agents-lifecycle-go-cache` 运行以下命令，均以状态码 0 退出。11 个受影响包的测试通过，5 个包中的取消与并发定向用例在竞态检测下各重复三轮通过，sandbox-manager 命令构建成功。

```sh
go test ./pkg/utils/logs ./pkg/cache ./pkg/cache/utils ./pkg/configreload ./pkg/identity ./pkg/sandbox-manager ./pkg/sandbox-manager/infra/sandboxcr ./pkg/sandbox-manager/quota ./pkg/servers/web ./pkg/servers/e2b ./pkg/servers/e2b/keys -count=1
go test -race ./pkg/utils/logs ./pkg/cache/utils ./pkg/sandbox-manager ./pkg/sandbox-manager/infra/sandboxcr ./pkg/servers/web -run 'TestCancellationSourceFollowsSelectedContext|TestAlreadyCanceledRequestDoesNotMarkDetachedCancellation|TestRegisterRouteCancellation|TestWaitForObjectSatisfied_CancellationAfterDoubleCheck|TestSandboxManagerTrafficAccessTokenLeaderCancellationDoesNotFailWaiter|TestSandboxManagerTrafficAccessTokenIssueTimeoutFailsAllWaiters|TestTrafficTokenIssueLifecycleStopCancelsAndDrainsIssuance|TestInfra_GetSandbox_PollPreservesReadCancellationSource' -count=3
go build -o /dev/null ./cmd/sandbox-manager
git diff --check
```

路由测试捕获实际输出的 JSON 和日志，覆盖已有状态码、消息、三种取消来源、中间件返回及字段省略。共享签发测试覆盖等待者断开后其他请求继续取得结果，以及 Manager 停机和签发期限。修复前已复现已结束的独立 context 因 Go 复用关闭通道而被错归为 HTTP 请求的情况，对应回归用例随上述命令通过。格式检查通过，未进行集群端到端验证。

## 2026-11-25 多 agent 实现审查与修复

用户要求多 agent 审查实现，随后要求直接修复问题。Codex 主评审者与三个只读专项评审者（lifecycle、api、infra）审查了设计 v2 和上文指纹 `046546f8…f5b7662e` 对应的 52 个文件。该版本结论为 `changes-required`。Codex 在原源码工作树中修复了六项发现。

| 项 | 原审查发现 | 修复和回归覆盖 |
| --- | --- | --- |
| 1 | 鉴权和模板查询将取消错误折成“未找到” | MySQL 查 key、卷所有者、模板和 Checkpoint 查询将原因传给 API，保留原状态码与文案。测试覆盖 401、404、创建请求的 400、Claim 的二次查询及 Checkpoint 回退。卷路由当前未启用，测试使用临时路由调用实际鉴权中间件和 Manager。 |
| 2 | 写冲突遮住下一轮终止重试的取消 | Pause/Resume 保留 client-go 返回的冲突类型和消息，同时从最后一次尝试取来源。回归用例验证只发起一次实际写入。 |
| 3 | 等待后的二次读取在缓存未命中时将请求取消降为 unknown | 保留 informer 的读取结果。只有需要再发起 APIReader 请求时才检查其 context；已经开始的读取沿用自己的错误。覆盖已取消且缓存命中、缓存未命中、独立读取取消。 |
| 4 | CSI 在 PV 和 Secret 查询失败时将错误转成字符串 | 原错误随消息传递到创建路由。以 POST /sandboxes 分别验证两种读取失败的 400、原文案及 unknown 字段。 |
| 5 | 静态配置下 Manager 停止 Secret 观察轮询时被记为 unknown | 组件区分回调错误和轮询自身退出。覆盖停机、同时发生的独立取消及普通读取失败，校验脱敏消息。 |
| 6 | 安全令牌签发、传播和 runtime 初始化的错误日志缺少来源 | 在原日志级别输出来源。runtime 重试保留最后一次尝试的取消归因。测试直接检查签发、传播、runtime 重试和最终失败日志。 |

当前源码分支为 `feat/sandbox-manager-cancel-source-261125`，HEAD 与基线仍为 `37351888a0cf561a57d694f3fc6baf077f3c9db8`。按上文命令计算的 71 个变更文件内容指纹为 `07156fec87607a639858f1195a7aad3bcbf71010d4dee8c081593e7e83118245`。源码保留在本地未提交工作树，修复版待独立复审及人工验收。

在该指纹上使用 Go 1.26.3 和 `GOCACHE=/private/tmp/agents-lifecycle-go-cache` 运行以下检查，全部退出 0。14 个受影响包的单元测试通过，6 个包中的 10 个定向回归用例在竞态检测下各通过三轮，sandbox-manager 构建成功。源码变更文件均通过 gofmt 检查。本轮未执行集群 E2E。

```sh
go test ./pkg/utils/logs ./pkg/cache ./pkg/cache/utils ./pkg/configreload ./pkg/identity ./pkg/sandbox-manager ./pkg/sandbox-manager/infra/sandboxcr ./pkg/sandbox-manager/quota ./pkg/servers/web ./pkg/servers/e2b ./pkg/servers/e2b/keys ./pkg/utils ./pkg/utils/runtime ./pkg/utils/csiutils -count=1
go test -race ./pkg/cache ./pkg/sandbox-manager/infra/sandboxcr ./pkg/identity ./pkg/utils/runtime ./pkg/servers/e2b/keys ./pkg/servers/e2b -run '^Test(NewSandboxPauseTask_DoubleCheckCancellation|Sandbox_PauseResumeCancellationAfterWriteConflict|CreateSandbox_LookupCancellation|CreateSandboxCSILookupCanceled|AuthorizationLookupCancellation|VolumeOwnershipLookupCancellation|MySQLLookupCancellation|SecretReloadObservationCancellation|SecurityTokenCancellationLogs|InitRuntimeCancellationAfterRetry)$' -count=3
go build -o /dev/null ./cmd/sandbox-manager
git diff --check HEAD
```

## 2026-11-25 第二次独立实现审查与修复

用户要求忽略之前的审查结果，从设计 v2 和源码重新进行多 agent 审查。Codex 主审与 lifecycle、api、quality 三个只读专项审查了内容指纹 `07156fec87607a639858f1195a7aad3bcbf71010d4dee8c081593e7e83118245`，结论为 `changes-required`。用户随后要求直接修复。以下改动由 Codex 及 retry_fix、claim_logs_fix 在同一源码工作树完成。

| 发现 | 修复及验证 |
| --- | --- |
| 重试返回前一次错误，丢失真正终止重试的取消来源 | MySQL 创建 API Key、Secret 写入及管理员密钥初始化、Checkpoint 查询与标签更新保留末次失败的来源，继续使用原有错误类型和消息。临时通过 Go overlay 恢复旧重试实现，六个取消场景均在来源断言处失败。 |
| Claim 候选的 Node 读取普通失败，随后因请求取消而退出，却清空了来源 | 在实际终止筛选的分支取来源。测试覆盖普通读取失败后断连、读取自身返回取消，以及独立取消与请求取消同时可见的情况。 |
| Runtime JSON 请求在真实 HTTP 传输中将请求取消降为 unknown | 在出站 context 传递可识别的断连原因，保留传输期限。测试服务收到 `/init` 后取消入站 context，修复前实际日志与返回错误为 `unknown`，修复后返回 `http_request`。另核对父期限、传输超时、先前已断开的请求与独立 context。 |
| CSI 挂载与失败 Sandbox 清理日志漏掉同次错误来源 | 命令挂载、Storage API、单卷失败以及三条保留或删除决策日志已覆盖。只在描述原失败的记录添加该来源。Clone 从注解解析卷时的错误日志也已补齐，该条通过源码核查。 |

源码 HEAD 和基线均为 `37351888a0cf561a57d694f3fc6baf077f3c9db8`。按上文命令计算的 74 个变更文件内容指纹为 `1e0785c77c5da60d7c461fc3b0a1f6f690d6916023588580ddb913e6af98d7f5`。复审状态为待独立复审，源码未提交。

在源码工作树使用 Go 1.26.3 和 `GOCACHE=/private/tmp/agents-lifecycle-go-cache` 执行以下检查，全部退出 0。七个受影响包通过完整单测，以下三组定向用例分别在竞态检测下重复三轮。最终简化了一处等价的 context 状态判断，并重新执行 Runtime 与 logs 的竞态测试、构建和格式检查。尚未进行集群 E2E 或人工验收。

```sh
go test -count=1 ./pkg/utils/logs ./pkg/utils/runtime ./pkg/sandbox-manager/infra/sandboxcr ./pkg/servers/e2b/keys ./pkg/servers/e2b ./pkg/servers/web ./pkg/sandbox-manager
go test -race -count=3 ./pkg/servers/e2b/keys ./pkg/sandbox-manager/infra/sandboxcr -run '^(TestMySQL_CreateKeyBranches|TestSecretKeyStorage_RetryPatchSecretKeyErrors|TestSecretKeyStorageCancellationAfterRetry|TestCheckpointLookupCancellationAfterRetry|TestPatchCheckpointIDLabel)$'
go test -race -count=3 ./pkg/sandbox-manager/infra/sandboxcr ./pkg/utils/runtime -run '^(TestClearFailedSandboxLogsClaimCancellation|TestPickAnAvailableSandbox_ProbeUpdates|TestProcessCSIMounts_CancellationLogs)$'
go test -race -count=3 ./pkg/utils/logs ./pkg/utils/runtime -run '^(TestTransportTimeout|TestInitRuntimeHTTPRequestCancellation|TestInitRuntimeCancellationAfterRetry)$'
go build -o /dev/null ./cmd/sandbox-manager
git diff --check HEAD
git ls-files -m -o --exclude-standard | xargs gofmt -l
```
