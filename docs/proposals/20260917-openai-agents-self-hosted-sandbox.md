---
title: OpenAI Agents API 自托管沙箱接入设计
creation-date: 2026-09-17
last-updated: 2026-09-28
status: provisional
design_status: review-pending
---

# OpenAI Agents API 自托管沙箱接入设计

## 摘要

sandbox-manager 增加 OpenAI Agents API 入口，与 E2B 共享 Manager。业务继续直接使用 OpenAI；本系统负责自托管沙箱的供应、初始化、休眠唤醒和清理，部署探针与已有 metrics 迁到独立管理入口。

Session 用确定名称的 Claim 承载，接受与交付分离。PostClaim 在 WaitReady 和基础初始化后以 root 执行，命令可重入，按原预算在原实例重试；沿用批量汇总 status，不新增逐实例执行记录。上层 API 回查 Session 与 Environment：已连接不因本地错误换新，断线优先恢复原实例；只有确认从未进入 PostClaim 且清理完成的失败允许自动重置。

Close 在删除被接受后即可返回，旧轮清理完成前不允许下一轮领取。模板禁用破坏保留期限的策略，并保留协议文件和工作区。首版保持现有分层与网关鉴权，接受休眠竞态和切主极端窗口下的唯一性边界，不增加 Binding 数据库或恢复平台。

## 背景

OpenAI Agents API 承担模型推理、工具调度和对话管理，工具执行仍然需要计算环境。使用自托管环境的业务希望由自己的基础设施控制镜像、计算资源和隔离策略，同时继续通过 OpenAI 提交输入、获取结果。

sandbox-manager 已提供沙箱领取、连接、超时管理和释放能力。本设计为其增加与 E2B 平行的 OpenAI Agents API 接入，将 OpenAI 的 Session 创建事件与环境连接请求转换成通用的 Sandbox Session 生命周期操作。创建时即可提前供应，减少首次输入时等待环境的时间。业务应用不必另外领取沙箱；sandbox-manager 也不代理业务应用与 OpenAI 之间的对话请求。

接入的主要问题不是转发工具调用，而是跨服务的生命周期协调：Webhook 可能重复，领取可能跨越进程重启，缓存不能立即观察到写入，OpenAI Session 删除也不等于沙箱被回收。因此，需要明确持久化接受、完整交付、环境连接三个不同的时点，以及重试、并发和清理分别由谁负责。

## 设计终态

### 1. 接入方式与责任边界

同一部署同时支持 E2B API 和 OpenAI Agents API。两套 API 使用独立端口、独立 APIController，分别由 `--enable-e2b-api`（默认开启）和 `--enable-openai-agents-api`（默认关闭）控制，未设置这两个开关的既有部署行为不变。两套 API 在同一进程内共享一个 SandboxManager。入口函数只负责依赖装配和组件启动。

独立管理入口承载 `/livez`、`/readyz` 和已有 `/metrics`，面向部署内部，部署探针与 metrics 抓取都使用它。存活和就绪检查能力由 SandboxManager 提供，覆盖共享核心及路由刷新等已启用的共享能力；管理入口与业务 APIController 只负责以 HTTP 暴露这些检查，不自行实现检查逻辑。已启用的业务 API 服务启动失败或运行中停止时，进程以错误退出，不另以就绪状态表达。检查不以某个 Session 的健康或 OpenAI 的远端可达性作为整个服务就绪的条件。此处只迁移已有 metrics，不增加新的指标。

E2B 业务端口保留 `/health` 与 `/kruise/api/health`：前者属于上游 E2B OpenAPI 规范，后者是其定制前缀下的等价路径。二者作为 E2B 协议端点复用 SandboxManager 的存活检查，正常时响应保持 200 OK，不再作为部署探针。`/metrics` 直接迁到管理入口，E2B 业务端口不保留旧地址，也不设兼容期，metrics 抓取与仓库内调用须同步调整。路由刷新等已启用共享能力的就绪条件不能因迁移而丢失。

禁用的 API 不初始化其专属凭证与配置。已启用组件的初始化失败必须显式报告，不能静默退化成另一套 API；两套业务 API 均未启用也属于配置错误。

| 层次或组件 | 负责的契约 | 不承担的职责 |
| --- | --- | --- |
| APIController | 协议解析、认证、事件与错误映射、OpenAI 状态查询、接口前限流 | 直接访问 SandboxClaim 或其他后端资源 |
| SandboxManager | 通用 Session 生命周期、沙箱业务编排、通过中立接口访问 Infra；提供进程主节点判断与存活、就绪检查 | OpenAI 事件模型、HTTP 语义、直接读写沙箱后端 CR |
| Infra | 幂等领取、后端查询、状态更新与删除的持久化语义 | OpenAI 协议和 Manager 业务策略 |
| agent-sandbox-controller | 独立调谐 Kubernetes 沙箱资源与领取任务 | 新增对 API、Manager 或其 Infra 实现的依赖；既有领取引擎的沿用见下文例外 |

依赖方向保持 API → Manager → Infra。sandbox-manager 侧创建、观察和删除 SandboxClaim 的能力按常规分层属于 sandboxcr。

SandboxClaim Controller 现有的领取路径直接调用 sandboxcr 的领取引擎，本接入将其作为经批准的分层例外沿用，范围限定如下：领取引擎只为该模式增加“锁定写入时建立 Claim 归属并替换池所有者”这一行为；Controller 不新增对 `pkg/servers/**` 或 `pkg/sandbox-manager/**` 的包依赖；PostClaim 执行、交付记录、恢复与 expectation 属于 Controller 自有代码，不放入 sandboxcr。

<!-- known-limit: The SandboxClaim controller still reuses the sandboxcr claim engine, a legacy cross-layer dependency. A separate neutral claim-engine proposal, scheduled after this integration, must move the engine and remove this exception. -->

