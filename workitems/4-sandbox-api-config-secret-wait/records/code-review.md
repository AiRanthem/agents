# 工作项 4 实现审查 · 2026-11-18

**Changes required。** 当前实现有四项高严重度发现、一项中严重度发现。批准的[设计 v1](../spec.md) 要求 Pod 提前 Ready 时，控制 API 与同 Pod Envoy 业务入口都持续返回 503，直到初始配置和运行时初始化完成。[用户决定](../decision.md)

## 需要修正的行为

| 严重度 | 发现、归因与修复验收条件 |
| --- | --- |
| 高 | **Envoy 业务流量跳过启动门禁。** `pkg/servers/e2b/core.go:325` 提前启动完整 proxy。`pkg/proxy/ext_proc.go:108` 将 Sandbox 请求送入既有查路由逻辑，空路由返回 502，已有 Running 路由时生成转发目标。`pkg/sandbox-manager/routes.go:60` 在初始事件处理中逐条写入路由，故同步完成前也可能已有可用目标。须保证等待配置、路由部分同步两个阶段都返回 503，包括 Sandbox 自身的 /health，激活后才恢复转发。CLI 帮助和源码 proposal 将当前偏差称作已接受的取舍，与批准记录冲突。启动测试在 `pkg/servers/e2b/run_test.go:100,270` 显式关闭 ext-proc，需要断言协议响应及是否生成转发目标。 |
| 高 | **待配置请求的凭据可能写入日志。** 提前启动使 `pkg/proxy/ext_proc.go:107` 在配置等待期即可执行，该处在分类前记录整组请求头，包括经 Envoy 转到控制 API 的流量。示例编排启用了相应详细日志级别。原始头日志已存在于基线，此次新增的是从接流到激活之间的暴露时段。须保证等待期请求的日志不含凭据，覆盖控制面和 Sandbox 两类请求；这也是 `pkg/proxy/AGENTS.md:18` 的明确约束。此项由代码及编排推导，未读取现场日志或观察到实际凭据泄露。 |
| 高 | **待处理的 SIGTERM 不能阻止首次开放准入。** 信号先入缓冲，启动结果随后也就绪时，`pkg/servers/e2b/core.go:379` 可以先选中成功结果。`core.go:292` 随即设置 active，直到另一 goroutine 消费已到信号并在 `core.go:436` 关闭门禁。此间业务监听已可用。基线的选择逻辑用于决定如何清理，新增的 active 写入使其决定是否接纳请求。两种调度都应能优雅退出，且挂起终止信号时不得开放业务。`pkg/servers/e2b/run_test.go:369` 允许两个仲裁结果，没有断言期间的准入。 |
| 高 | **可预先确定的 memberlist 端口冲突会被 Ready 掩盖。** 当 memberlist 与本实例的路由刷新监听都配置在 7789 且地址重叠时，默认 metrics 配置下的 `cmd/sandbox-manager/main.go:65` 放过此组合。早期监听先占用该端口，配置持续缺失时仍能满足探针。只有配置补齐、执行 `pkg/sandbox-manager/core.go:451` 后，才会在成员启动时发现一定会失败的绑定。基线在此期间不会先 Ready。应在提前 Ready 前拒绝静态可判定的端口范围错误和监听冲突，同时保留原定的成员加入时机。启动测试的 Manager 未装配 memberlist。 |
| 中 | **启用 tracing 时，等待期的部分控制 API 请求返回 400。** 请求命中已注册业务端点但携带带连字符的 UUID 作为请求 ID 时，`pkg/servers/web/framework.go:99` 会在 `framework.go:157` 的中间件之前返回 400，E2B 准入检查无法执行。应在已匹配的业务入口先返回带既有 JSON 字段的 503；激活后恢复 tracing 原有的 400。现有框架测试和准入测试分别覆盖两个行为，缺少组合断言。集中设置业务路由的准入检查也可消除逐路由重复挂载。 |

## 审查对象与覆盖

