---
title: OpenAI Agents API 自托管沙箱接入设计
creation-date: 2026-09-17
last-updated: 2026-09-18
status: implementable
---

# OpenAI Agents API 自托管沙箱接入设计

## 摘要

sandbox-manager 增加与 E2B 平行的 OpenAI Agents APIController，共享 Manager，并将健康检查与已有 metrics 移入独立管理入口。业务继续直接使用 OpenAI；本系统只负责自托管沙箱的供应、初始化、休眠唤醒与清理。

Manager 以 ActivateSession、DeactivateSession、CloseSession 提供通用生命周期。Session 由带 Key 的幂等领取记录表达，不增加独立 Binding 存储；sandboxcr 用确定名称的 SandboxClaim 承载任务。Webhook 在操作被持久化接受后返回，不等待 executor 连接。PostClaim 纳入完整领取尝试，失败清理后由原有调谐循环重试。

首版以 scale expectation 约束缓存延迟下的重复领取，以接口前限流保护入口，主节点轮询只兜底清理。设计接受休眠与新 Turn 的竞态，以及切主极端窗口下不保证严格唯一的边界，不引入额外任务系统或恢复平台。

## 背景

OpenAI Agents API 承担模型推理、工具调度和对话管理，工具执行仍然需要计算环境。使用自托管环境的业务希望由自己的基础设施控制镜像、计算资源和隔离策略，同时继续通过 OpenAI 提交输入、获取结果。

sandbox-manager 已提供沙箱领取、连接、超时管理和释放能力。本设计为其增加与 E2B 平行的 OpenAI Agents API 接入，将 OpenAI 的环境连接请求转换成通用的 Sandbox Session 生命周期操作。业务应用不必另外领取沙箱；sandbox-manager 也不代理业务应用与 OpenAI 之间的对话请求。

接入的主要问题不是转发工具调用，而是跨服务的生命周期协调：Webhook 可能重复，领取可能跨越进程重启，缓存不能立即观察到写入，OpenAI Session 删除也不等于沙箱被回收。因此，需要明确持久化接受、完整交付、环境连接三个不同的时点，以及重试、并发和清理分别由谁负责。

## 设计终态

### 1. 接入方式与责任边界

同一部署同时支持 E2B API 和 OpenAI Agents API。两套 API 使用独立端口、独立 APIController，分别由 `--enable-e2b-api` 和 `--enable-openai-agents-api` 控制，在同一进程内共享一个 SandboxManager。入口函数只负责依赖装配和组件启动。

独立管理入口承载 `/livez`、`/readyz` 和已有 `/metrics`，业务 APIController 不再承载这些接口。管理入口面向部署内部；存活和就绪检查反映本进程、共享核心与已启用 API 的状态，不以某个 Session 的健康或 OpenAI 的远端可达性作为整个服务就绪的条件。此处只迁移已有 metrics，不增加新的指标。

禁用的 API 不初始化其专属凭证与配置。已启用组件的初始化失败必须显式报告，不能静默退化成另一套 API；两套业务 API 均未启用也属于配置错误。

| 层次或组件 | 负责的契约 | 不承担的职责 |
| --- | --- | --- |
| APIController | 协议解析、认证、事件与错误映射、OpenAI 状态查询、接口前限流 | 直接访问 SandboxClaim 或其他后端资源 |
| SandboxManager | 通用 Session 生命周期、沙箱业务编排、通过中立接口访问 Infra；提供进程主节点判断 | OpenAI 事件模型、HTTP 语义、直接读写沙箱后端 CR |
| Infra | 幂等领取、后端查询、状态更新与删除的持久化语义 | OpenAI 协议和 Manager 业务策略 |
| agent-sandbox-controller | 独立调谐 Kubernetes 沙箱资源与领取任务 | 依赖 API、Manager 或其 Infra 实现 |

依赖方向保持 API → Manager → Infra。Controller 与 sandbox-manager 需要复用的执行能力必须属于真正中立的组件，不能通过共享包隐藏反向依赖。