OpenAI 向 APIController 发送 Webhook，APIController 在需要时向 OpenAI 查询 Session 和 Environment，并决定是否需要连接恢复或允许重置；Manager 和 Infra 不解释 OpenAI 状态。Sandbox 内的 executor 主动连接 OpenAI，直接交换工具命令和结果，APIController 不在工具执行的数据通路上。该分离遵循 [OpenAI 自托管连接模型](https://developers.openai.com/api/docs/guides/agents-api/environments/self-hosted)。

sandbox-gateway/Envoy 的路由发布和鉴权保持现状，本接入不新增网关禁入策略、强制 token 或跨路径鉴权改造。因此，“不代理工具执行数据面”不表示沙箱不会出现在既有网关路由中，也不承诺额外的入站隔离。

### 2. 数据模型与生命周期

**OpenAI Session** 是 OpenAI 管理的对话对象。**Sandbox Session** 是 Manager 管理的通用沙箱会话，其标识在本接入中来自 OpenAI Session ID，逻辑上与一个 Sandbox 一一对应。

Sandbox Session 不增加独立的 Session、Binding 数据库存储或消息队列。它由带 Key 的持久化领取记录及其结果表达：尚未领取成功时可以只有记录，没有 Sandbox；领取成功后由该记录找到 Sandbox。OpenAI 的环境 ID、连接地址是初始化数据，不构成新的 Manager 领域对象。

本文中，**Key** 是幂等领取标识，**Claim 任务**是承载它的持久化 SandboxClaim，**接受**指操作已被持久化接纳，**交付**指完整 Try 已成功并持久化。接受、交付和连接 OpenAI 不能互相替代。

三个核心接口的语义如下：

- **ActivateSession** 接受 session-id、template、pauseAfter、shutdownAfter 等参数，并支持 `CreateIfMissing`。允许创建时，通过幂等 Claim 获取或加入领取任务；已有归属明确的 Sandbox 则通过 Connect 唤醒、更新超时，不因 Claim 已失败就绕过原实例。禁止创建且 Key 不存在时直接返回不存在。活动状态使用空 PauseTime 取消待休眠计划；已有实例必须尚未到期且未开始删除，才能续期并唤醒。调用方可逐次允许重置，但后端仅对确认未进入 PostClaim、且旧轮领取与清理均已收敛的终态失败执行 Close 后重新创建；没有成功计数不满足此条件。重置使用旧领取身份作为前提，并发调用只加入已持久化的新任务；正在删除或尚未确认清理完成时返回可重试结果。原领取失败保留为诊断，操作原实例不把失败 Claim 改成成功，也不重新开启其领取预算。
- **DeactivateSession** 不创建 Sandbox。Session 不存在则成功；Claim 仍在领取且确认尚无 Sandbox 时也无操作成功，不取消领取、不修改预算或初始 ShutdownTime，也不保存交付后休眠意图。交付后由后续 idle 安排休眠，没有后续事件则由初始 ShutdownTime 兜底。Sandbox 已休眠或正在休眠时不唤醒，但在尚未到期且未开始删除时刷新 ShutdownTime。对可休眠状态设置延迟休眠时，PauseTime 只允许首次设置或提前，不能推迟。已有领取结果异常不能伪装成新的可领取 Session。
- **CloseSession** 按 session-id 幂等删除领取 Key。不存在则成功；存在时，成功表示后端已接受删除，Sandbox 最终回收，不等待物理清理完成。同一 Session 的新一轮实际领取必须等旧轮清理确认完成；Close 成功不表示可以立即复用 Key 开始领取。

超时分为三个独立时钟：

| 时钟 | 默认值与起点 | 含义 |
| --- | --- | --- |
| Claim 总超时 | OpenAI APIController 默认设置 5 分钟，可配置；从任务首次持久化开始计算 | 包含 Controller 首次调谐前的排队、所有 Try、等待与 PostClaim；重试、加入和重启不重置，只有符合重置条件的新一轮使用新预算 |
| PauseTime | idle 后默认 30 分钟 | 延迟休眠目标；后续 Deactivate 只能保持或提前，Activate 可以清空 |
| ShutdownTime | 最近一次有效生命周期心跳后默认 24 小时 | 无心跳最长保留期限；活动与 idle 都可刷新，不是 Session 自创建起的固定寿命 |

初始 ShutdownTime 以首次创建心跳为起点计算，默认增加 24 小时，并随领取任务一起持久化；sandboxcr 复用 `SandboxClaim.Spec.ShutdownTime` 承载这个绝对时间。Controller 对新建和池内领取的 Sandbox 都应用该期限，不依赖交付后的后台 Connect 存活。领取重试、加入和重启不重新计算初始期限，重置开启的新一轮则以其创建心跳重新计算；后续有效生命周期操作仅按下面的规则延长 Sandbox 的期限。

领取开始时间采用首次持久化的时间基准，例如 Claim 创建时间；不能在首次 Reconcile 或 `Phase` 为空时用当前时间重新起算。任务在队列中已经耗尽预算时，不得再启动领取或 PostClaim。

生命周期更新必须在同一次持久化写入中独立合并两个字段，并以当前实例尚未到期、未开始删除为前提；并发冲突后重新检查该前提，不能凭旧读结果续命。

| 操作 | PauseTime | ShutdownTime |
| --- | --- | --- |
| Activate | 清空待休眠时间 | 只延长，不缩短；需要 Resume 时与恢复目标同次持久化 |
| Deactivate | 未设置时设置，否则取原值与本次目标的较早者 | 独立取原值与本次目标的较晚者 |
| 到期或已开始删除 | 不修改 | 不续期，返回不可继续使用的结果，不自动换新实例 |

Resume 复用 `ResumeOptions.Timeout` 的原子更新契约，将清空 PauseTime、延长 ShutdownTime 与 `Spec.Paused=false` 在同次写入中持久化，同时检查未到期、未开始删除。不能先解除暂停，再单独清除旧 PauseTime，否则 Controller 可能立即再次暂停。

现有整体覆盖的 `Always` 和按单一有效截止时间比较的 `ExtendOnly` 不能直接表达这一契约，不能用它们近似替代按字段合并。到期判断包含等于 ShutdownTime 的时刻；即使尚未物理删除，也不能再由 Activate/Deactivate 续命。

OpenAI 模式在模板和实际待领取实例上均拒绝 `AnnotationReservePausedSandboxDuration`，以及非空的 `Spec.AutoPausePolicy.Resume.OnIngressTraffic`；接入自身也不写入这些配置。现有 ingress 自动唤醒会独立改写 ShutdownTime，不能用于本接入。暂停本身不改变 ShutdownTime；其他原生策略也不得绕过本节的时间合并与到期规则。此兼容性限制不改变 gateway 路由发布和鉴权。

ShutdownTime 不是连续工具执行心跳。若一次长 Turn 在整个保留期限内没有新的有效生命周期事件，沙箱仍可能到期回收。

### 3. OpenAI 交互与 Webhook 响应

APIController 在解码前验证原始 Webhook body 的签名，解析事件，并将其映射到 Manager 操作。固定模板、凭证作用域与允许处理的自托管环境由部署确定，Webhook 不能指定任意模板或获得额外权限。经验证但不属于本部署处理范围的事件返回 2xx 忽略，不能据此操作本地资源。

本接入的所有 OpenAI Session 回查，包括创建事件、连接请求、失败事件和周期清理，都必须使用 `GET /v1/agents/sessions/{session_id}`，并同时发送 `OpenAI-Beta: agents=v1` 与 `Authorization: Bearer ...`。SDK 中的 `beta.agents` 是客户端命名空间，不属于 HTTP 路径。实现可以使用官方 SDK 或遵循同一 wire contract 的直接 HTTP 客户端；本设计不绑定具体客户端。

Session 返回 `status`、`required_actions` 和 `environment.id`，其内嵌 Environment 不包含连接状态。需要决定首次供应、连接恢复或失败重置时，APIController 使用该 ID 查询 `GET /v1/agents/environments/{environment_id}`，沿用相同的 Header 与部署凭证作用域，读取 `pending / connected / disconnected / expired / failed`。这是当前连接状态，不能证明从未执行；公开契约没有 `ever_connected` 之类的历史保证。参见 [Session 查询](https://developers.openai.com/api/reference/python/resources/beta/subresources/agents/subresources/sessions/methods/retrieve)和 [Environment 查询](https://developers.openai.com/api/reference/python/resources/beta/subresources/agents/subresources/environments/methods/retrieve)。

Session 仍有效且 Environment 为 `connected` 时，继续使用原 Sandbox，不因 PostClaim RPC 错误、领取超时或成功记录缺失而 Close 后换新；本地 Key 或实例缺失时也不补建另一个实例。需要连接且当前未连接时，优先对原实例 Activate；`environment_connection` 既可表示首次连接，也可表示断线重连，不能单独授权丢弃工作区。只有本地领取同时满足第 2 节的重置条件，APIController 才允许 Close 后重新 Activate。查询失败或状态不能确认时不推断可重建；Environment 的 `failed`、`expired` 或 not-found 也不等同于 Session 已失败或删除。Session 确认失败、删除和本地 ShutdownTime 到期仍按既定清理规则处理，连接状态不赋予无限保留。

| 事件 | 行为 |
| --- | --- |
| `agent.session.created` | 回查 Session 和 Environment，确认属于本部署的自托管范围且 Session 未失败或删除；已连接时只激活原实例，否则取得完整初始化信息后 Activate，允许首次创建；无需等待 `environment_connection` |
| `agent.session.action_required`，`required_action.type=environment_connection` | 回查 Session 和 Environment，确认仍需处理，取得初始化信息；已连接时只激活原实例，未连接时优先恢复原实例；允许首次创建，失败重置还必须满足本地安全条件 |
| `agent.session.in_progress` | Activate 已有 Session，禁止创建；清空 PauseTime、刷新 ShutdownTime |
| `agent.session.idle` | 不回查 Session，直接 Deactivate；有可操作实例时设置延迟休眠并刷新 ShutdownTime，领取中且确认尚无 Sandbox 时无操作成功 |
| `agent.session.failed` | 查询并确认 Session 仍失败后 Close |
| 其余事件，包括 `function_call` 类型的 action-required | 首版忽略 |

`created` 的连接信息优先使用回查得到的 `session.environment.id` 与 `session.environment.remote_url`；缺失字段允许由同一 OpenAI Session 的已验签事件中的 `data.environment_id` 与 `data.connect.remote_url` 补齐。两处同时提供的值必须一致，冲突或补齐后仍不完整时返回错误，不创建不完整领取任务，也不报告接受成功。事件载荷不能替代当前状态与部署作用域的回查；查询失败时沿用查询错误语义，不能仅凭事件直接创建。回查确认 Session 已失败或删除时不激活，已有本地资源按既有 Close 规则清理。

`created` 与 `environment_connection` 使用相同的 Session Key。两者重复或并发到达时，按 first-wins 加入同一领取任务；不能先持久化缺少初始化信息的 Claim，再等待后续事件补全 PostClaim。已交付实例仍按已有激活规则唤醒和续期，不重放 PostClaim。提前供应意味着尚未提交输入的 OpenAI Session 也可能占用 Sandbox；没有后续生命周期事件时，仍由初始 ShutdownTime 兜底。

若已确认可安全丢弃的失败 Key 被轮询 Close，旧轮清理完成后，一个重复或迟到的 `created` 在本次回查确认 Session 仍有效、Environment 非 `connected` 时，也允许重新预供应，不要求一定等新的 `environment_connection`。这沿用 Key 不存在时的首次创建规则，不增加事件去重系统；已交付或执行结果不确定的 Key 不走这种失败清理路径。

`in_progress` 表示执行已经开始，不能作为首次提供离线环境的唯一触发点；首次供应可由 `created` 或仍有效的 `environment_connection` 请求驱动。`idle` 也不等于某次 Turn 成功完成，它可能出现在环境连接恢复后、等待输入真正开始前。事件含义及 created 连接字段见 [Session Webhook 协议](https://developers.openai.com/api/docs/guides/agents-api/sessions/webhooks)。

Webhook 的响应边界不是一律等待 Sandbox Ready，也不是一律看到旧 Key 就成功：

| 操作 | 可返回 2xx 的最早时点 |
| --- | --- |
| 首次领取或加入尚未完成的领取 | 包含初始化所需 PostClaim 的任务已持久化，或确认已有未开始删除的有效任务可加入 |
| 已有 Sandbox 的激活，包括 Claim 已失败但原实例可操作 | 本次唤醒、续约等目标状态已持久化，不能仅凭旧 Key 存在提前返回 |
| Deactivate | 本次超时更新已持久化，或确认无需操作：Key 不存在，或 Claim 领取中且尚无 Sandbox |
| Close | 删除已被后端接受，或 Key 已不存在 |
| 有效的 `environment_connection` 遇到符合安全重置条件的终态失败 | 旧轮清理已确认完成，且新一轮任务已持久化，或确认已加入他方重建的新任务 |
| 旧 Key 正在删除，或旧轮清理未确认完成 | 不算新的接受；在短等待内不能加入有效新任务则返回可重试错误 |
| 已持久化的终态失败，且确认既不能操作原实例也不允许重置 | 确认原失败后返回 2xx，不启动新的 Try，也不将 Claim 改成成功 |
| 禁止创建的事件，且 Key 确认不存在 | 返回 2xx，记录无需操作的结果，不创建任务 |
| Environment 为 `connected`，但本地 Key 或实例确认不存在 | 返回 2xx，保留本地结果缺失的诊断，不补建另一个实例 |
| 已交付或可能执行过 PostClaim 的原 Sandbox 确认已消失 | 返回 2xx，保留结果丢失的诊断，不自动重建 |

Infra 和 Manager 对不可继续处理的终态失败、禁止创建时 Key 不存在、工作区结果丢失仍返回可识别的原错误，由 APIController 按上表映射成 2xx，表示本次有效投递已处理、无需继续重投；错误原因保留在已有状态或诊断信息中。存在可操作的原实例时，优先执行已有实例的生命周期操作，不能仅因 Claim 终态失败就跳过。2xx 不证明环境可用，不清除 OpenAI 的连接请求，也不等价于让 OpenAI Session 成功。若查询确认 OpenAI Session 本身已失败，仍按 Close 规则清理。

上述 2xx 规则以确认事实为前提。后端状态以已同步的 informer 观察为准：缓存已同步且其中不存在，即确认不存在或已消失；缓存尚未同步、本进程写入后尚未观察到该对象，或 OpenAI 查询失败，都属于不确定情况，不能当作不存在，仍返回可重试错误；不为此改为直接读取 APIServer。只有按上述 wire contract、使用本部署正确作用域凭证发起的查询，且响应可归因于目标 OpenAI Session 不存在时，才能映射为 Session 不存在。错误路径、缺少必需 Header、通用路由或网关 404，以及不能识别为 OpenAI Session not-found 的响应，都是查询失败；处理创建事件或连接请求时不得据此返回 2xx 忽略事件。未持久化的创建失败、创建所需模板不存在等前置错误继续返回对应错误，不能伪装成任务已接受。符合上述条件的 `created` 与 `environment_connection`，仅在本次 Environment 回查非 `connected`、Key 确认不存在且没有旧轮清理阻塞时，允许首次创建或安全失败后的重新供应；不能绕过已有或可能丢失的工作区保护。

APIController 可以启动后台调用并等待其接受通知，以便及时返回。后台调用继承请求的日志上下文，但不受 HTTP handler 返回后的取消影响；其等待仍受组件生命周期与操作超时约束。进程内 goroutine 只是调用方和等待者，持久化任务才是领取工作的所有者。已接受任务不依赖该 goroutine 存活，也不需要 Manager 主节点重新投递。

OpenAI 要求 Webhook 在几秒内响应，超时及非 2xx 会触发最长 72 小时的退避重试；3xx 不会被跟随，投递也可能重复。回查和接受等待必须有短时限，不能在 handler 内等待整个领取预算；无法确认接受且属于临时错误时返回可重试错误。部署必须提供最终 HTTPS Webhook 地址，不依赖 HTTP 重定向。2xx 只证明本节定义的接受、不可操作结果确认或忽略，不证明执行成功。参见 [Webhook 接收要求](https://developers.openai.com/api/docs/guides/webhooks#handling-webhook-requests-on-a-server)。

Sandbox Ready、PostClaim 成功、daemon 报告 running，以及 executor 与 OpenAI 建立连接，仍是不同的状态。OpenAI 等待离线环境连接的预算与 Claim 总超时各自独立：领取默认 5 分钟不保证赶上 OpenAI 的连接期限；迟到连接不会自动重放已超时的输入。参见 [环境连接生命周期](https://developers.openai.com/api/docs/guides/agents-api/environments/lifecycle)。

### 4. Infra 的幂等领取契约

Claim 保留原有同步返回最终交付结果的形式，通过可选的 **IdempotencyOptions** 统一携带 **Key** 与 **Accepted** channel。不传该选项时，保持普通 Claim 的同步调用形式；传入时，持久化接受和等待交付成为两个阶段。

Key 是全局唯一的领取标识。同一 Key 必须稳定路由到同一后端身份空间；本设计不新增跨 Infra 的全局协调服务。每次调用可以提供独立的 Accepted channel，由被调用方在本次操作确认已被接受时关闭一次。channel 只通知当前进程中的调用者，不进入持久化记录，也不由调用者关闭。跨进程加入时，由本地 Infra 确认持久化任务后通知本地等待者。

Accepted 与最终返回结果是两个独立信号：接受前失败不关闭 Accepted，等待方必须同时处理接受通知、调用结束和取消，不能只等待 channel；接受后失败仍通过最终结果报告。已知终态失败或已丢失的交付结果不通过关闭 Accepted 伪装成新的接受，API 层按上一节决定响应。

| Key 对应状态 | Claim 行为 |
| --- | --- |
| 不存在 | 创建持久化任务；成功后通知 Accepted，再等待完整交付 |
| 任务进行中且未开始删除 | 加入原任务并通知 Accepted，等待同一结果 |
| 正在删除或旧轮清理未确认 | 不通知新的 Accepted；在调用短时限内未完成清理则返回可重试结果 |
| 已成功且 Sandbox 存在 | 确认原任务已接受，直接返回原 Sandbox |
| 已失败 | 返回原失败，不开始新的 Try |
| 曾成功但 Sandbox 已消失 | 返回异常，不删除 Key，不重新领取 |

Key 采用 **first-wins**：以第一个成功持久化的任务为准，后来调用不比较或覆盖 template、PostClaim、领取总超时等任务参数。first-wins 不绕过身份、权限和 Key 原始标识的校验；也不冻结后续 Connect 所管理的生命周期超时。

只有创建新任务才要求验证该次创建的模板。重放已有成功任务不应因后来提供的不同模板、或原模板已被移除而重新领取。取消调用方等待不会取消已持久化的领取任务。

Claim 从不删除 Key。终态成功与失败均保留，只有显式 Close 且旧轮清理确认完成后才允许同一标识开始新一轮领取；Manager 的安全重置和轮询清理也都经由 Close。查询原 Sandbox 的能力不以 Claim 成功为前提，Manager 可在保留领取失败诊断的同时对原实例 Connect；不能通过重新 Claim 掩盖失败。已有 Sandbox 的 Accepted 必须延迟到本次 Connect 状态持久化，不能直接转发旧领取记录的接受通知。

### 5. sandboxcr 的后端表达与删除

sandboxcr 将 Key 映射为确定名称的 SandboxClaim。CRD 显式表达通用幂等领取模式，不以是否出现 OpenAI 元数据猜测行为；模式不可变。本接入的 Session Claim 使用 `replicas=1`，这是 Session 与 Sandbox 的映射约束，不是通用 PostClaim 的前提。首次任务的 template、PostClaim、领取总超时等身份和执行参数不可被后来调用覆盖。原始 session-id 保存在受保护的元数据中，用于标识 Sandbox Session 和验证身份；不能直接用作资源名时使用确定性哈希，并校验原始值。发生名称碰撞必须报错，不能加入另一个 Session 的任务。

namespace 由部署配置确定，同一 Key 稳定落入同一 namespace，不从 Webhook 请求取值。Claim 和其 Sandbox 必须同 namespace；领取 owner 使用 Claim UID，而不是某个 E2B API Key 的用户身份。

后端查询统一遵循：

**session-id → SandboxClaim → Claim UID 对应的 owner 索引 → Sandbox**

这条查询链完全封装在 Infra 中，Manager 不接触 SandboxClaim 类型或 Kubernetes selector；复用已有 owner 索引，不在高频查询上依赖全量 Sandbox 过滤。后端缓存必须观察 SandboxClaim 和 Sandbox，并覆盖部署指定的资源范围；相应权限须覆盖任务的查询、观察、持久化和删除。并发创建同名 Claim 时，后端对象名称的唯一性使调用者加入同一个 Key。缓存观察任务用于等待已有对象和结果，缓存已知的重复加入不需要为每个请求重新读写 APIServer。

Sandbox 被新建或从池中领取时，其对 SandboxClaim 的 OwnerReference 与领取身份在同一次写入中建立，而不是等到 Close 时再扫描补绑。所有权指向 Claim UID，并替代原池所有者，使领取后的实例不再计入池的受控成员。该模式的沙箱不归还共享池：模板与待领取实例若启用 cleanup/reuse 则拒绝，Close 以删除 Claim 为入口，由 Controller 清理其成员，不走可能触发回池的通用 DeleteSandbox 路径。

Close 对当前 Claim 身份发起带 UID 保护的删除，删除被接受即可返回。幂等模式的 Claim 从首次创建起就有清理屏障：删除中保留旧 Claim 和同名 Key，停止该轮继续领取；负责删除的 Controller 主动发起并观察旧 UID 的成员清理，待在途归属写入、已领取 Sandbox 及其执行资源的清理均已确认后，才释放 Key，不能只等待 owner 删除后的后台垃圾回收。屏障由 Claim 的 finalizer 或等价后端机制持久化，不依赖 APIController 的等待协程存活；删除处理不能仅因 Claim 总预算耗尽而停止。清理范围包括失败、暂停和已到期实例，不能仅以活跃 owner 索引为空作为完成证据。Sandbox CR 消失但执行 Pod 仍待回收，也不满足清理完成。

同一 Session 只有在旧轮不再存在待清理或结果不明的实例时，才允许下一轮实际领取。UID 保护仅防止旧请求误删后来创建的同名 Claim，进程内 expectation 仅约束本轮观察，二者都不能代替跨轮屏障。单独使用后台级联会先移除 owner，不能满足此要求；参见 [Kubernetes 后台级联删除](https://kubernetes.io/docs/concepts/architecture/garbage-collection/#background-cascading-deletion)和 [Finalizer 语义](https://kubernetes.io/docs/concepts/overview/working-with-objects/finalizers/)。此规则同样约束连接请求重置、轮询 Close 和并发重建，不能把删除中的旧任务当作有效的新接受。

此模式显式使用已有 `TTLAfterCompleted` 的负值语义禁用自动删除，不新增 TTL 禁用字段，也不沿用默认 60 分钟。否则 TTL 不仅会丢失幂等记忆，还会通过 OwnerReference 删除用户沙箱。未启用本模式且未配置 PostClaim 的普通 SandboxClaim 保持既有计数、OwnerReference 和 TTL 生命周期。已交付的 Key 即使其 Sandbox 已被 ShutdownTime 回收，仍须保留到 Close；此后 Claim 返回结果消失异常，而非重新补建。

该模式、PostClaim 和对应状态语义必须由匹配的 CRD 与 Controller 共同支持后才能启用。旧 CRD 丢弃字段或旧 Controller 忽略新模式都不属于受支持的混跑方式，不能静默退回普通领取；回退到不支持该模式的版本时也不能继续处理仍存续的此类任务。

### 6. PostClaim 与完整交付

PostClaim 是领取任务中的声明式后置动作，首版支持有限时长的 run command。它是 **Try 的最后一步**：先完成 WaitReady 和必要的运行时、凭证、存储等基础初始化，再执行 PostClaim；新建和池内领取都必须满足此前提。命令确实退出且退出码为零，完整 Try 才成功。成功启动命令或 RPC 未报错都不能单独作为完成依据。PostClaim 留在领取流程中，不下沉为 Sandbox Controller 的就绪条件，也不改变 Sandbox Ready 的通用含义。

PostClaim 的命令声明与领取参数一起持久化，发生在 Accepted 之前；实际命令执行不属于 Accepted 的等待条件。CR 委托模式由 Controller 执行，并由 Controller 提供运行时 TLS 配置，不依赖发起请求的 sandbox-manager 进程存活。命令时限必须落在原 Claim 剩余总预算内；本次不增加独立执行队列或 worker 隔离，也不新增 E2B 的公开 PostClaim 接口。

首版 PostClaim 命令固定以 Sandbox 内的 `root` 用户执行，与现有 lifecycle hook 的执行身份一致。实际执行方必须在每次 runtime 命令请求中显式传入 `AuthUser="root"`，包括首次执行、领取重试、Controller 重启后的恢复与幂等重放；身份不依赖发起请求的上下文。AuthUser 表示 runtime 解析的 OS 用户，不是 Claim owner、OpenAI 用户或 API Key，也不替代 runtime access token 与 TLS 校验。本次不增加执行用户配置或持久化字段，不修改通用 runtime 客户端的默认身份。模板必须支持 root 执行初始化命令；用户解析失败或权限不足时按 PostClaim 失败处理，不省略身份或切换用户重试。

<!-- known-limit: PostClaim runs only as root in the first version. Templates requiring a non-root identity need an explicit persisted execution-user contract before support can be added. -->

PostClaim 必须可重入，Controller 在原实例、原总预算内通过已有 Reconcile Loop 充分重试，不增加独立重试预算。非零退出表示这次命令失败，RPC 超时或响应丢失表示结果未知，命令成功但 status 写入失败表示结果未持久化；三者保留不同诊断，但都不能触发删除原 Sandbox 并换领。非零退出也可能发生在协议文件已发布之后，不能推断 executor 从未启动。只有能确认该实例此前从未进入 PostClaim 的前置失败，才可在必要清理被观察完成后重新领取；恢复调谐中的一次 WaitReady 失败不能证明此前没有执行过命令。调用方取消 HTTP 等待不取消持久化任务及必要清理。

Claim status 沿用批量汇总的成功计数、阶段和失败原因，不新增逐实例 PostClaim 开始或完成记录，也不增加 Sandbox 交付 label 或 condition。Controller 在完整 Try 成功后按批次汇总持久化，不为每个 Sandbox 的命令执行单独写 status。`Completed`、成功计数为零、Sandbox Ready 和 owner 成员数量都不能证明从未执行。恢复后不能仅凭 owner 或 Ready 补记交付成功；需要时在原成员上重放可重入命令，再汇总结果，重复重放不能重复累计同一成员的成功数。

| 恢复时可确认的事实 | 行为 |
| --- | --- |
| Claim 已记录成功，原 Sandbox 仍存在 | 返回原实例，不重新执行领取 |
| Claim 尚未终态，当前 UID 的已归属成员可确认 | 在已有成员上确认前置条件并重放 PostClaim，按批次汇总；不能因缺少命令记录另领实例 |
| PostClaim 非零退出、RPC 结果未知，或成功但 status 写入丢失 | 在剩余预算内重试原实例，保留相应诊断，不进行失败删除和换新 |
| 整轮确认未进入 PostClaim，且领取写入与实例清理已全部确认 | 可记录为允许安全重置的终态失败；后续是否重置由上层决定 |
| 成员归属、存亡、领取写入、执行或清理结果不确定 | 不推断成功或可重置，也不按缺少的成功数量盲目补领 |
| Claim 已终态失败，但原实例仍存在 | 停止本轮 PostClaim 尝试；保留 Key 与实例，允许上层按现有生命周期恢复连接，不自动换新 |
| 已交付或可能执行过的成员消失 | 返回结果丢失或不确定，不自动替换 |

恢复不改变首次持久化的开始时间与总预算，预算耗尽后停止新 Try 和 PostClaim 请求。成功记录缺失不能将可能已执行的实例归为可丢弃；原实例仍可由 ShutdownTime 到期、确认 OpenAI Session 失败或删除等既有规则回收，无需无限保活。自动重置资格必须来自现有终态原因中可验证的整轮前置失败事实及清理完成证据；没有这样的证据就不自动重置，不能用空 owner 列表或某次失败的阶段补足此前丢失的历史。

这些规则不依赖 `replicas=1`。例如批量 Claim 的 `replicas=2`，A 已执行而 B 的执行结果丢失时，在原 B 上重试；不能用一个 Claim 级布尔值代表两个成员，也不能因只有一个成功计数而领取 C 替代 B。若 B 随后消失且无法确认是否执行过，则停止自动补领，保留诊断。

<!-- known-limit: Without a per-member execution journal, some crash and member-loss cases cannot be classified for automatic replacement. Preserve uncertainty instead of allocating a blank workspace; broader recovery requires a separately approved durable history or workspace recovery contract. -->

初始化文件通过完整、原子的发布方式对 daemon 可见，相同初始化内容重复执行无害；命令失败重试不得清空工作区、启动第二个相同 executor，或用不同内容将已有 executor 重新绑定到另一环境。命令需要保证重复调用和上次执行结果未知时再次调用的安全性。这是 Sandbox 初始化安全性，不是对后来 Claim 参数增加 first-wins 之外的比较规则。

### 7. 并发与缓存观察

领取并发复用 **scale expectation**，不增加 `selectedSandboxRef` 或独立的唯一绑定记录。它用于阻止同一 Claim 因缓存尚未观察到前一次写入而重复发起领取，不是分布式锁。

Expectation 以 Claim UID 为作用域，覆盖新建 Sandbox、Update 领取已有 Sandbox，以及失败清理的删除观察。在写操作前登记，在对应 informer 事件被观察后满足；Update 领取必须能观察到 Claim 成员关系变化，不能只依赖 Create 事件。现有 Create/Delete expectation 用法不能原样满足此要求；需要利用已有 Sandbox informer 的事件回调补齐成员关系与删除观察，不能假设 Claim 调谐会自然收到 Sandbox 更新。

明确未发生写入的错误可以撤销本次 expectation；写入结果不明确时不能按“没有成功”处理。不能继承其他调用处等待一分钟后清空 expectation 并继续领取的策略；超时不构成“上次未写入”的证据，必须保留不确定性约束，受 Claim 总超时限制。未完成实例与未观察到的清理都会阻止针对该份额的替换领取；批量 Claim 的其他确定份额不因此被误算为已交付。Close 或同名 Claim 更换 UID 不能解除旧轮约束，跨轮清理由第 5 节的持久化屏障承接。

正常工作模型是单个活跃 Controller、同一 Claim 的串行调谐、处理前 informer 已同步。缓存同步后可恢复已持久化对象，但 expectation 本身是进程内状态。

<!-- known-limit: Scale expectations do not fence stale writers across leader transitions. Strict uniqueness requires persistent arbitration or fencing if that guarantee becomes necessary. -->

本设计接受这一保证上限：不承诺切主、旧请求仍在途等极端窗口下严格只有一个物理 Sandbox 或 executor。常规模型下的 Session 一对一关系，不应被解释为覆盖所有故障的绝对唯一性。若未来必须提供该保证，需要提升持久化仲裁或写入 fencing 能力，而不是扩展内存 expectation 的承诺。

### 8. 模板、初始化协议与凭证

编排预先创建固定专用模板；当前后端可以是 SandboxSet，但 API 和 Manager 只持有中立模板引用。需要创建而模板不存在时直接报错，不由 Webhook 自动创建模板。

兼容性检查覆盖模板的有效配置及实际领取候选：禁止 cleanup/reuse、暂停保留注解和 ingress 自动唤醒。池内实例可能来自旧模板 revision，当前模板通过检查不能替代实例检查；带禁用配置的候选不得交付给本接入。还须核对其他原生策略是否独立改写 PauseTime、ShutdownTime 或绕过到期条件；仅改变 Paused、且满足本设计期限约束的探针策略不因此一概禁用。未来若支持 ingress 唤醒，其时间写入必须遵守第 2 节相同的合并和到期规则，不能沿用永久保留策略。

模板必须提供可用的 agent-runtime、初始化命令、daemon 和 executor，以及 executor 所需的工具、文件系统与权限。不能因 runtime 缺失而跳过初始化并报告交付成功。沙箱声明 runtime TLS 能力时，实际执行者必须持有匹配的 TLS 配置，缺失或不匹配应失败而非降级明文。镜像内 Codex executor 使用固定的兼容版本，不依赖可变的 alpha 标签自动升级；网络策略必须允许向 `https://api.openai.com` 注册并向 `wss://codex-cloud-environments.chatgpt.com` 建立出站连接。

Manager 提供通用的受控文件写入能力；本接入通过 PostClaim 的有限 run command 调用模板内初始化命令，将非秘密的环境 ID、OpenAI 提供的连接地址等写入协议文件，不要求 API 直接访问 Sandbox 后端。幂等重放不能清空工作区或启动第二个相同 executor。

模板负责保证协议文件和需保留的工作区跨暂停恢复及容器重启仍存在。Stop 删除 Pod 时，需要 PVC 等跨 Pod 保留的存储；仅将文件放在容器可写层或 `emptyDir` 不满足这一暂停恢复契约。采用其他恢复机制也必须实际满足文件保留要求，不能仅凭 Hibernate 配置名称推定可用。已交付实例的 Resume 不重放 PostClaim；首次领取未完成时的幂等恢复仍遵循第 6 节。

daemon 作为容器主进程等待协议文件：文件不存在时持续轮询；文件完整可见后启动 executor，监测子进程，并在 executor 退出后同步退出。长运行 executor 不由一个等待命令退出的 PostClaim 请求托管。executor 意外退出后沿用模板既有的容器重启策略；允许重启时，daemon 重新读取保留的协议文件，以原 `environment_id`、`remote_url` 和仍有效且作用域匹配的 environment key 启动 executor 重连。本设计不增加 daemon 自有重试循环，不因此自动重建 Sandbox，也不依赖 OpenAI 再发 Webhook 才启动恢复。重连方式见 [executor 启动协议](https://developers.openai.com/api/docs/guides/agents-api/sessions/webhooks#start-the-executor)。

探测接口区分 `pending` 与 `running`：前者表示 executor 尚未启动，后者表示子进程已启动；不可达视为不健康。`pending` 不阻塞领取前置就绪与初始化，否则会形成“先等 executor Ready、再写启动文件”的循环依赖。`running` 不证明 executor 已通过认证或连接 OpenAI。

凭证分成两个独立管理面：

- **服务端凭证**：Webhook signing secret 和查询 OpenAI Session、Environment 的 API Key 由部署保存到 Secret，OpenAI APIController 初始化时读取，仅用于对应的验证和查询职责；查询凭证须具备两类读取所需权限。
- **环境凭证**：environment key 由编排直接注入 Sandbox，sandbox-manager 服务端不保存，不通过 PostClaim、初始化参数、CR 元数据、命令参数或日志传递。

非秘密连接信息和环境凭证不能混为一体。模板内进程使用环境凭证主动连接 OpenAI；业务应用的 API Key 不因此交给 agent 执行环境。凭证角色见 [自托管环境认证说明](https://developers.openai.com/api/docs/guides/agents-api/environments/self-hosted#authentication)。

每套接入配置固定一个 organization、project 和 user/service account，environment key 必须与 Session 创建身份的这三个维度一致，且只授予环境连接所需权限。服务端查询凭证和 Webhook 配置也限定于该部署范围。多个业务可以共用这一创建身份，但首版不按事件动态选择所有者、模板或凭证；凭证轮换仍由各自管理面的部署与注入机制负责，不把密钥固化在镜像或 CR 中。

### 9. 清理兜底与流量边界

APIController 通过 Manager 判断当前副本是否为主节点，仅主节点运行周期清理。它通过 Manager 枚举本接入管理的 Session Key，包括尚未分配 Sandbox 或已失败的领取记录；不在 API 层查询 Kubernetes。失去主节点身份后停止发起新的清理操作。

轮询仅用于异步清理，通常在向 OpenAI 确认 Session 已删除、不存在或仍失败时调用 Close；可安全丢弃的前置失败另按下一段处理。只有符合第 3 节 wire contract、作用域正确且可归因于目标 OpenAI Session 不存在的 404 才是删除证据；错误路由、通用网关 404、403、其他认证失败、429、5xx 和网络超时都不是删除证据，应保留资源，仍受既有 ShutdownTime 约束。轮询间隔是部署参数；查询范围仍是本地 Key，不改为扫描整个 OpenAI project，分页或列表中未出现某个 Session 也不等于已删除。

仅当现有终态失败事实能证明整轮未进入 PostClaim 且清理已确认完成时，轮询才可将它作为可安全丢弃的失败候选；Close 前仍回查 Session 和 Environment，确认没有有效的已连接环境，并以该领取身份关闭。零成功计数、超时或断线都不足以进入此分支。已交付及可能执行过的 Key 保留到 OpenAI Session 被确认删除或失败，即使其 Sandbox 已被 ShutdownTime 回收；失败和结果不确定的实例同样受该期限约束。所有 Close 都遵守跨轮清理屏障，关闭前以资源事件和结构化日志保留原因。

<!-- known-limit: Delivered and execution-uncertain session keys persist until the OpenAI session is deleted or fails, so key records and per-key polling grow with long-lived undeleted sessions. Bounding them requires an explicit retention contract that preserves replacement safety. -->

OpenAI Session 删除不会发送删除 Webhook，也不会代为删除自托管计算资源，因此需要这条兜底路径。业务应用仍直接管理 OpenAI Session，sandbox-manager 不接管应用的关闭和输入提交流程。参见 [Session Webhook 协议](https://developers.openai.com/api/docs/guides/agents-api/sessions/webhooks)。

轮询不补建 Session、不唤醒或续约、不恢复 APIController 后台任务，也不重试已经终态失败的 Claim。领取工作的持续推进由已持久化任务及其 Controller 负责。

首版在 OpenAI 接入新增接口前限流，额度保留为部署参数。超限请求在调用 Manager 或启动后台工作之前拒绝，采用可重试的服务不可用响应。该机制限制入口接受速率，不是存续资源总量或跨副本后端并发上限；同步 PostClaim 仍会占用 Controller 的调谐能力，不承诺固定的新 Session 吞吐量。它不增加事件队列、去重、合并或专门的后端限流，不修改 kubeconfig 和 Kubernetes 客户端配置，也不接入 E2B 配额。

诊断复用 Claim status/conditions、资源事件与结构化日志，关联 Session Key、Claim UID 和现有操作追踪；不能把 Webhook 2xx、daemon running 或领取失败当成 OpenAI 的连接结论。终态失败在被重置或清理前由 Claim status 保留原因，区分可确认的前置失败、PostClaim 命令失败和结果不确定；关闭时写入资源事件与结构化日志。这不要求按成员或每次命令执行新增 status 写入。

### 10. 已接受的行为边界

延迟休眠以 idle 为信号，并通过后续 Activate 清除 PauseTime。首版不为 idle 增加状态回查，因此晚到的旧 idle 也可能在较新的活动事件之后安排休眠；PauseTime 的数值单调规则不能消除事件乱序或新 Turn 竞态。休眠发生在工具调用期间时，调用可能失败；不保证 OpenAI 会为每次中途断连发送新的连接请求，也不保证重放原工具调用。本设计接受由 Agent 或业务应用处理工具失败，不通过接管输入提交来消除竞态。

<!-- known-limit: Idle-driven pause is not coordinated with new input. Stronger tool continuity requires application-side admission coordination or a different pause policy. -->

同理，重新连接不等于恢复已退出的工具进程或重放已超时的输入。文件保留须满足第 8 节模板契约，进程状态仍取决于底层能力；容器重启不能恢复被终止的工具调用，也不能保证使已失败或删除的 OpenAI Session 恢复可用。已交付或可能执行过 PostClaim 的 Sandbox 丢失时，Manager 返回异常、有效 Webhook 按第 3 节返回 2xx，不悄悄用空白新实例替换工作区。本次不建设替换恢复、产物收集或完整的 OpenAI 托管环境功能对等能力。

因此，已交付或执行结果不确定的 Session 连续超过保留期（默认为最近一次有效生命周期心跳后 24 小时）没有生命周期事件，或其 Sandbox 以其他方式丢失后，在本部署上不能继续使用：后续连接请求返回 2xx 但不补建，输入在 OpenAI 的连接等待期满后失败。业务应删除并新建 OpenAI Session，删除后由轮询清理本地 Key。提前供应的实例若在首次输入前超过保留期，同样适用：首次输入失败并使 Session 进入 failed，随后按 Close 规则清理。只有能确认未进入 PostClaim 且旧轮清理完成的失败才可重置；没有交付成功记录不代表没有工作区。PostClaim 可重入允许低写入成本的原实例恢复，不提供任意故障后的无损换新保证。

这些边界使首版集中于底层沙箱供给：持久化领取任务承担重试，Manager 提供协议中立的生命周期，APIController 负责 OpenAI 交互，轮询只兜底清理。
