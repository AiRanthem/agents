# 上下文与设计证据

## 来源与当前事实

- 2026-11-17，用户通过 `$explore-design 4-sandbox-api-config-secret-wait` 启动本项设计探索。
- 用户随后明确更正：“需求表达错误，现在等待的时候会出现 0/2 ready ，导致一些发布系统会卡住”。当前问题以该更正为准；不再将缺少配置时立即 crash 作为事实。
- 原先的“进程不感知 startup probe 超时”约束没有被明确撤回。后续提前 Ready 的批准不授权进程自行读取探针配置或推算等待期限。
- 用户随后明确选择“Pod 先变成 2/2 Ready，配置完成前业务返回 503（会接入流量，也可能推进滚动替换）”，并补充“这个需要一个开关控制启动时的行为”。这些新增决定见 [decision.md](decision.md)。
- 用户对随后提交的完整开关合同及设计路径回复“确认”。设计 v1 已据此写入 [spec.md](spec.md)，作者为前序设计会话的 Codex 主 agent `/root`。本次另行获准的独立审查已通过，当前状态 `implementable`，正文合同不变。
- 本项使用未占用编号 `4`，与既有 SandboxSet 工作项无已知依赖或缺陷修复关系。

## 当前源码证据

- 设计 v1 取证时，源码主检出 `develop` 为 `8f02008e8a2a5560fb607a70afc3520d55c636e9`，`upstream/master` 为 `d764256be82aa790582b4ce4af98997a5958a30a`。本次审查已再次成功执行 `git pull --ff-only`，主检出仍为上述干净的 `develop`；`git fetch upstream master` 与 `git ls-remote upstream refs/heads/master` 核验的上游为 `18096feb1d1089499b1227a3e60dc25476ae072d`。新上游仅修改 `pkg/identity/jwtissuer`，没有改变本设计的配置观察、API、Manager 和 proxy 启动接口。本项尚未创建源码分支或 worktree。
- `cmd/sandbox-manager/secretconfig.go` 将非空 `--secret-config` 接入 `configreload.RunWatcher`；`pkg/configreload/controller.go` 使用按 namespace/name 限定的独立 informer。初始配置没有确认前，`Dispatcher.Initialized()` 不会释放启动等待；配置形状无效时等待更新，观察器故障会继续重试。
- `pkg/servers/e2b/core.go` 的 `Init` 等待初始配置，之后 `startComponents` 才运行 Manager、业务 HTTP 和可选独立 metrics/health 监听。`pkg/sandbox-manager/core.go` 在 `Run` 中启动 proxy，`pkg/proxy/server.go` 才绑定路由刷新与 ext-proc 监听。因此配置等待能阻止这些后续监听启动。
- `config/sandbox-manager/deployment.yaml` 的测试编排为双容器：controller 的 startup/readiness 检查端口 7789，envoy-proxy 检查端口 7788。按 `config/AGENTS.md`，它仅是 E2E 测试编排，不能据此确认现场两个容器的探针，也不能证明现场 `0/2` 的逐容器原因。
- 内部 `develop` 的 Helm 模板 `deploy/sandbox-manager/templates/deployment.yaml` 同样使用 controller 的 7789 和 Envoy 的 7788；该目录不存在于本次核验的开源 `upstream/master`，不能称为开源交付证据。本次审查据上游 `config/sandbox-manager/deployment.yaml` 核对这一探针组合；两者都不能代替现场编排取证。现有 legacy TCP 探针入口不能仅靠提前启动独立 metrics/health 监听就满足。
- 官方 Kubernetes 合同中，startup probe 成功前不会运行 readiness probe；Ready 还影响 Service 流量接入。仅提前开放健康端口而继续保持未 Ready，不能满足发布系统等待 Ready 的条件。来源：[Pod lifecycle](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#container-probes)。
- 历史上 PR #857 使用一次性 Secret Get；[PR #1177](https://github.com/openkruise/agents/pull/1177) 的上游提交 `4331416b2266acb4dd062995d55b8adb02be78fd` 引入当前观察与初始化门禁，内部对应提交 `989514c4cdcd68b2be908d2eb9a882374a243db5` 已包含在本地 `ack-sandbox-api-v0.6.14-release.2` 源码标签。该历史不是当前运行镜像或现场发布状态的证据。
- `pkg/proxy/ext_proc.go` 已通过 Envoy ImmediateResponse 返回 HTTP 错误；新模式需要确保待配置请求在这一入口也得到 `503`，不能只保护直连 E2B HTTP。现有健康/观测例外必须限定到控制面端点，不能凭 Sandbox 业务路径也叫 `/health` 就放行。
- `pkg/servers/e2b/keys/mysql.go` 的 `ListLimited` 直接使用 `k.db`，而 `pkg/sandbox-manager/quota/antidrift.go` 会经 quota subject lister 调用它。初始 MySQL 配置完成前数据库尚未发布，因此仅提前运行整个 Manager 并给 HTTP 加门禁不足以建立安全的启动合同；依赖配置的后台工作也要保留其启动前提。
- `pkg/peers/memberlist.go` 的 Pod seed 发现不按 Ready 过滤；成员加入由 `Start` 决定。配置等待期间不因提前 Ready 自动加入成员和承担业务，配置生效后仍须完成原有初始路由处理再开放业务。peer 生命周期只读证据由原证据收集 agent 补充，主 agent 已核对关键源码。

## 已执行的局部检查

以下为前序设计会话记录的检查，由当时的 Codex 主 agent 在上述干净的 `develop` 主检出执行并记录通过。本轮审查未重跑，也未将缺少原始输出的历史断言作为新模式的运行验证。相关生产文件与已刷新上游相同；E2B 测试文件有一处既有缓存辅助函数类型差异，未涉及当时选定测试。

- `go test ./pkg/configreload -run 'Test(DispatcherConvergence|SecretReconcilerPreservesState|WatcherReconcileLogs|RunWatcherRetriesUntilCanceled)$' -count=1`：通过，覆盖现有配置确认、删除后状态保留、实际观察器 reconcile 和重试取消。
- `go test ./pkg/servers/e2b -run 'Test(ConfigurationStartsBeforeInitWait|ConfigurationSourceExitsBeforeInitialization|ControllerSignalDuringStartupExitsCleanly|AwaitStartup)$' -count=1`：通过，覆盖配置门禁与启动取消。

这些检查验证现有等待路径的局部行为，不验证修订后的发布目标，没有执行初始缺失后补建的完整启动、双容器探针、滚动更新、发布系统或集群 E2E。只读历史收集由受派证据收集 agent 完成；没有独立设计或代码评审。

## 设计结论与完整性复核

- 正式合同保存在 [spec.md](spec.md)，用户批准来源保存在 [decision.md](decision.md)。参数默认值、适用范围、初始配置错误分类、Ready/业务状态转换及运行后兼容均已确认，不再保留待选择的旧方案。
- 写入前复核覆盖 Secret 缺失、无效、后端未确认、观察恢复、同进程补齐、后续运行时初始化、启动取消及运行后热更新。关键反例为：仅开放独立健康端口不能满足 7789 探针；未保护 Envoy 入口不能保证业务 `503`；提前运行配置相关维护可能访问未初始化 MySQL。正式合同分别保留实际探针入口、覆盖所有业务入口及后台启动前提。
- 生命周期复核要求首次业务激活晚于配置确认与既有初始路由处理，监听不重复绑定，终止后的晚到配置不能再激活业务，停止不会等待从未启动的 worker。必要安全配置和非配置致命错误不被提前 Ready 掩盖。
- 接受的限制为：新模式可持续 Ready/503，可能接流量和推进滚动替换，不保证业务可用；startup probe 不再是配置等待期限；不新增配置版本的跨组件事务保证。默认模式与无 Secret 引用的静态路径保持原有行为。
- 当前没有待用户决定的设计阻塞项；完整性复核是作者自检，不是独立设计评审。具体发布系统和现场双容器探针尚未核对，不能将设计批准或既有单测通过当作新模式已实现或现场已达标。
- 序列化后已回读设计，确认保留获批合同、三个约定顶层章节和 `review-pending` 状态，不包含文件级实现清单或测试计划。YAML 解析、元数据及批准状态一致性、本地 Markdown 链接与 `git diff --check` 通过；设计与需求的 SHA-256 绑定保存在 metadata 和项目 state 中。

先前询问的 crash 版本和退出日志已不是本项当前目标的必需前提；后续信息应围绕上述发布阻塞问题收敛。

## 工作边界

设计 v1 已由用户确认并通过独立设计审查，随后按用户授权在隔离工作树实现。用户在实现审查后澄清了设计 v2 的控制 API 和 Envoy 行为，并已确认当前补丁通过人工验收。[当前源码与交付状态](#2026-11-18-人工验收与-pr)

项目未配置 Aone 后端，本次不进行外部系统同步。

## 2026-11-17 独立设计审查

- 用户显式调用 `$review-design workitems/4-sandbox-api-config-secret-wait`。审查者为本次独立审查会话的 Codex 主 agent `/root`，没有参与该设计任何版本的实质编写或修订。完整报告见 [records/design-review.md](records/design-review.md)。
- 结论为 **Independent review passed**，没有阻塞发现或必要证据缺口。覆盖开关适用范围、真实探针端口、API/Envoy 准入与健康例外、独立配置观察、后台及 peer 生命周期、取消与失败、默认行为及运行后热更新兼容。主审完成全部判断；受派 agent 仅补充后台/peer 生命周期源码事实，不充当额外独立审查者。
- 设计正文逐字保持不变，仅将 front matter 状态登记为 `implementable`；需求仅同步交付阶段说明，用户合同与验收目标不变。上下文中的 Helm 模板证据归属按本次源码结果纠正，不形成产品决定或新设计版本。
- 实际执行源码刷新、远端基线及关键文件差异核验，并读取现有测试断言。没有执行 Go 测试、运行时复现、集群或 E2E；设计审查不证明新模式已经工作，现场逐容器探针和具体发布系统仍未核验。

## 2026-11-17 实现与验证

- 授权：用户对只读实施方案明确要求“Implement the plan.”；实现者为本会话 Codex 主 agent。设计 v1 正文与其批准的取舍保持不变。
- 主检出保持 `develop`，成功执行 `git pull --ff-only` 和 `git fetch upstream master`。`upstream` URL 与远端 `refs/heads/master` 核验通过；新工作树初始 HEAD 与刷新后的基线均为 `18096feb1d1089499b1227a3e60dc25476ae072d`，与设计审查基线一致，没有失效的设计假设。
- 源码位置：`worktrees/4-sandbox-api-config-secret-wait`，分支 `feat/ready-before-config-261117`。本项全部为社区文件，未修改主检出、内部代码或部署编排；源码尚未提交、推送或创建 PR。
- 实现：启动开关仅与非空 Secret 引用组合生效；Controller 分离配置观察启动与首次确认等待；Manager 可单独启动固定安全配置保护的 proxy 监听，原 `Run` 复用监听并保留运行时及后台任务前提。API 鉴权前的独立 middleware 和 proxy 的中立准入回调共同限制业务，控制面健康/观测沿原入口豁免。配置及运行时完成后一次性激活，终止状态不可逆；部分启动由启动执行者有界清理，只停止已启动的 key worker，quota worker 排空支持退出 context。
- 受影响包完整 race 检查通过：在上述源码工作树执行 `go test -race -p 1 ./cmd/sandbox-manager ./pkg/configreload ./pkg/servers/e2b/... ./pkg/sandbox-manager ./pkg/sandbox-manager/quota ./pkg/proxy -count=1`，9 个包均成功。启动、API 分类、Envoy ImmediateResponse 的首轮窄测试也通过。
- 最终重复检查通过：同一工作树执行 `go test -race -p 1 ./pkg/servers/e2b ./pkg/sandbox-manager ./pkg/sandbox-manager/quota ./pkg/proxy -run 'TestReadyBeforeConfig|TestControllerStartupWaitsForInitialSandboxRoutes|TestAntiDriftStopContextBudget|TestSandboxManagerRun' -count=10 -timeout=180s`，4 个包均成功，覆盖新增场景和真实初始路由同步边界、终止及配额排空预算。`gofmt -l` 无输出，源码及项目 `git diff --check` 通过。
- 最终源码身份：HEAD 仍为初始基线 `18096feb1d1089499b1227a3e60dc25476ae072d`；`git diff --binary | shasum -a 256` 为 `a51ea8ff29aab5e9993d985e57d315217eebdeb9634d4e8ac8857335cbd8fa9c`。12 个已跟踪文件有本项修改，无源码未跟踪文件及无关改动。涉及命令入口、E2B 启动与路由、Manager 启动、quota 停止、proxy 准入及相关测试和配置 Secret proposal。源码分支未发布，后续审查须保留此工作树或建立可复现快照。
- 构建 `go build -o /tmp/oka-ready-before-config-sandbox-manager ./cmd/sandbox-manager` 成功；直接运行该二进制 `--help` 被本机以退出码 137 终止，无输出，提权重复结果一致。`codesign --verify --verbose` 验证有效，尚不能确认该输出路径的系统终止原因。
- 随后在最终源码工作树运行 `go run ./cmd/sandbox-manager --help` 成功（启用 pipefail 并筛选帮助输出），确认 `--ready-before-config` 及其 Secret 适用范围已注册，默认关闭。Go 临时构建路径下的 CLI 启动验证有效；上述独立输出路径的异常没有被归因为代码缺陷，也没有执行普通业务启动或部署。
- 独立代码审查未执行。没有执行真实 Envoy、双容器 Ready、滚动替换、具体发布系统、集群 E2E、部署或人工验收。本机无可用 Envoy/容器运行设施，协议单测不能代替这些现场结果。

## 2026-11-18 独立实现审查

主审及三名独立专项审查者审查了当前 11 个已暂存文件，结论为 **Changes required**。与上一节的 12 文件实现快照相比，本轮以不同的完整 diff 指纹重新验证。两批定向 race 测试均通过。Envoy 准入、等待期请求头日志、终止信号与首次开放的竞争、静态端口冲突和 tracing 错误码仍需修正。审查对象、源码行号、验收条件及运行命令见[审查报告](records/code-review.md)。

## 审查后复核

用户确认了 Envoy 接流和控制 API 在等待配置 Secret 时的拒绝语义。[当前合同](spec.md)为 v2。已同步源码 proposal、控制 API 准入注释和参数帮助。原审查第 1、5 项撤回。第 2 项保留凭据日志问题。第 3、4 项用临时 Go overlay 验证了真实启动仲裁与监听冲突。[复核记录](records/code-review.md)区分了运行证据与源码推导。

## 2026-11-18 修复第 3、4 项

用户要求“帮我修复3、4”。Codex 在 `feat/ready-before-config-261117` 的现有工作树修改 CLI 参数校验、启动仲裁及各自的既有测试。仲裁在启动成功与终止信号均已就绪时消费该信号，走优雅退出分支，控制 API 保持关闭。启动失败仍返回原错误。

CLI 在等待初始配置前校验 memberlist 的有效端口与控制 API、metrics、路由刷新和已启用的 ext-proc 监听。沿用当前非正 memberlist 端口取默认值的规则。关闭 ext-proc 时其端口可用于 memberlist。成员加入仍在运行时初始化阶段。

回归断言在修复前分别观察到信号漏消费和错误端口通过校验。修复后在源码工作树执行 `go test -race -p 1 ./cmd/sandbox-manager ./pkg/servers/e2b -run 'Test(ValidateListenerPorts|AwaitStartup)$' -count=100`，两包均通过。实际执行 `go run ./cmd/sandbox-manager --peer-selector=app=test --ready-before-config --secret-config=test/config --memberlist-bind-port=7789` 时使用空 kubeconfig，程序在参数校验阶段以状态 255 退出，错误明确指向路由刷新监听冲突。两个受影响包的完整测试也通过了 `go test -race -p 1 ./cmd/sandbox-manager ./pkg/servers/e2b -count=1`。变更 Go 文件格式检查及 `git diff --check HEAD` 通过。

工作树 HEAD 为 `18096feb1d1089499b1227a3e60dc25476ae072d`，完整工作树 diff SHA-256 为 `ae6bfb279c1cadd8ba579d04a3794748d1c9e53cf591a8bd40b6cd7056f87ca0`。源码保持未提交，原 11 文件暂存差异指纹仍为 `b01ef90f9c9b8e9c4c1422fb93393f05bb1c67d84d63ed1fe354873de7520c8f`。第 3、4 项的当前证据为本地修复与回归，第 2 项仍待处理；独立复审及集群验证尚未执行。

## 2026-11-18 人工验收与 PR

- 用户确认已完成人工验收，并确认发布普通 PR。[决定来源](decision.md#2026-11-18-人工验收与发布决定)
- 验收的 12 文件补丁已提交并无冲突地对齐刷新后的 `upstream/master`（`b6cd98608a81cf93d4ef2c0a92313bf2a29d1ee2`）。完整补丁的 SHA-256 与采集时一致，12 个文件均属于社区范围。源码提交 `b37d3430ebeb7119d2c91e6c66499afa8049c7d5` 已推送至 `AiRanthem/agents:feat/ready-before-config-261117`，并回读核验远端分支与 PR 的 head 一致。
- 在该提交执行 `go test -race -p 1 ./cmd/sandbox-manager ./pkg/configreload ./pkg/servers/e2b/... ./pkg/sandbox-manager ./pkg/sandbox-manager/quota ./pkg/proxy -count=1`，9 个包全部通过。
- [PR #1237](https://github.com/openkruise/agents/pull/1237) 已向 `openkruise/agents:master` 创建并核验为普通、开放的 PR。GitHub 检查已启动，合并待定。当时独立实现审查第 2 项请求头日志仍待处理，第 3、4 项仍待独立复审。部署和现场验证无新增证据。

## 2026-11-20 工作树清理

按用户要求移除了 `/Users/sophon/Workspace/OKAWorkspace/projects/oka-daily-open-source/worktrees/4-sandbox-api-config-secret-wait`。移除前核验 Git 状态干净且没有进行中的 Git 操作或嵌套仓库，移除后核验目录和 Git 工作树登记均已消失。本地分支 `feat/ready-before-config-261117` 保留。查询时 PR #1237 仍开放，head 为 `e92212ffb849987b83c1989e1f5c38469970a49a`。[PR #1237](https://github.com/openkruise/agents/pull/1237)

移除前后回读确认 `git@github.com:AiRanthem/agents.git` 的 `refs/heads/feat/ready-before-config-261117` 均指向 `e92212ffb849987b83c1989e1f5c38469970a49a`。从 OKAWorkspace 根目录执行以下命令可恢复原快照，即使远端分支随后前移。

```sh
git -C agents fetch git@github.com:AiRanthem/agents.git refs/heads/feat/ready-before-config-261117
git -C agents worktree add --detach "$PWD/projects/oka-daily-open-source/worktrees/4-sandbox-api-config-secret-wait" e92212ffb849987b83c1989e1f5c38469970a49a
```

原工作树内被 Git 忽略的 `.vscode/` 与 `tags` 已移至本机 `local-storage/pr-worktree-cleanup-261120/4-sandbox-api-config-secret-wait/`，目录结构保留。
