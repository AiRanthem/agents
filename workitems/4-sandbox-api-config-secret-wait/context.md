# 上下文与设计探索

## 来源与当前事实

- 2026-11-17，用户通过 `$explore-design 4-sandbox-api-config-secret-wait` 启动本项设计探索。
- 用户随后明确更正：“需求表达错误，现在等待的时候会出现 0/2 ready ，导致一些发布系统会卡住”。当前问题以该更正为准；不再将缺少配置时立即 crash 作为事实。
- 原先的“进程不感知 startup probe 超时”约束没有被明确撤回。后续提前 Ready 的批准不授权进程自行读取探针配置或推算等待期限。
- 用户随后明确选择“Pod 先变成 2/2 Ready，配置完成前业务返回 503（会接入流量，也可能推进滚动替换）”，并补充“这个需要一个开关控制启动时的行为”。这些新增决定见 [decision.md](decision.md)。
- 本项使用未占用编号 `4`，与既有 SandboxSet 工作项无已知依赖或缺陷修复关系。

## 当前源码证据

- 已成功更新源码主检出 `develop` 至 `8f02008e8a2a5560fb607a70afc3520d55c636e9`，并刷新 `upstream/master` 至 `d764256be82aa790582b4ce4af98997a5958a30a`。本轮设计取证未创建源码分支或 worktree。
- `cmd/sandbox-manager/secretconfig.go` 将非空 `--secret-config` 接入 `configreload.RunWatcher`；`pkg/configreload/controller.go` 使用按 namespace/name 限定的独立 informer。初始配置没有确认前，`Dispatcher.Initialized()` 不会释放启动等待；配置形状无效时等待更新，观察器故障会继续重试。
- `pkg/servers/e2b/core.go` 的 `Init` 等待初始配置，之后 `startComponents` 才运行 Manager、业务 HTTP 和可选独立 metrics/health 监听。`pkg/sandbox-manager/core.go` 在 `Run` 中启动 proxy，`pkg/proxy/server.go` 才绑定路由刷新与 ext-proc 监听。因此配置等待能阻止这些后续监听启动。
- `config/sandbox-manager/deployment.yaml` 的测试编排为双容器：controller 的 startup/readiness 检查端口 7789，envoy-proxy 检查端口 7788。按 `config/AGENTS.md`，它仅是 E2E 测试编排，不能据此确认现场两个容器的探针，也不能证明现场 `0/2` 的逐容器原因。
- 开源 Helm 模板 `deploy/sandbox-manager/templates/deployment.yaml` 同样使用 controller 的 7789 和 Envoy 的 7788；现有 legacy TCP 探针入口不能仅靠提前启动独立 metrics/health 监听就满足。
- 官方 Kubernetes 合同中，startup probe 成功前不会运行 readiness probe；Ready 还影响 Service 流量接入。仅提前开放健康端口而继续保持未 Ready，不能满足发布系统等待 Ready 的条件。来源：[Pod lifecycle](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#container-probes)。
- 历史上 PR #857 使用一次性 Secret Get；[PR #1177](https://github.com/openkruise/agents/pull/1177) 的上游提交 `4331416b2266acb4dd062995d55b8adb02be78fd` 引入当前观察与初始化门禁，内部对应提交 `989514c4cdcd68b2be908d2eb9a882374a243db5` 已包含在本地 `ack-sandbox-api-v0.6.14-release.2` 源码标签。该历史不是当前运行镜像或现场发布状态的证据。
- `pkg/proxy/ext_proc.go` 已通过 Envoy ImmediateResponse 返回 HTTP 错误；新模式需要确保待配置请求在这一入口也得到 `503`，不能只保护直连 E2B HTTP。现有健康/观测例外必须限定到控制面端点，不能凭 Sandbox 业务路径也叫 `/health` 就放行。
- `pkg/servers/e2b/keys/mysql.go` 的 `ListLimited` 直接使用 `k.db`，配额 anti-drift 会调用它。仅删掉前台配置等待、提前运行全部后台任务会触及未初始化存储；依赖配置的后台激活必须与早期监听就绪分开。
- `pkg/servers/e2b/keys/mysql.go` 的 `ListLimited` 直接使用 `k.db`，而 `pkg/sandbox-manager/quota/antidrift.go` 会经 quota subject lister 调用它。初始 MySQL 配置完成前数据库尚未发布，因此仅提前运行整个 Manager 并给 HTTP 加门禁不足以建立安全的启动合同；依赖配置的后台工作也要保留其启动前提。
- `pkg/peers/memberlist.go` 的 Pod seed 发现不按 Ready 过滤；成员加入由 `Start` 决定。配置等待期间不因提前 Ready 自动加入成员和承担业务，配置生效后仍须完成原有初始路由处理再开放业务。peer 生命周期只读证据由原证据收集 agent 补充，主 agent 已核对关键源码。

## 已执行的局部检查

以下检查由 Codex 主 agent 在上述干净的 `develop` 主检出执行，均通过。相关生产文件与已刷新上游相同；E2B 测试文件有一处既有缓存辅助函数类型差异，未涉及本次选定测试。

- `go test ./pkg/configreload -run 'Test(DispatcherConvergence|SecretReconcilerPreservesState|WatcherReconcileLogs|RunWatcherRetriesUntilCanceled)$' -count=1`：通过，覆盖现有配置确认、删除后状态保留、实际观察器 reconcile 和重试取消。
- `go test ./pkg/servers/e2b -run 'Test(ConfigurationStartsBeforeInitWait|ConfigurationSourceExitsBeforeInitialization|ControllerSignalDuringStartupExitsCleanly|AwaitStartup)$' -count=1`：通过，覆盖配置门禁与启动取消。

这些检查验证现有等待路径的局部行为，不验证修订后的发布目标，没有执行初始缺失后补建的完整启动、双容器探针、滚动更新、发布系统或集群 E2E。只读历史收集由受派证据收集 agent 完成；没有独立设计或代码评审。

## 已确认方向与尚待收敛的合同

- 已确认通过启动开关选择提前 Ready、待配置业务返回 `503`；不再等待用户在先前三个方向中重新选择。
- 建议开关为 `--ready-before-config`，默认 `false`，仅在 `--secret-config` 非空时启用新语义；没有配置 Secret 时保留静态 flag/env 路径，避免扩大本项范围。这仍是待用户批准的完整合同中的建议。
- 建议开启时，Secret 缺失、内容无效、首次配置应用/验证尚未成功都保持 Ready 并以 `503` 拒绝业务；观察器继续按既有策略恢复。非配置的静态参数、证书、安全配置和监听绑定错误仍按原有致命启动错误处理。
- 建议原有健康与观测端点在新模式下可用，普通控制 API、Envoy 业务请求及未完成初始化的对等业务入口受统一的实例准入状态约束。依赖配置的维护、成员加入和运行时业务激活不提前；已有初始路由同步要求继续有效。
- 建议 startup probe 在新模式下只限制进程服务入口的启动，不再限制配置等待总时长；配置持续缺失可以持续 Ready/503。首次配置成功并完成后续运行时初始化后，在同一进程开放业务；后续配置变更失败/删除保留原有最后有效配置，不因这一启动开关重新进入待配置状态。
- 具体发布系统和现场双容器探针尚未核对，不能将代码支持当作发布现场已经达标。完整合同及正式设计路径 `workitems/4-sandbox-api-config-secret-wait/spec.md` 尚待最终确认。

先前询问的 crash 版本和退出日志已不是本项当前目标的必需前提；后续信息应围绕上述发布阻塞问题收敛。

## 工作边界

本轮同步用户已明确的需求更正、两项后续决定及实际设计取证，完整 Why/What 尚待最终确认，未编写设计定稿。独立评审、实现、人工验收与源码交付均未进行；没有创建开发分支或源码 worktree。后续如开展代码开发，须按 `.project/business-instructions.md` 成功刷新并核验最新 `upstream/master` 后建立隔离分支，记录并核验基线。

项目未配置 Aone 后端，本次不进行外部系统同步。
