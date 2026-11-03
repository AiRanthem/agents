# IM Webhook 唤醒独立设计审查

日期：2026-11-04。本报告是普通项目的 report-only 设计审查，不是自主推进、实现评审或人工验收。

## 逐项结论

| 审查范围 | 结论 | 依据与边界 |
| --- | --- | --- |
| `2-feishu-wake-openclaw`：整体 Webhook 能力、子项边界和集成验收 | **Unable to conclude** | 已确认的内存接收与正常下线契约具有可行实现路径，拆分及依赖合理；但接入配置/授权身份和应用交付协议仍存在必要未决契约（G1、G2），无法对完整链路给出独立通过。 |
| `21-webhook-gateway-code`：Gateway 接收、唤醒、交付及排空代码契约 | **Unable to conclude** | 单独审查了本项和继承的父项契约。正常下线子契约未发现阻塞性设计缺陷；但本项并非仅做 drain，还负责完整接收和应用交付，因此同样受 G1、G2 限制。 |
| `22-webhook-ack-orchestration`：实际 ACK 编排接入契约 | **Independent review passed** | 独立检查后，编排职责、先业务 drain 后 Envoy drain/TERM 的顺序、65/5/30/20 秒预算、失败继续退出和代码/镜像前置条件相互一致；其需求明确把具体接口绑定交给已交付的 21，未要求本项替代 21 决定业务接收协议。此结论只覆盖当前编排语义契约，不代表前置已交付或可以立即实施。 |

本轮没有证明候选设计已规定了某个必然错误的实现，因此没有使用 `Design changes required`。父项与 21 未通过的原因是明确可定位的必要未决契约，不是缺少 `spec.md`，也不是没有执行尚未实施的功能。本报告不直接写入任何 `implementable` 状态。

## 必要未决契约

以下是影响结论的输入缺口，和已证明的设计缺陷分开记录。严重性列表示缺口的潜在验收影响，不表示已观察到相应事故。

### G1：尚未选择应用交付和有效接收确认协议

