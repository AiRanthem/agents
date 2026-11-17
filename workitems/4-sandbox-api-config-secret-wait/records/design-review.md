# 工作项 4 独立设计审查

结论：**Independent review passed**。未发现由本设计引入或分配给本项但未满足的阻塞问题，没有保留的非阻塞发现或必要证据缺口。获批 v1 合同可实现，设计状态登记为 `implementable`。本结论不构成源码实现授权、代码审查、人工验收或运行验证。

## 身份、授权和输入

- 日期：2026-11-17。
- 主审：Codex（本次独立审查会话，主 agent `/root`）。本会话没有实质编写或修订该设计任何版本；前序作者记录中的 `/root` 属于此前设计会话。主审直接读取完整原文和关键源码完成全部评估，未用作者自检替代审查。
- 授权：用户本次调用 `$review-design workitems/4-sandbox-api-config-secret-wait` 并提供技能入口。此前完整合同的实际用户批准来源见 [decision.md](../decision.md)。项目指令覆盖审查记录、状态同步、提交及普通推送。
- 辅助取证：受派 agent `startup_lifecycle_evidence` 只收集后台、peer、路由初始化和停止的源码事实，不作独立设计裁决，不修改合同或源码。它采用不继承历史的独立任务上下文，原因是适用路由指定了不同模型的取证执行者；没有声称缓存收益或跨模型独立评审。
- 输入项目提交：`cad5fea3b962469b3f01b8f7f0adfb4c691784db`，输入工作区干净。完整输入为 [requirement.md](../requirement.md)、[spec.md v1](../spec.md)、[decision.md](../decision.md)、[context.md](../context.md)，以及项目、主工作区、源码仓库和相关子目录原始指令。无前置工作项。

| 身份 | SHA-256 |
| --- | --- |
| 审查输入 spec.md v1 | `a88d7fb92211cecb7cb76ba3ef3cc0a5fdedf09e726896d04d7d776565710767` |
| 审查输入 requirement.md | `db65ddd1b63840acc9fef3364c82af287ebf5c72a86329ee14d7ce452e72d7a7` |
| 审查输入 decision.md | `3bd7bfd22556144dc130dd78849e8382f53fb58b7d791a70d44fb1bbfeba111f` |
| 状态登记后 spec.md v1 | `cd20e6999ea8e7c89b5210a48493bd3f94bb79d07530f365b53fc01447e8af03` |
| 阶段说明同步后 requirement.md | `2877329af629aa4ca10efbb5aaf635ed9c9111cad75b625babd4f40e82bc0c47` |

设计文件唯一变化为 `design_status: review-pending` → `implementable`，正文逐字不变；需求只更新末尾交付阶段说明，合同和验收目标不变。原用户批准继续覆盖当前合同，版本仍为 1。决定及上下文同步实际发生的审查，不新增产品决定。

## 源码目标和适用性

审查绑定成功刷新、并由 `git ls-remote upstream refs/heads/master` 核验的开源提交 `18096feb1d1089499b1227a3e60dc25476ae072d`。设计原基线为 `d764256be82aa790582b4ce4af98997a5958a30a`；两者之间只有 `pkg/identity/jwtissuer/issuer.go` 及其 principal token 测试变化，未改变本项的启动、配置观察及准入接口，不需要重开已批准的产品取舍。

实际读取的源码主检出 `/Users/sophon/Workspace/OKAWorkspace/agents` 保持 `develop`。成功执行 `git pull --ff-only` 后 HEAD 仍为 `8f02008e8a2a5560fb607a70afc3520d55c636e9`，工作区干净。逐路径差异检查确认本轮直接使用的 main/secretconfig、configreload、E2B core/routes/adapters/keys、Manager core/quota、proxy、peers、peer 安全及 E2E 编排生产文件与上述上游相同。E2B `core_test.go` 的 `EnableWaitSim` 和 Manager `core_test.go` 的 `panicAPIReaderCache` 存在既有缓存辅助类型差异，不改变本轮阅读的配置初始化及启动顺序断言；本轮未运行这些测试。

补充检查的 `pkg/cache/cache.go` 相对上游存在另一工作项已交付的 `PickSandboxSet` 有限等待差异及所需 import；本项所用的 `Run`、事件注册与初始同步实现保持一致，审查没有将整个 Cache 文件误记为相同。

