# 上下文与设计探索

## 来源与当前事实

- 2026-11-17，用户通过 `$explore-design 4-sandbox-api-config-secret-wait` 启动本项设计探索。
- 用户随后明确更正：“需求表达错误，现在等待的时候会出现 0/2 ready ，导致一些发布系统会卡住”。当前问题以该更正为准；不再将缺少配置时立即 crash 作为事实。
- 原先的“进程不感知 startup probe 超时”约束没有被明确撤回；不能从本次更正推导进程内超时、提前 Ready 或跳过发布检查已获批准。
- 本项使用未占用编号 `4`，与既有 SandboxSet 工作项无已知依赖或缺陷修复关系。

## 当前源码证据

- 已成功更新源码主检出 `develop` 至 `8f02008e8a2a5560fb607a70afc3520d55c636e9`，并刷新 `upstream/master` 至 `d764256be82aa790582b4ce4af98997a5958a30a`。本轮设计取证未创建源码分支或 worktree。
- `cmd/sandbox-manager/secretconfig.go` 将非空 `--secret-config` 接入 `configreload.RunWatcher`；`pkg/configreload/controller.go` 使用按 namespace/name 限定的独立 informer。初始配置没有确认前，`Dispatcher.Initialized()` 不会释放启动等待；配置形状无效时等待更新，观察器故障会继续重试。
- `pkg/servers/e2b/core.go` 的 `Init` 等待初始配置，之后 `startComponents` 才运行 Manager、业务 HTTP 和可选独立 metrics/health 监听。`pkg/sandbox-manager/core.go` 在 `Run` 中启动 proxy，`pkg/proxy/server.go` 才绑定路由刷新与 ext-proc 监听。因此配置等待能阻止这些后续监听启动。
- `config/sandbox-manager/deployment.yaml` 的测试编排为双容器：controller 的 startup/readiness 检查端口 7789，envoy-proxy 检查端口 7788。按 `config/AGENTS.md`，它仅是 E2E 测试编排，不能据此确认现场两个容器的探针，也不能证明现场 `0/2` 的逐容器原因。
- 官方 Kubernetes 合同中，startup probe 成功前不会运行 readiness probe；Ready 还影响 Service 流量接入。仅提前开放健康端口而继续保持未 Ready，不能满足发布系统等待 Ready 的条件。来源：[Pod lifecycle](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#container-probes)。
- 历史上 PR #857 使用一次性 Secret Get；[PR #1177](https://github.com/openkruise/agents/pull/1177) 的上游提交 `4331416b2266acb4dd062995d55b8adb02be78fd` 引入当前观察与初始化门禁，内部对应提交 `989514c4cdcd68b2be908d2eb9a882374a243db5` 已包含在本地 `ack-sandbox-api-v0.6.14-release.2` 源码标签。该历史不是当前运行镜像或现场发布状态的证据。

## 已执行的局部检查

以下检查由 Codex 主 agent 在上述干净的 `develop` 主检出执行，均通过。相关生产文件与已刷新上游相同；E2B 测试文件有一处既有缓存辅助函数类型差异，未涉及本次选定测试。

- `go test ./pkg/configreload -run 'Test(DispatcherConvergence|SecretReconcilerPreservesState|WatcherReconcileLogs|RunWatcherRetriesUntilCanceled)$' -count=1`：通过，覆盖现有配置确认、删除后状态保留、实际观察器 reconcile 和重试取消。
- `go test ./pkg/servers/e2b -run 'Test(ConfigurationStartsBeforeInitWait|ConfigurationSourceExitsBeforeInitialization|ControllerSignalDuringStartupExitsCleanly|AwaitStartup)$' -count=1`：通过，覆盖配置门禁与启动取消。

这些检查验证现有等待路径的局部行为，不验证修订后的发布目标，没有执行初始缺失后补建的完整启动、双容器探针、滚动更新、发布系统或集群 E2E。只读历史收集由受派证据收集 agent 完成；没有独立设计或代码评审。

## 尚待收敛的合同

- 缺配置时，发布应成功并保留待配置状态，还是在有限时间内明确失败。
- 若发布可继续，是否由发布系统识别待配置并跳过相应检查，还是要求 Pod 提前 Ready。两者的流量接入和旧副本替换结果不同，尚未作出用户决定。
- 具体发布系统、实际双容器探针和发布完成条件；源码测试编排不能替代现场配置。
- 对 Secret 缺失与存在但内容无效、权限或连接故障，是否采用相同发布语义。
- 启动及运行中配置恢复、业务准入、滚动更新可用性与此前外部超时约束如何组成完整验收合同。

先前询问的 crash 版本和退出日志已不是本项当前目标的必需前提；后续信息应围绕上述发布阻塞问题收敛。

## 工作边界

本轮只同步用户已明确的需求更正及实际设计取证，完整 Why/What 尚待用户选择，未编写设计定稿。独立评审、实现、人工验收与源码交付均未进行；没有创建开发分支或源码 worktree。后续如开展代码开发，须按 `.project/business-instructions.md` 成功刷新并核验最新 `upstream/master` 后建立隔离分支，记录并核验基线。

项目未配置 Aone 后端，本次不进行外部系统同步。