OpenAI 向 APIController 发送 Webhook，APIController 在需要时向 OpenAI 查询 Session；Sandbox 内的 executor 则主动连接 OpenAI，直接交换工具命令和结果。APIController 不在工具执行的数据通路上。该分离遵循 [OpenAI 自托管连接模型](https://developers.openai.com/api/docs/guides/agents-api/environments/self-hosted)。

### 2. 数据模型与生命周期

**OpenAI Session** 是 OpenAI 管理的对话对象。**Sandbox Session** 是 Manager 管理的通用沙箱会话，其标识在本接入中来自 OpenAI Session ID，逻辑上与一个 Sandbox 一一对应。

Sandbox Session 不增加独立的 Session、Binding 数据库存储或消息队列。它由带 Key 的持久化领取记录及其结果表达：尚未领取成功时可以只有记录，没有 Sandbox；领取成功后由该记录找到 Sandbox。OpenAI 的环境 ID、连接地址是初始化数据，不构成新的 Manager 领域对象。

三个核心接口的语义如下：

- **ActivateSession** 接受 session-id、template、pauseAfter、shutdownAfter 等参数，并支持 `CreateIfMissing`。允许创建时，通过幂等 Claim 获取或加入领取任务，再通过 Connect 唤醒 Sandbox、更新超时；禁止创建且 Key 不存在时直接返回不存在，不执行完整领取流程。活动状态使用空 PauseTime 取消待休眠计划。
- **DeactivateSession** 不创建 Sandbox。Session 不存在则成功；Sandbox 已休眠或正在休眠时不唤醒，但刷新 ShutdownTime。对可休眠状态设置延迟休眠时，PauseTime 只允许首次设置或提前，不能推迟。已有领取结果异常不能伪装成新的可领取 Session。
- **CloseSession** 按 session-id 幂等删除领取 Key。不存在则成功；存在时，成功表示后端已接受删除，Sandbox 最终回收，不等待物理清理完成。

超时分为三个独立时钟：

| 时钟 | 默认值与起点 | 含义 |
| --- | --- | --- |
| Claim 总超时 | OpenAI APIController 默认设置 5 分钟，可配置；从任务首次持久化记录的开始时间计算 | 所有 Try、等待与 PostClaim 共用同一领取预算，重试、加入和重启不重置 |
| PauseTime | idle 后默认 30 分钟 | 延迟休眠目标；后续 Deactivate 只能保持或提前，Activate 可以清空 |
| ShutdownTime | 最近一次有效生命周期心跳后默认 24 小时 | 无心跳最长保留期限；活动与 idle 都可刷新，不是 Session 自创建起的固定寿命 |

ShutdownTime 不是连续工具执行心跳。若一次长 Turn 在整个保留期限内没有新的有效生命周期事件，沙箱仍可能到期回收。

### 3. OpenAI 交互与 Webhook 响应

APIController 验证原始 Webhook 请求的签名，解析事件，并将其映射到 Manager 操作。固定模板、凭证与允许处理的环境由部署确定，Webhook 不能指定任意模板或获得额外权限。

| 事件 | 行为 |
| --- | --- |
| `action_required`，类型为 `environment_connection` | 查询并确认连接请求仍有效，取得初始化信息，Activate，允许创建 |
| `in_progress` | Activate 已有 Session，禁止创建；清空 PauseTime、刷新 ShutdownTime |
| `idle` | Deactivate，设置延迟休眠并刷新 ShutdownTime |
| `failed` | 查询并确认 Session 仍失败后 Close |
| 其余事件或其他 action-required 类型 | 首版忽略 |

`in_progress` 表示执行已经开始，不能作为首次提供离线环境的唯一触发点；首次供应由 `environment_connection` 请求驱动。`idle` 也不等于某次 Turn 成功完成，它可能出现在环境连接恢复后、等待输入真正开始前。事件含义见 [Session Webhook 协议](https://developers.openai.com/api/docs/guides/agents-api/sessions/webhooks)。

Webhook 的响应边界不是一律等待 Sandbox Ready，也不是一律看到旧 Key 就成功：

| 操作 | 可返回 2xx 的最早时点 |
| --- | --- |
| 首次领取或加入尚未完成的领取 | 包含初始化所需 PostClaim 的任务已持久化，或确认已有有效任务可加入 |
| 已交付 Sandbox 的激活 | 本次唤醒、续约等目标状态已持久化，不能仅凭旧 Key 存在提前返回 |
| Deactivate | 本次超时更新已持久化，或确认不存在而无需操作 |
| Close | 删除已被后端接受，或 Key 已不存在 |

已知终态失败、无创建权限时 Key 不存在、创建所需模板不存在等情况，应提前返回对应错误。发现 Key 存在不意味着可以将已知失败当作成功接受。

APIController 可以启动后台调用并等待其接受通知，以便及时返回。后台调用继承请求的日志上下文，但不受 HTTP handler 返回后的取消影响；其等待仍受组件生命周期与操作超时约束。进程内 goroutine 只是调用方和等待者，持久化任务才是领取工作的所有者。已接受任务不依赖该 goroutine 存活，也不需要 Manager 主节点重新投递。

OpenAI 要求 Webhook 快速响应；超时和非成功响应可能引起重试，也可能重复投递。因此，2xx 只证明本节定义的接受，不证明执行成功。参见 [Webhook 接收要求](https://developers.openai.com/api/docs/guides/webhooks#handling-webhook-requests-on-a-server)。

Sandbox Ready、PostClaim 成功、daemon 报告 running，以及 executor 与 OpenAI 建立连接，仍是不同的状态。OpenAI 等待离线环境连接的预算与 Claim 总超时各自独立：领取默认 5 分钟不保证赶上 OpenAI 的连接期限；迟到连接不会自动重放已超时的输入。参见 [环境连接生命周期](https://developers.openai.com/api/docs/guides/agents-api/environments/lifecycle)。

### 4. Infra 的幂等领取契约

Claim 保留原有同步返回最终交付结果的形式，通过可选的 **IdempotencyOptions** 统一携带 **Key** 与 **Accepted** channel。不传该选项时，保持普通 Claim 的既有语义；传入时，持久化接受和等待交付成为两个阶段。

Key 是全局唯一的领取标识。同一 Key 必须稳定路由到同一后端身份空间；本设计不新增跨 Infra 的全局协调服务。每次调用可以提供独立的 Accepted channel，由被调用方在本次操作确认已被接受时关闭一次。channel 只通知当前进程中的调用者，不进入持久化记录，也不由调用者关闭。

| Key 对应状态 | Claim 行为 |
| --- | --- |
| 不存在 | 创建持久化任务；成功后通知 Accepted，再等待完整交付 |
| 任务进行中 | 加入原任务并通知 Accepted，等待同一结果 |
| 已成功且 Sandbox 存在 | 确认原任务已接受，直接返回原 Sandbox |
| 已失败 | 返回原失败，不开始新的 Try |
| 曾成功但 Sandbox 已消失 | 返回异常，不删除 Key，不重新领取 |

Key 采用 **first-wins**：以第一个成功持久化的任务为准，后来调用不比较或覆盖 template、PostClaim、领取总超时等任务参数。first-wins 不绕过身份、权限和 Key 原始标识的校验；也不冻结后续 Connect 所管理的生命周期超时。

只有创建新任务才要求验证该次创建的模板。重放已有成功任务不应因后来提供的不同模板、或原模板已被移除而重新领取。取消调用方等待不会取消已持久化的领取任务。

Claim 从不删除 Key。终态成功与失败均保留，只有显式 Close 删除 Key 后才允许同一标识开始新一轮领取。Manager 的 Activate 使用这一接口，但已有 Sandbox 的 Accepted 必须延迟到本次 Connect 状态持久化，不能直接转发旧领取记录的接受通知。

### 5. sandboxcr 的后端表达与删除

sandboxcr 将 Key 映射为确定名称、`replicas=1` 的 SandboxClaim。原始 session-id 保存在受保护的元数据中，用于标识 Sandbox Session 和验证身份；不能直接用作资源名时使用确定性哈希，并校验原始值。发生名称碰撞必须报错，不能加入另一个 Session 的任务。

后端查询统一遵循：

**session-id → SandboxClaim → label selector → Sandbox**

这条查询链完全封装在 Infra 中，Manager 不接触 SandboxClaim 类型或 Kubernetes selector。并发创建同名 Claim 时，后端对象名称的唯一性使调用者加入同一个 Key。缓存观察任务用于等待已有对象和结果，缓存已知的重复加入不需要为每个请求重新读写 APIServer。

Sandbox 被新建或从池中领取时，其对 SandboxClaim 的 OwnerReference 与领取身份在同一次写入中建立，而不是等到 Close 时再扫描补绑。所有权指向 Claim UID，不能保留会阻止回收的活跃池所有者。该模式的沙箱不归还共享池。

Close 对当前 Claim 身份发起带 UID 保护的后台级联删除，先删除 Key，再由垃圾回收处理 Sandbox。UID 保护防止一个在途旧删除误删后来创建的同名 Claim；它不是跨越显式重建周期的永久删除令牌。后台删除不等待 Sandbox 真正消失，符合 [Kubernetes 后台级联删除语义](https://kubernetes.io/docs/concepts/architecture/garbage-collection/#background-cascading-deletion)。

此模式禁用普通 Completed TTL，防止自动删除 Key 破坏幂等记忆。普通 SandboxClaim 的原有生命周期不变。即使 Sandbox 已被 ShutdownTime 回收，Key 仍须保留到 Close；此后 Claim 返回结果消失异常，而非重新补建。

### 6. PostClaim 与完整交付

PostClaim 是领取任务中的声明式后置动作，首版支持有限时长的 run command。它是 **Try 的最后一步**：基础就绪、运行时初始化等前置步骤完成后才执行；命令确实退出且退出码为零，完整 Try 才成功。成功启动命令或 RPC 未报错都不能单独作为完成依据。

PostClaim 与领取参数一起持久化，发生在 Accepted 之前。其执行原语可以服务于共享的领取流程，但本次不新增 E2B 的公开 PostClaim 接口。

PostClaim 失败按一次完整 Try 失败处理：清理本次 Sandbox，再由现有 Reconcile Loop 在剩余总预算内从头尝试。它不在同一个 Sandbox 上维护独立的重试状态机，也不拥有单独的重试预算。清理失败或结果仍不明确时，不能跳过旧实例并不断领取新实例；已取消的领取等待也不能使必要清理直接被取消。

完整 Try 的成功必须有可恢复的持久化判据。不能只根据“selector 找到 Sandbox”或普通 Ready 就增加交付数量。重启后，未完成实例需要继续被识别为未完成或清理对象；只有确认完整 Try 成功的实例才可恢复成领取成功结果。

命令必须支持重复执行，因为执行结果丢失不能证明命令未执行。初始化文件通过完整、原子的发布方式对 daemon 可见，相同初始化内容重复执行无害；不能用不同内容悄悄将已有 executor 重新绑定到另一环境。这是 Sandbox 初始化安全性，不是对后来 Claim 参数增加 first-wins 之外的比较规则。

### 7. 并发与缓存观察

领取并发复用 **scale expectation**，不增加 `selectedSandboxRef` 或独立的唯一绑定记录。它用于阻止同一 Claim 因缓存尚未观察到前一次写入而重复发起领取，不是分布式锁。

Expectation 以 Claim UID 为作用域，覆盖新建 Sandbox、Update 领取已有 Sandbox，以及失败清理的删除观察。在写操作前登记，在对应 informer 事件被观察后满足；Update 领取必须能观察到 Claim 成员关系变化，不能只依赖 Create 事件。

明确未发生写入的错误可以撤销本次 expectation；写入结果不明确时不能按“没有成功”处理。等待超过一般 expectation 时限也不能直接清空记录并盲目再领，必须保留不确定性约束，受 Claim 总超时限制。未完成实例与未观察到的清理都会阻止下一次领取。

正常工作模型是单个活跃 Controller、同一 Claim 的串行调谐、处理前 informer 已同步。缓存同步后可恢复已持久化对象，但 expectation 本身是进程内状态。

<!-- known-limit: Scale expectations do not fence stale writers across leader transitions. Strict uniqueness requires persistent arbitration or fencing if that guarantee becomes necessary. -->

本设计接受这一保证上限：不承诺切主、旧请求仍在途等极端窗口下严格只有一个物理 Sandbox 或 executor。常规模型下的 Session 一对一关系，不应被解释为覆盖所有故障的绝对唯一性。若未来必须提供该保证，需要提升持久化仲裁或写入 fencing 能力，而不是扩展内存 expectation 的承诺。

### 8. 模板、初始化协议与凭证

编排预先创建固定专用模板；当前后端可以是 SandboxSet，但 API 和 Manager 只持有中立模板引用。需要创建而模板不存在时直接报错，不由 Webhook 自动创建模板。

模板提供必要的 runtime、初始化命令、daemon 和 executor，以及 executor 所需的工具、文件系统与权限。Manager 提供通用的受控文件写入能力；本接入通过 PostClaim 的有限 run command 调用模板内初始化命令，将非秘密的环境 ID、OpenAI 提供的连接地址等写入协议文件，不要求 API 直接访问 Sandbox 后端。

daemon 作为容器主进程等待协议文件：文件不存在时持续轮询；文件完整可见后启动 executor，监测子进程，并在 executor 退出后同步退出。长运行 executor 不由一个等待命令退出的 PostClaim 请求托管。本设计不增加 daemon 自有的自动重启策略。

探测接口区分 `pending` 与 `running`：前者表示 executor 尚未启动，后者表示子进程已启动；不可达视为不健康。`pending` 不阻塞领取前置就绪与初始化，否则会形成“先等 executor Ready、再写启动文件”的循环依赖。`running` 不证明 executor 已通过认证或连接 OpenAI。

凭证分成两个独立管理面：

- **服务端凭证**：Webhook signing secret 和查询 OpenAI Session 的 API Key 由部署保存到 Secret，OpenAI APIController 初始化时读取，仅用于对应的验证和查询职责。
- **环境凭证**：environment key 由编排直接注入 Sandbox，sandbox-manager 服务端不保存，不通过 PostClaim、初始化参数、CR 元数据、命令参数或日志传递。

非秘密连接信息和环境凭证不能混为一体。模板内进程使用环境凭证主动连接 OpenAI；业务应用的 API Key 不因此交给 agent 执行环境。凭证角色见 [自托管环境认证说明](https://developers.openai.com/api/docs/guides/agents-api/environments/self-hosted#authentication)。

### 9. 清理兜底与流量边界

APIController 通过 Manager 判断当前副本是否为主节点，仅主节点运行周期清理。它通过 Manager 枚举本接入管理的 Session Key，包括尚未分配 Sandbox 或已失败的领取记录；不在 API 层查询 Kubernetes。失去主节点身份后停止发起新的清理操作。

轮询仅用于异步清理：向 OpenAI 确认 Session 已删除、不存在或仍失败时调用 Close。网络超时、认证失败、限流及其他查询错误都不是删除证据，应保留资源，仍受既有 ShutdownTime 约束。轮询间隔是部署参数。

OpenAI Session 删除不会发送删除 Webhook，也不会代为删除自托管计算资源，因此需要这条兜底路径。业务应用仍直接管理 OpenAI Session，sandbox-manager 不接管应用的关闭和输入提交流程。参见 [Session Webhook 协议](https://developers.openai.com/api/docs/guides/agents-api/sessions/webhooks)。

轮询不补建 Session、不唤醒或续约、不恢复 APIController 后台任务，也不重试已经终态失败的 Claim。领取工作的持续推进由已持久化任务及其 Controller 负责。

首版只复用接口前限流，额度保留为部署参数。超限请求在调用 Manager 或启动后台工作之前拒绝，采用可重试的服务不可用响应。该机制限制入口接受速率，不宣称是跨副本统一的后端并发上限。它不增加事件队列、去重、合并或专门的后端限流，不修改 kubeconfig 和 Kubernetes 客户端配置，也不接入 E2B 配额。

### 10. 已接受的行为边界

延迟休眠以 idle 为信号，并通过后续 Activate 清除 PauseTime，仍然可能与新 Turn 竞态。休眠发生在工具调用期间时，调用可能失败；不保证 OpenAI 会为每次中途断连发送新的连接请求，也不保证重放原工具调用。本设计接受由 Agent 或业务应用处理工具失败，不通过接管输入提交来消除竞态。

<!-- known-limit: Idle-driven pause is not coordinated with new input. Stronger tool continuity requires application-side admission coordination or a different pause policy. -->

同理，重新连接不等于恢复已退出的工具进程。沙箱暂停、唤醒所保留的文件和进程状态遵循底层能力；成功领取后 Sandbox 丢失时返回异常，不悄悄用空白新实例替换工作区。本次不建设替换恢复、产物收集或完整的 OpenAI 托管环境功能对等能力。

这些边界使首版集中于底层沙箱供给：持久化领取任务承担重试，Manager 提供协议中立的生命周期，APIController 负责 OpenAI 交互，轮询只兜底清理。