- **影响级别：High；归属：父项 2 的共享契约、子项 21 的实现输入。** 子项 22 只消费排空结果，不拥有这项业务决定。
- **原文定位：** `workitems/2-feishu-wake-openclaw/requirement.md:31`、`:41-47`；该项 `context.md:25-38`、`:51`；`workitems/21-webhook-gateway-code/requirement.md:14`、`:24-26`。这些原文要求等待“应用有效确认接收”，同时把具体应用协议和交付完成判据保留为待决。
- **触发场景：** Gateway 已内存登记并对飞书确认，Sandbox 恢复后向应用发送事件。应用返回普通 HTTP 200；或应用实际接收了事件但响应丢失；或事件在正常运行期因重试/积压延迟较久后再投递。排空线程必须在这些场景里决定成功、重试还是失败终态。
- **后果及违反的可观察要求：** 目前无法确定哪种应用响应结束交付责任，也无法确定交付使用原始飞书信封、可信中继还是另一个应用接收接口。只以“HTTP 200”作为成功可能把 challenge 或不承担消息接收责任的响应算成交付；任意解析后重建 body 又可能破坏现有验签。这样无法判断父项 `requirement.md:37` 所要求的“事件交给应用”及 21 的 60 秒排空成功标准是否成立。上述是具体候选路径的差异，不是声称作者已经选择了这些错误路径。
- **独立核对的原始证据：** OpenClaw 固定提交 `0a0d601bf12dfea5e4c94c3e8cd6d823c405d9a0` 的 [monitor.transport.ts:66-75](https://github.com/openclaw/openclaw/blob/0a0d601bf12dfea5e4c94c3e8cd6d823c405d9a0/extensions/feishu/src/monitor.transport.ts#L66-L75)、[105-138](https://github.com/openclaw/openclaw/blob/0a0d601bf12dfea5e4c94c3e8cd6d823c405d9a0/extensions/feishu/src/monitor.transport.ts#L105-L138)、[507-528](https://github.com/openclaw/openclaw/blob/0a0d601bf12dfea5e4c94c3e8cd6d823c405d9a0/extensions/feishu/src/monitor.transport.ts#L507-L528) 分别规定 durable 响应标志、一小时签名时间窗/原始 body 验签和 challenge 普通 200 的区别。[feishu-ingress.ts:397-429](https://github.com/openclaw/openclaw/blob/0a0d601bf12dfea5e4c94c3e8cd6d823c405d9a0/extensions/feishu/src/feishu-ingress.ts#L397-L429) 等待 `monitor.admit` 后才返回 durable。原始代码由 reviewer 独立下载阅读，并非只复述项目研究结论。
- **所需结果：** 设计所有者确定首期支持的应用接收能力/兼容前提，明确请求载荷及鉴权、成功接收证据，以及超时/响应丢失/拒绝接收对应的重试和最终失败责任。可以限定短期内存存活时间以复用原签名，也可以选择其他经过批准的交付协议；本报告不代替用户选择。无需引入持久队列，也无需保证模型完成或业务恰好一次。内部重试实现、私有类型、具体调用库可由实现者决定。
- **不确定性：** 所查 OpenClaw 快照不是实际部署版本。本轮没有证明真实部署不兼容，也没有要求先部署才能审查；缺少的是设计要支持什么接收契约，而非现场成功证据。只要候选明确支持的协议和兼容前提，版本核验可以按实现/集成阶段职责完成。正常下线的 60 秒上限也不等于正常运行期所有内存事件的总存活上限，不能用它自动消除签名时间窗问题。

### G2：接入配置、授权目标身份及开关变化的外部语义尚未收敛

- **影响级别：High；归属：父项 2 的共享契约、子项 21。**
- **原文定位：** `workitems/2-feishu-wake-openclaw/requirement.md:14-16`、`:23`、`:41`、`:45-47`，该项 `context.md:48-52`；`workitems/21-webhook-gateway-code/requirement.md:9-11`、`:26`。原文已要求正确目标和未授权不恢复，但仍把目标身份、凭据配置责任、接入配置与开关变化处理列为待决。
- **触发场景：** 一个接入已绑定 Sandbox A，并有已 ACK 的内存事件等待执行；配置随后改为 B、A 被删除或同名重建，或用户关闭自动唤醒以保持 Pause。执行器此时必须知道沿用接收时目标与权限，还是重新解析/重新授权；新请求和已接收任务也必须有确定的处置方式。
- **后果及违反的可观察要求：** 只知道“单接入绑定一个已有 Sandbox”，不足以判断旧事件是否允许唤醒变更后的对象，也不足以判断关闭开关能否阻止积压事件把 Sandbox 再次恢复。这涉及用户可见的配置/存储契约和授权范围，直接影响父项 `requirement.md:11` 的持续 Pause 用法、`:14` 的正确目标与授权，以及 21 的非法事件不得恢复约束。报告没有认定代码已发生越权；问题是当前输入无法判定哪一种执行结果才被批准。
- **独立核对的原始证据：** ACK 镜像对应的 agents `e55d70c7fc7d603e8a585918919788edd0374e31`，`pkg/sandbox-gateway/filter/filter.go:146-149` 在恢复前执行当前流量认证，`:310-344` 在唤醒前检查 Sandbox UID；`wake/wake.go:69-108` 提供 UID 与开关读取。这证明旧流量路径已经区分对象身份与名称，并不证明 Webhook 接入配置或其异步权限语义已经存在。当前普通流量认证依赖请求头/route（`filter.go:211` 起），不能直接当作飞书来源认证和 Sandbox 授权绑定已经解决的证据。
- **所需结果：** 在不改变“单接入单已有 Sandbox”“开关开启可唤醒手动 Pause”决定的前提下，明确首期接入的对外配置/管理责任、平台认证身份到目标的授权绑定，以及变更/关闭/目标消失时对新请求与已接收任务的行为。无需在审查中固定内部存储结构或新增 CRD；这些可在批准的对外语义下由实现者选择。
- **不确定性：** 目前可行实现不止一种，且已有源代码提供部分可复用检查。缺少的是可观察配置与生命周期契约，不是缺少某个 Go helper。若设计所有者能证明既有、已批准的外部配置契约完整覆盖这些规则，可以引用它收敛，无须重做已确认业务决定。

## 已确认部分的独立判断

### 内存接收和任务生命周期

父项 `requirement.md:13`、`:29`、`:37` 与 21 `requirement.md:10-16` 清楚限定了可靠性：先登记再 ACK，任务由进程持有，允许进程退出丢失。停收与登记互斥，避免把 drain 时刻的并发请求排除在任务统计之外；ACK、请求取消和 stream 销毁不终止任务，且禁止随后调用已销毁 stream 的 API。这些结果约束足以指导并发实现；无需审查者预先选择锁、队列或 goroutine 结构。

独立读取现有 `filter.go:160-172`、`:347-392`、`:497-507` 后确认，原普通流量路径在等待完成前仍挂在 Envoy stream 上，OnDestroy 会取消其 context。新 Webhook 后台交付因此确实需要独立任务所有权；当前契约已经覆盖这个新增差异，没有把旧 stream 实现误当成可直接复用的后台队列。

精确队列容量、工作并发、内部缓存类型和恢复合并算法本身可以由实现者选择，不因文档尚未写具体数字而单独阻塞。所选方式仍需实现批准后的满载接收结果、成功/失败责任、稳定事件身份和终止上限；这些对外结果与 G1、G2 一起收敛。没有依据要求跨 Gateway 持久去重、强可靠或无限重试。

### 正常下线与 60 秒上限

`evidence/ack-gateway-webhook-shutdown.md:67-74` 及 21 `requirement.md:12-16` 明确了完整顺序：本地管理入口原子停收，readiness 失败但保留路由/peer/outbound，等待已登记任务，首次停收起 60 秒绝对截止，到期取消并记录，随后 Envoy drain，最后 TERM 清理。重复 drain 沿用原截止，调用方断连不撤销停收。这些契约覆盖了接收/停收竞争、已 ACK stream 销毁、提前关闭依赖、重复 hook 和有界退出。

独立读固定源码确认：`server/server.go:44-53` 的 `ProcessStopTimeout` 是 8 秒；`:400-417` 清理 HTTP server、peer 和 outbound；`filter/config.go:178-191` 在 Config.Destroy 调用该清理。`cmd/sandbox-gateway/main.go:54-95` 启动路由/controller/peer。把业务排空安排在 preStop，避免使用这段 8 秒清理等待 10 秒唤醒，具有实际依据。

readiness 与内部 registry readiness 必须分开这一要求也有依据：固定版本 `filter.go:116-132` 用 registry readiness 阻止路由，`server.go:243-257` 又用 registry readiness 生成探针结果；若直接把 registry 设 false，会影响排空所需请求。候选明确禁止这种做法，未发现与当前源码不可调和的约束。loopback 管理入口也避免在同时承担 peer refresh/TLS 的 system listener 上暴露无鉴权停机操作（`server.go:261-266`、`:298-315`、`:344-365`）。

### 实际 ACK 编排与总预算

读取和重新渲染的依据仅来自 ack-components 的实际组件包 `addons/ack-sandbox-manager/main/v0.6.14-release.1`，未使用 agents/config 示例：

- `charts/ack-sandbox-manager/templates/sandbox-gateway.yaml:41-43` 当前 grace 为 `drainTimeSeconds + 60`；`:85-86` 传入 Envoy drain 时长；`:143-151` 为 curl 最长 5 秒后 sleep drain 时长。
- `charts/ack-sandbox-manager/values.yaml:281-301` 当前 liveness 是 7788 TCP，readiness 为 system `/readyz`；`:305-319` 的 admin 默认只监听 loopback，system 端口 7789；`:338-339` 默认 drain 30 秒。
- `configs/default.yaml:12-15` 为 `acs/ack-sandbox-gateway:v0.6.0-release.1`；`component.yaml:45` 映射到含 `e55d70c7f` 的 dev 镜像。对应 Dockerfile 第 18 行固定 Envoy `contrib-v1.37.3`。

新预算的算术及生命周期匹配：服务端业务等待不超过 60 秒，调用侧上限 65 秒；随后 Envoy 调用 5 秒、连接 drain 30 秒，单次 preStop 调用预算最多约 100 秒，120 秒总 grace 预留约 20 秒用于 TERM 后退出和调度开销。自定义 drain 时长按同一关系增加总 grace。该预算是有界正常终止的目标配置，不是对调度停顿/节点故障的硬实时保证。

Kubernetes 官方 [hook 契约](https://kubernetes.io/docs/concepts/containers/container-lifecycle-hooks/) 确认 preStop 在 TERM 前完成，且消耗同一个总 grace；[Pod 终止流程](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#pod-termination-flow) 确认 EndpointSlice 摘流与节点终止并行，不能替代应用原子停收。[Envoy 1.37.3 drain 文档](https://www.envoyproxy.io/docs/envoy/v1.37.3/intro/arch_overview/operations/draining) 确认 graceful drain 期间仍可接收新连接。因此当前 90 秒/旧 hook 的不足属于已被本项明确承担并覆盖的基线差异；不能把它再列为候选新方案未修复的缺陷。

固定 10 秒唤醒、无排队且应用交付及时完成时，可以提前结束业务等待；不同消息排队、应用交付和重试仍消耗窗口，不能由单次唤醒 10 秒推出任意积压全部在 60 秒完成。候选已明确超时计数和退出可丢失，不存在所审文档承诺任意积压不丢失的冲突。

### 子任务与交付依赖

父项 `requirement.md:55-62`、21 `requirement.md:28-34`、22 `requirement.md:5-16` 和 `:25-29` 共同覆盖代码、镜像绑定、编排和集成验收责任；22 的 metadata `depends_on` 精确指向 21。代码合并交付与镜像可用/源码关联分别核验，禁止旧镜像配新 hook。子项 22 可以预先审查语义契约，实际编排变更继续受真实前置交付门禁约束。

22 尚未填写的本地端口、path、具体 HTTP 返回表示可以使用 21 已交付代码的实际接口；它们在本项是受前置提供方约束的绑定值，不需要为了设计通过虚构一个实现常量。后续接口若改变当前 60 秒绝对截止、幂等、结果区分或本地可达/不可经业务 listener 暴露等共享语义，则相应变化需要重新审查。目标组件版本与发布分支的选择按原工作区实施规则完成，不是本轮设计质量阻塞项。

父项仍承担整体验收，不能仅由代码或编排单独通过推导完整功能通过。22 的独立通过也不解决 G1、G2，更不代表前置代码、镜像、组件、部署或真实消息验证已经完成。

## 身份、独立性和授权

- Reviewer canonical name：`/root/webhook_design_reviewer`。派发工具未暴露额外 UUID，不臆造 agent id。
- 显式派发配置（主代理提供）：`model=gpt-6.1-sol`，`reasoning_effort=high`，`agent_type=default`，`fork_turns=none`。这是指定配置记录，不声称存在额外底层运行时型号证明。
- 我未参与该设计原稿或修订的实质编写。输入为 clean-context 的原始要求、路径和事实入口；本轮自主阅读原文、形成结论。未新增 reviewer 子代理。
- 用户明确请求“让独立 reviewer 进行设计审查”。用户已批准内存接收/退出可丢失、单接入单 Sandbox、开关开启可唤醒手动 Pause、正常下线顺序、最多 60 秒和编排依赖代码交付；没有把这次审查请求推断成所有剩余业务选择已批准。
- 使用 [review-design/SKILL.md](/Users/sophon/Workspace/skills/airan-dev-kit/skills/review-design/SKILL.md) 的普通项目 report-only 模式及 discussion-and-authorization、implementable-gate 和关联审查标准。技能明确允许“**A conversational design may be reviewed without a document status.**”，并规定“**Unable to conclude: an essential contract, stable target, decision, evidence or independent reviewer is missing.**”。前者是技能的明确要求；G1/G2 是本 reviewer 独立判断的必要契约缺口，不是文档形式门禁或额外审批要求。
- 仅写入本报告和 `/tmp` 原始读取/渲染产物。未改项目记录、源代码、实际编排或正式状态，未 commit/push，未请求部署或镜像发布。

## 输入身份和实际检查

项目根：`/Users/sophon/Workspace/OKAWorkspace/projects/im-auto-wakeup`。输入 HEAD：`27e8ae89472e3844104ec75a18182091e3088c12`；开始检查时 `git status --short` 无输出。以下为 Git blob 身份；路径均相对项目根。metadata 的 design version 均为 0，父项 designing、子项 new；这些标签没有替代本轮判断。

| 路径 | blob |
| --- | --- |
| `workitems/2-feishu-wake-openclaw/requirement.md` | `07ba11364353050900b429f6914b31b40978416c` |
| `workitems/2-feishu-wake-openclaw/decision.md` | `cf05895119e64fec809b2994975b45c210ed8ede` |
| `workitems/2-feishu-wake-openclaw/context.md` | `5fa05c6f472a3052891cedf3567bf0045016c642` |
| `workitems/2-feishu-wake-openclaw/metadata.yaml` | `e41201d563a187764c7a73c30f21b1433a05b99a` |
| `workitems/21-webhook-gateway-code/requirement.md` | `5648433e46860c5847bf1d0abd494a79f4d53562` |
| `workitems/21-webhook-gateway-code/decision.md` | `eff8e8d28a581e7fbcd2956e9864563dd7ad6ee3` |
| `workitems/21-webhook-gateway-code/context.md` | `a4882ed8c3c38c73c7866d881c1daaed91287dfe` |
| `workitems/21-webhook-gateway-code/metadata.yaml` | `166ea7678fa49eb6b1e959a3dd7408721cce0b13` |
| `workitems/22-webhook-ack-orchestration/requirement.md` | `73617002321dedb535278eb015c4a480b8325001` |
| `workitems/22-webhook-ack-orchestration/decision.md` | `857a3972e68942b28ab17f226ef2487ecff69cd8` |
| `workitems/22-webhook-ack-orchestration/context.md` | `e3d620bebb4153ac56532232990b3fd8aa08f8e1` |
| `workitems/22-webhook-ack-orchestration/metadata.yaml` | `6b1839b4c33f5393648e8e74309a05e66300a26e` |
| `evidence/ack-gateway-webhook-shutdown.md` | `13c1972b657749b2ee228be535cd4f5088e1a332` |
| `evidence/feishu-event-transports.md` | `6fb61a1ba85b471806e2aa1bff24d32b928238c1` |
| `evidence/openclaw-feishu-im-mechanism.md` | `f9c2ed5ae8a5f9f8fd33f7d97f8333d9f02a16a7` |
| `evidence/im-wakeup-paths-and-capabilities.md` | `10fd397b3ac1f580478eff6258a726820a66741f` |

原始指令：读取 `~/.codex/AGENTS.md`、主工作区 `AGENTS.md`、项目根及三个工作项的 `AGENTS.md`、`.project/project-instructions.md`、`context.md`、`business-instructions.md`、`main-workspace.md`、`project.yaml`、`repositories.yaml`，以及 agents 原始根和 `pkg/sandbox-gateway/AGENTS.md`。ack-components 搜索未发现仓库内 `AGENTS.md`。读取了三个 item 的 requirement/decision/context/metadata 与 logs，四份相关 evidence。记忆检索仅用于定位旧项目索引，当前结论均绑定本轮原文与源码，不沿用旧状态。

源码与配置身份：

- agents 主检出 `develop` HEAD `c7f1bf56966940fbfe2a73cd48b9a52c2b17de66`，只读 status 干净；复用主代理本轮已成功 `git pull --ff-only` 的检查，不切分支。现有 ACK 镜像行为统一使用固定源码 `e55d70c7fc7d603e8a585918919788edd0374e31` 的 `git show`，未把它声明成未来开发基线。读取 filter/filter.go、filter/config.go、server/server.go、controller/gateway_controller.go、wake/wake.go、cmd/sandbox-gateway/main.go 与 dockerfiles/sandbox-gateway-inner.Dockerfile。没有借用工作项 1 的未提交实现。
- ack-components 主检出 `master` HEAD `02d1a5f3b1c7fe5478ea69e105eb9dddfada8934`，只读 status 干净；同样复用本轮主代理拉取结果。实际读取包为 `addons/ack-sandbox-manager/main/v0.6.14-release.1`。模板 blob `b743dccf5653e29e430ce13567e40bfecd984f99`，values blob `76f09cd7d95dca8f5118b5d9a4b6c0833b6e35e6`，default config blob `1460abb66852817517bfb20b56852864c162291f`，component blob `34dc332823167f24558f65136cd86e4b9fcde4e2`。其他 release 分支原核验记录仅作背景，本 reviewer 没有重新核验它们的完整模板。
- OpenClaw 原始资料读取固定 `0a0d601bf12dfea5e4c94c3e8cd6d823c405d9a0`；本地 `/tmp/review-openclaw-monitor.transport.ts` SHA-256 `1c25c2402595a04b4aa9a463febb187e9af25876169d29d0b8bcdcdbf64fb4d3`，`/tmp/review-openclaw-feishu-ingress.ts` SHA-256 `56dc15bd79655f69bd2e4d4f6a706927bf2c8c65ccef16e054b4238d0f925a14`。
- Envoy 官方 1.37.3 文档和对应 tag 的 `server.cc:985-994` 核对信号直接调用 shutdown。下载文件 `/tmp/review-envoy-server.cc` SHA-256 `f0ddaa40cbfb1a384b1c536b663f7e641d845cdde3cd533c1ed09950a358d506`。未引用其他版本的 drain 行为。

实际执行的非破坏性验证：

1. 读取固定源码及配置、检查项目/源码/编排 status 与 HEAD，并获取上述 blob 和下载文件 SHA-256。所有结论均为设计/静态路径判断，没有把它们写成故障复现。
2. 独立执行 `helm template review <实际 Chart> -f /tmp/review-ack-gateway-default.yaml --show-only templates/sandbox-gateway.yaml`，退出码 0。default 配置仅把 `RegistryURL` 展开为 Chart 当前仓库域名，`ClusterID` 使用 `review-check` 占位；没有改 Chart 或目标值。原始产物 `/tmp/review-ack-gateway-rendered.yaml` 显示 grace=90、drain=30、旧 curl 5 秒/sleep 30、匹配的 gateway tag 及 readiness/liveness。此验证确认现状，不宣称已渲染或实施新 120 秒方案。
3. 通过 web 独立核对 Kubernetes hook/Pod 终止、Envoy 固定版本 drain 官方资料；飞书[事件概述](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/event-subscription-guide/event-subscriptions)官方索引返回确认窗口及有限重试文本，页面直开无可读正文。OpenClaw/Envoy GitHub 页通过 web 直开 cache miss，随后使用 curl 读取官方仓库固定 commit/tag 的 raw 源码成功。第三方搜索结果未作为依据。

未执行：业务代码测试、新 drain 并发实验、真实飞书配置与消息、Pause/Resume、应用接收集成、Pod 删除/滚动/故障注入、线上覆盖值/imageID、镜像构建发布、组件更新或部署。这些尚未实施或授权的运行工作不独立构成本轮设计阻塞；G1/G2 需要先明确的语义输入不能用未来运行测试代替。

## Handoff

主代理登记本报告的真实身份、输入和三个独立结论；保持 22 的通过与前置交付分开。设计所有者集中收敛 G1、G2 的必要契约，复用既有内存/暂停/60 秒/拆分决定；修订后优先由本 reviewer 对变化及受影响链路进行独立复核，保留本轮正常下线、预算和子任务边界的有效覆盖。该建议不授予代码实施、镜像发布、编排实施或部署权限。