- 源码位于本项目的 `worktrees/4-sandbox-api-config-secret-wait`，分支 `feat/ready-before-config-261117`。基线和 HEAD 均为 `18096feb1d1089499b1227a3e60dc25476ae072d`。全部 11 个变更文件已暂存，449 行新增、103 行删除，无未暂存或未跟踪文件。完整 `git diff --binary --no-ext-diff HEAD` 的 SHA-256 为 `b01ef90f9c9b8e9c4c1422fb93393f05bb1c67d84d63ed1fe354873de7520c8f`。11 月 17 日实现记录中的 12 文件快照指纹不同，不能将其测试结果作为本轮实测。
- 本轮重新核对了需求 SHA-256 `2877329af629aa4ca10efbb5aaf635ed9c9111cad75b625babd4f40e82bc0c47` 和设计 SHA-256 `cd20e6999ea8e7c89b5210a48493bd3f94bb79d07530f365b53fc01447e8af03`。源码 proposal 和命令帮助参与审查；产品合同以用户批准的工作项原文为准。
- 普通模式及无 Secret 引用的静态路径保留原启动顺序。固定 runtime TLS 与 peer 安全材料在对应监听前加载。新模式复用独立 informer 与一次性配置确认信号。Manager 保有缓存、初始路由、成员加入和配额维护的所有权。控制 API 在正常请求上先拒绝再鉴权，观测端点保留原有位置。无效或后续失败的热更新不会重置一次性状态。主审另检查了监听复用、启动失败、局部初始化后的清理、Secret 存储未运行即停止及 quota worker 的退出预算。
- 用户回复“是3”。独立主审 Codex `/root` 完成全量审查，另有三个独立专项审查实际执行。三个 Astra 审查会话分别为 `envoy_review`（数据面、请求分类及安全）、`lifecycle_review`（启动、取消及部分启动后的清理）、`api_quality_review`（控制 API、实现质量及测试断言）。首次分派因角色绑定未执行，随后使用指定角色与独立上下文重派。主审及实际参与的三位审查者均未编写或修正此次实现。主审核对了每项发现的调用链和测试预期。

## 本轮验证

在上述工作树使用 Go 1.26.3 执行以下两组定向测试，均退出 0。第一组中 cmd、keys、Manager 三包没有匹配用例，第二组按真实测试名称覆盖这三个包。并发竞争发现来自对可达执行顺序的检查；race 检测器检查的是数据竞争。

```sh
go test -race -p 1 ./cmd/sandbox-manager ./pkg/configreload ./pkg/servers/e2b ./pkg/servers/e2b/keys ./pkg/sandbox-manager ./pkg/sandbox-manager/quota ./pkg/proxy -run 'Test(ReadyBeforeConfig|ControllerStartupWaitsForInitialSandboxRoutes|AwaitStartup|AntiDriftStopBudget|SecretKeyStorageStop|Server_Process|Server_RunLifecycle|DispatcherConvergence|SecretReconcilerPreservesState|RunWatcherRetriesUntilCanceled)' -count=1
go test -race -p 1 ./cmd/sandbox-manager ./pkg/servers/web ./pkg/servers/e2b ./pkg/servers/e2b/keys ./pkg/sandbox-manager -run 'Test(ParseSecretConfig|SecretConfigSource|RequestIDHandling|ConfigurationStartsBeforeInitWait|ConfigurationSourceExitsBeforeInitialization|ControllerRunStartsDedicatedObservabilityListener|ControllerStartHTTPServerReportsBindFailure|SecretKeyStorage_StopWithoutRun|SandboxManagerRun|ApplyPeerSecurity)' -count=1
```

变更 Go 文件的 `gofmt -l` 无输出，源码 `git diff --check HEAD` 通过。审查未运行真实 Envoy、双容器 Pod、滚动发布或集群 E2E。源码仍是未提交的工作树内容。工作项待修正与复审，人工验收和源码交付尚未发生。