设计上下文将 `deploy/sandbox-manager` 称为开源 Helm 模板不准确：该目录存在于内部 `develop`，但不存在于本次上游。本轮已纠正证据归属；用于核对设计的双容器端口来自上游 E2E [deployment.yaml:57](https://github.com/openkruise/agents/blob/18096feb1d1089499b1227a3e60dc25476ae072d/config/sandbox-manager/deployment.yaml#L57)，没有据此认定现场探针。该事实更正不改变设计合同，不构成阻塞发现。

## 判断和主要依据

**提前 Ready 的目标与接受的影响一致。** `spec.md` 的“开关与适用范围”“就绪与业务激活”将默认关闭、有 Secret 引用才生效、探针就绪与业务可用分开。现有 controller 的 startup/readiness 端口为 7789，Envoy 为 7788，controller liveness 还使用 8080；proxy 的路由刷新监听与 ext-proc 分别在其 `Run` 中绑定，不能只启动独立 metrics 监听。依据：[proxy/server.go:119](https://github.com/openkruise/agents/blob/18096feb1d1089499b1227a3e60dc25476ae072d/pkg/proxy/server.go#L119)。TCP 探针以端口可连接判定成功，startup probe 成功后停止该启动检查；这支持已批准的持续 Ready/503 取舍，但不证明特定发布系统通过。[Kubernetes 探针合同](https://kubernetes.io/docs/concepts/workloads/pods/probes/)、[Pod 生命周期](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#container-probes)。

**所有业务入口的拒绝可在正确责任边界实现。** `spec.md` 的“待配置期间的请求行为”明确要求在依配置的认证、存储、配额及业务处理前拒绝，并覆盖 auth 关闭场景。现有 native/customized 注册共用 `RegisterE2BRoute`，健康和 metrics 在独立注册边界；因此可以保持现有控制 API 错误结构及监听上的例外，而不改正常服务协议。源码：[routes.go:41](https://github.com/openkruise/agents/blob/18096feb1d1089499b1227a3e60dc25476ae072d/pkg/servers/e2b/routes.go#L41)、[framework.go:44](https://github.com/openkruise/agents/blob/18096feb1d1089499b1227a3e60dc25476ae072d/pkg/servers/web/framework.go#L44)。上游 E2B 规范为 503 保留 Error 响应，基本字段为 `code`、`message`，与保留原错误 JSON 的合同相容。[E2B OpenAPI](https://raw.githubusercontent.com/e2b-dev/E2B/main/spec/openapi.yml)。

Envoy 的 `handleRequestHeaders` 先做已有请求分类，再查 Sandbox 路由；`logAndCreateErrorResponse` 已可用 `ImmediateResponse` 指定 HTTP 状态。依据：[ext_proc.go:99](https://github.com/openkruise/agents/blob/18096feb1d1089499b1227a3e60dc25476ae072d/pkg/proxy/ext_proc.go#L99)、[ext_proc.go:176](https://github.com/openkruise/agents/blob/18096feb1d1089499b1227a3e60dc25476ae072d/pkg/proxy/ext_proc.go#L176)。该协议支持在请求头阶段返回本地响应并停止后续转发。[Envoy 协议](https://www.envoyproxy.io/docs/envoy/latest/api-v3/service/ext_proc/v3/external_processor.proto#service-ext-proc-v3-immediateresponse)。设计已排除“ext-proc 不监听造成连接错误”和“Sandbox 的 /health 借控制面例外放行”两个错误实现；共享 proxy 仅接收中立实例准入状态，也符合依赖方向约束。

**配置等待与首次激活边界可复用。** `secretConfigSource` 选择静态来源或精确 Secret watcher；`RunWatcher` 自带独立 namespace/name informer、失败重建与取消，不依赖 Sandbox 缓存启动。Dispatcher 在每个组件首次确认全部所属键后释放一次性 `Initialized()`，后续失败不会重置它。依据：[secretconfig.go:78](https://github.com/openkruise/agents/blob/18096feb1d1089499b1227a3e60dc25476ae072d/cmd/sandbox-manager/secretconfig.go#L78)、[configreload/controller.go:139](https://github.com/openkruise/agents/blob/18096feb1d1089499b1227a3e60dc25476ae072d/pkg/configreload/controller.go#L139)、[configreload/controller.go:192](https://github.com/openkruise/agents/blob/18096feb1d1089499b1227a3e60dc25476ae072d/pkg/configreload/controller.go#L192)。Secret 缺失、形状无效及应用失败保留等待/重试的现有区分，足以支持设计所需的同进程补齐和一次性业务激活，不需要新增回源或轮询。设计也明确没有引入跨组件、同 Secret 版本的事务保证。

**后台、安全和终止不是 HTTP 门禁可以替代的条件。** 当前 `Init → initializeConfiguration → Manager.Run → HTTP → keys.Run` 明确串行；Manager 又拥有 Infra、固定 peer 安全、proxy、成员加入及 anti-drift 的顺序。依据：[e2b/core.go:157](https://github.com/openkruise/agents/blob/18096feb1d1089499b1227a3e60dc25476ae072d/pkg/servers/e2b/core.go#L157)、[e2b/core.go:292](https://github.com/openkruise/agents/blob/18096feb1d1089499b1227a3e60dc25476ae072d/pkg/servers/e2b/core.go#L292)、[sandbox-manager/core.go:426](https://github.com/openkruise/agents/blob/18096feb1d1089499b1227a3e60dc25476ae072d/pkg/sandbox-manager/core.go#L426)。设计已经要求传输入口提前启动与业务/成员职责分开，固定安全校验先于相关入口，配置相关维护不提前访问未初始化存储，初始路由完成后才激活。它没有要求提前运行整个 Manager，因而不存在这一错误路径所必需的设计缺陷。

补充取证确认，`Cache.Run` 等待 cache sync 以及已注册 Sandbox handler 的 `HasSynced`，为现有初始路由事件交付提供同步边界；这不承诺每条事件都能成功投影。[cache.go:315](https://github.com/openkruise/agents/blob/18096feb1d1089499b1227a3e60dc25476ae072d/pkg/cache/cache.go#L315)、[route_source.go:39](https://github.com/openkruise/agents/blob/18096feb1d1089499b1227a3e60dc25476ae072d/pkg/sandbox-manager/infra/sandboxcr/route_source.go#L39)。peer 的 Pod seed 发现不按 Ready 过滤，正常成员监听和加入由 `MemberlistPeers.Start` 决定，启动 proxy 与该调用相互独立；因此提前 Ready 本身不必提前加入成员。[memberlist.go:247](https://github.com/openkruise/agents/blob/18096feb1d1089499b1227a3e60dc25476ae072d/pkg/peers/memberlist.go#L247)。

`spec.md` 的生命周期条款还要求只停止已启动组件、终止后不再激活、转换不重复绑定监听、后续初始化致命错误退出。当前 Controller 在启动中收到信号时仅取消，完整 shutdown 假定所有后台已经 Run；实现新模式时必须兑现更细的生命周期合同，不能直接套用这两个旧分支。现有测试对旧启动取消、同步启动错误及端口绑定错误有明确断言；这是需保留/扩展的验证边界，不是尚未写代码即存在的设计缺失。

具体边界包括 Secret key storage 的 `Stop` 在未 `Run` 时会等待未关闭的 `done`，以及无 context 参数的 anti-drift 停止等待；两者均不能被当作任意阶段可直接调用的统一有界停止机制。[secret.go:398](https://github.com/openkruise/agents/blob/18096feb1d1089499b1227a3e60dc25476ae072d/pkg/servers/e2b/keys/secret.go#L398)、[antidrift.go:409](https://github.com/openkruise/agents/blob/18096feb1d1089499b1227a3e60dc25476ae072d/pkg/sandbox-manager/quota/antidrift.go#L409)。这些已有实现限制已被设计的“只停已启动组件、按有效预算退出”结果约束覆盖，不要求在设计阶段指定新的私有生命周期类型。

**范围和实现成本适当。** 方案复用配置观察与错误响应机制，将启动模式、准入状态和生命周期分别放在实例协调者、API 与 Manager 所属边界，没有承诺新存储事务、指标、诊断 API、Service 隔离或发布系统旁路。默认路径和激活后的热更新明确保留原行为；既有可观察场景可以区分“端口早开”“配置已确认”“缓存/路由已完成”和“终止后误激活”，足以指导后续有意义的验证。内部 helper、并发表示及组件拆分由实现选择，无须新增产品批准。

## 实际检查与结论边界

- 主审完成完整需求、批准来源、设计、相关原始指令和上述关键调用路径的检查，读取配置初始化、观察重试、API 观测路由、启动取消、Manager 安全/启动顺序和 ext-proc 测试的断言；未将测试名称或作者自检视为新模式已覆盖。
- `git pull --ff-only`、`git fetch upstream master`、远端 SHA 核验及关键生产路径差异检查成功。源码主检出无本次代码改动，未创建开发分支或 worktree。
- 受派 agent 完成所分配的只读取证并返回原始路径、输入身份、命令结果及限制；主审核对关键路由同步、seed 选择和停止阻塞点后整合，未把取证结论记为额外独立 Pass。双方均未运行相同业务检查或修改源码。
- 项目记录的 YAML 解析、状态/文档路径一致性、审查输入和登记后 SHA-256、设计正文及需求合同不变、相对链接与 `git diff --check` 检查通过。
- 本轮未执行 Go 测试、race、运行时复现、双容器实测、滚动更新、发布系统或集群 E2E。上下文中前序测试结果仅保留为该会话记录，本轮没有原始输出可据以复用为新运行证据。
- 现场实际探针、额外发布门禁和业务可用性未核验；它们不在本轮设计 Pass 所证明的范围内。持续 Ready/503、可接流量并推进滚动替换、startup probe 不再限制配置等待，均为用户已批准的限制，不重新列为缺陷。
- 后续实现须另有授权，并从届时成功刷新和核验的最新 `upstream/master` 创建隔离分支；实现审查、人工验收和源码交付各自保留独立证据。
