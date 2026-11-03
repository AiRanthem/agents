# 飞书 IM Webhook 唤醒第二轮独立设计审查

日期：2026-11-04。审查输入：项目提交 `5061001783fd3d9fd431c3e820f6862f7a5e4eb6`。这是用户明确要求“再次独立复审”后的普通项目 report-only 增量审查；未作设计修订、实现、部署或正式状态写入。

## 结论

| 范围 | 本轮独立结论 | 根据 |
| --- | --- | --- |
| `2-feishu-wake-openclaw` | **Unable to conclude** | 标准飞书 IM 协议、HTTP 200 接收判据和 E2B URL 寻址已得到实质收敛；仍有已接收事件失败处置及飞书入口配置/授权、启停变化的必要契约缺口。 |
| `21-webhook-gateway-code` | **Unable to conclude** | 独立评估了整个接收、恢复、交付和排空范围，不能仅凭正常下线子契约通过代表全项通过。受下文 G1-R、G2-R 限制。 |
| `22-webhook-ack-orchestration` | **Independent review passed** | 当前编排语义、预算、顺序、失败处理及交付前置未改变；本轮检查变化对其应用确认/排空交互的影响后，原独立覆盖仍有效。此 Pass 不代表代码或镜像已交付，不解除实际编排变更的前置门禁。 |

没有发现已确定的候选行为必然违反要求的新增阻塞性缺陷，因此不使用 `Design changes required`。本轮结论来自必要未决的对外行为，既不因缺少 `spec.md` 判失败，也不把真实部署、E2E 或未来实现的缺席当作设计缺陷。G1/G2 并非原样保留：前次协议选择和额外目标映射方面的疑问已经缩小，详见下文。

## 前次输入、变化及覆盖复用

前次报告为 `workitems/2-feishu-wake-openclaw/records/design-review-20261104.md`，目标提交 `27e8ae89472e3844104ec75a18182091e3088c12`，SHA-256 `fcf599dc88564b5bb045a4e8b94d3f9943718912fd083a442c32051e56740600`。本轮重读报告及同名 YAML，并核验文件与我原 `/tmp` 报告逐字相同。前次并未要求必须采用 durable；它把接收判据列为未决。当前用户选择标准飞书协议后，不能再以没有 OpenClaw 私有 durable 标记为缺陷。

本轮同时比较 `27e8ae8..5061001` 的累计变化和 `92cb333345c58a3952166ecb7caffb35cf502bb6..5061001` 的本次设计变化，并读取完整当前 requirement/decision/context/metadata。变化包括：Webhook 范围从通用 IM 收敛为独立飞书 IM；应用返回标准 HTTP 200 即完成协议接收；转交保留原始 body/签名头；复用 E2B 数据面 Host 和既有 route 寻址；新增飞书入口证据及对尚未确定配置/重试行为的说明。前次评审登记也在累计 diff 内，但不是新的业务设计或通过证据。

以下覆盖继续有效：内存接收、允许进程退出丢失、先登记后 ACK、与停收互斥、任务不依赖已销毁 stream；本地 drain、首次停收起 60 秒绝对截止、重复调用不延期、调用方断连不撤销 draining；readiness 与内部 route 可用性分离；业务排空先于 Envoy drain/TERM；65+5+30+20=120 秒编排预算；代码交付后才能变更编排、启用 hook 前匹配镜像。上述约束及原四份 evidence 未发生语义改变。实际 ACK 包和决定这些结论的源文件 blob 也未改变。

子项 22 的 requirement/decision 与前次输入逐字相同；context/metadata/logs 只是登记真实评审结果。其共享的应用成功条件由抽象“有效确认”具体化为标准 HTTP 200，仍在应用接收时终结，未扩大到模型执行或飞书回复。该变化不改变本地 drain 调用、预算或其失败处理，因此可以复用此前完整审查和 Helm 渲染，不重复稳定检查。

## 已解决或缩小的缺口

### G1 的协议选择、有效确认和载荷边界已解决

父项 `requirement.md:31`、子项 21 `requirement.md:12` 已明确两段 ACK：Gateway 登记内存后向飞书返回 200；恢复后向正确应用事件路径转交普通 IM 事件，应用 HTTP 200 表示协议接收完成。challenge 单独处理，非普通消息交付；业务执行、持久化和最终回复均不由此证明。请求保留原始 body 及相关签名头。

我重新查询了飞书[事件概述](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/event-subscription-guide/event-subscriptions)官方索引文本：平台通过 POST 投递事件，三秒内 HTTP 200 作为接收确认，失败存在有限重投。这支持现行标准接收判据。飞书[回调概述](https://open.feishu.cn/document/event-subscription-guide/callback-subscription/callback-overview)另行规定同步交互结果和超时处理；当前 IM 事件 ACK 不能扩大到卡片/预览等同步 callback。现行 requirement 第 19 行已区分它们，没有把当前支持外的同步场景错误地统一为异步确认。

缓存的 OpenClaw 固定源码 `0a0d601bf12dfea5e4c94c3e8cd6d823c405d9a0` 重新核验哈希后阅读：`monitor.transport.ts:507-528` 区分 challenge 和普通事件，但普通事件仍用 HTTP 200 返回；私有 durable 头是实现附加信息。`:105-138` 对原始 body 与签名头验签。因此当前选择有可行接收路径，不再要求另选私有 API、重签或强持久化。实际应用版本符合该标准接口是集成兼容前提，可在实现/接入时核验，无须先部署才能认可该协议选择。

### G2 的目标寻址已解决，无需新的通用映射系统

完整 URL `https://<port>-<sandbox-id>.<e2b-domain>/<应用事件路径>` 能提供现有路由所需的 ID/端口。独立读 agents `c7f1bf56966940fbfe2a73cd48b9a52c2b17de66`：

- `pkg/servers/e2b/adapters/native_e2b.go:45`、`:68-120` 从 Host 前缀提取端口和 public ID；`:134-136` 生成同一格式。
- `adapters/unified_e2b.go:120-132` 从 HTTP authority/host 取得解析输入；普通应用路径选择 native adapter（`:95-100`）。
- `pkg/sandbox-gateway/filter/filter.go:133-149` 依据 ID 查 route，再认证。
- `pkg/sandboxroute/route.go:32-45`、`:94-123` 已保存 namespace/name、UID、owner、地址和授权相关信息。

这些文件与已核验 ACK 镜像源码 `e55d70c7fc7d603e8a585918919788edd0374e31` 的相关行为相同。`pkg/servers/e2b/sandbox.go` 只多了与本题无关的 claim-method metadata 输出，Domain/token 分离行为未变。

运行现有适配器窄测试通过，覆盖 Host fallback、header 优先级、解析和错误输入；测试没有把 Host 当作身份认证证据。域名公网 DNS、证书和入口实际通向 Gateway 仍是接入环境前提，本轮不把它们假定为线上已验证。裸基础域名没有端口/ID，也不能代替上述完整请求地址。

## 剩余必要未决契约

下列是必要输入缺口，不是已复现事故或已经选定错误实现。影响级别用于说明不能独立通过的原因，不声称当前已造成越权或事件丢失。

### G2-R：飞书认证的配置/授权边界及启停变化仍未确定

- **影响级别：High；归属：父项 2、子项 21。**
- **当前原文定位：** 父项 `requirement.md:23`、`:33`、`:43`、`:47-49`，`context.md:23`、`:64`；21 `requirement.md:11`、`:27`；`evidence/feishu-e2b-webhook-entry.md:15-21`。当前文字明确把验证配置载体、启停/更新和排队重新校验留待确定，不能把这部分误认为 E2B Host 已解决。
- **触发与后果：** 飞书向某个 E2B Host/应用路径发送合法事件，但该目标原本要求 E2B token/JWT；专用入口必须知道何时按飞书认证替代该次数据面认证、用哪份平台配置验证，以及该配置由谁授权绑定到哪个目标/端口/路径。若照搬普通流量认证，标准请求会被拒绝；若只放开一个宽泛入口而无目标绑定，又不能从来源合法推出有权访问任意 Host。配置被撤销或自动唤醒关闭时，已 ACK 任务还要有确定的执行/取消/拒绝边界，否则无法检验“需要持续保持暂停时关闭开关”的用户用法（父项第 11 行）。本报告没有认定候选已经选择宽泛放开或照搬旧认证；两种后果用于说明为何需要具体契约。
- **原始代码证据：** `filter.go:211-287` 中 JWT/传统 token 与飞书签名不是同一凭据；缺少相应 E2B token 的请求会在恢复前返回 401/403，验证器不可用则 503。`native_e2b.go:45,109-116` 仅解析请求指定的 Host 前缀，不认证其来源。飞书官方[验签公式](https://open.feishu.cn/document/event-subscription-guide/callback-subscription/receive-and-handle-callbacks)使用 timestamp、nonce、Encrypt Key 与原始 body，不包含请求目标 Host/path；故路由值本身不能授予权限。`sandboxid.go:93-104` 的 public ID 取 label 或 legacy namespace--name，并非 UID；`filter.go:324-344` 已有 UID fence，当前新证据第 19 行也明确禁止异步任务投递到同名重建对象。
- **本轮已消除的部分：** 无需新建 endpoint-to-Sandbox 映射系统；UID 不得错投的结果约束已明确，可由实现者复用现有 route/UID 机制，不要求 reviewer 再设计数据结构。
- **所需结果：** 确定用户怎样显式启用这一个飞书入口、如何向 Sandbox 外的 Gateway 提供/授权使用对应验证配置，以及配置/开关撤销或更新对新请求和已接收任务的生效语义。应限定对普通数据面的认证影响。Secret 名称、私有缓存、锁、共享 helper 和读取优化属于实现选择；这里不要求指定那些内部细节，也不重复征询单接入单目标或手动 Pause 可唤醒的既有决定。
- **不确定性：** 当前明确要求“未授权不得恢复”，且要求只在显式入口内使用飞书验证；存在可行安全实现。缺少的是用户/运维会使用并依赖的配置及撤销契约，不能把它描述成已有源代码缺陷。没有现场数据证明某个集群开启或关闭了旧门禁，本轮也不依赖该事实。

### G1-R：成功判据已明确，但 ACK 后失败/响应丢失的处置边界仍未完成

- **影响级别：High；归属：父项 2、子项 21。** 这是前次 G1 的剩余范围，不再保留“应用接收确认协议未选择”的旧表述。
- **当前原文定位：** 父项 `requirement.md:25`、`:31`、`:35`、`:44-46`，`context.md:65`；21 `requirement.md:15`、`:27`；新 evidence 第 29、33 行。
- **触发与后果：** Gateway 对飞书确认后，应用持续拒绝/连接失败，或应用已收到但 200 响应丢失。此时上游已经得到成功确认，不能指望飞书知道内部交付失败；处理器必须知道是否重投、何时最终失败、重复投递能依赖何种事件身份/应用幂等前提。当前也只在下线时规定了 60 秒上限，未给正常运行期的任务生存边界。因而无法判断某事件进入失败终态、继续占内存或再次交付是否符合承诺，亦无法完整评估“全部任务已结束”的业务 drain 结果。接受进程退出丢失不会自动确定进程存活时的这些可观察处置。
- **原始证据：** 飞书[事件概述](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/event-subscription-guide/event-subscriptions)区分接收确认与失败重投；Gateway 的提前确认会使后续应用交付成为接收层自己的责任。OpenClaw 固定源码 `monitor.transport.ts:75,105-138` 限制签名时间窗为一小时；保留旧 body/签名头可以短时转交，但不能假定它们永远有效。该一小时是所查 OpenClaw 的实现约束，不是所有标准飞书接收器的统一保证。
- **所需结果：** 设计明确 ACK 后的有限失败责任：响应丢失/失败是否重投、重复事件可承诺到什么程度、什么条件结束事件，以及任务存活与目标验签时间窗的兼容前提。无需承诺恰好一次、业务回复、跨进程恢复或强可靠；也无需让用户逐一决定退避算法、worker 数、队列的精确默认容量或每次 HTTP timeout。实现者可以在既定责任和上限内选择这些参数。
- **不确定性：** 当前未选择无限重试、超时错误算成功或重签，因此没有证明具体协议冲突。确定一个有限边界后可能直接复用现行原始请求转交，无需改变已批准的内存方案。当前缺口是 What 层的失败终态和责任，不能仅用未来测试或默认实现参数替代。

## 本轮检查与未验证范围

1. 重读原始 `~/.codex/AGENTS.md`、主工作区及项目根 AGENTS、三个 item AGENTS、当前项目 instructions/context/business-instructions；读取 review-design 共享技能、project-mode、implementable-gate 和 discussion-and-authorization。新增代码阅读还读取 agents 根、Gateway、E2B API、sandboxid 和 sandboxroute 的原始 AGENTS。未作原文或候选机械修订。
2. agents 主检出先检查为干净 develop，ack-components 为干净 master；分别执行 `git pull --ff-only`，均退出 0、Already up to date。没有切分支。当前 HEAD 仍为 agents `c7f1bf56966940fbfe2a73cd48b9a52c2b17de66` 与 ack-components `02d1a5f3b1c7fe5478ea69e105eb9dddfada8934`。拉取只维护按原始指令要求刷新的本地引用，不作源码发布。
3. 直接阅读上述决定入口结论的五组原始源码，比较 `e55d70c7f..c7f1bf5` 相关差异；独立检查普通流量认证在恢复前发生、token 与 Domain 分离、ID 与 UID 区别。没有以新 evidence 的作者结论替代源码检查。
4. 执行 `GOCACHE=/tmp/im-wakeup-review-r2-gocache go test ./pkg/servers/e2b/adapters -run '^(TestMap|TestParseRequest|TestNativeE2BAdapterHeaderBasedMap)$' -count=1`，退出 0，输出 `ok github.com/openkruise/agents/pkg/servers/e2b/adapters 0.948s`。已读现有表格用例及断言，确认覆盖不带额外路由头的 Host fallback；该测试不验证飞书验签、网络可达或异步交付。
5. ACK 四个原始模板/配置 blob 与前次完全相同，保留原先成功的 Helm 渲染和正常下线审查；读取仍在 `/tmp/review-ack-gateway-rendered.yaml` 的原产物，仍显示 90 秒旧 grace、curl 5 秒和 sleep 30。没有重复运行 Helm 或声称新 120 秒方案已渲染/实施。
6. 重新通过 web 查询官方飞书事件和 callback 文档，来源限官方平台文档。事件正文直开仍无可读行，使用官方搜索索引返回的正文；未引用自定义机器人发送 Webhook 的签名或时限，也未引用社区帖当协议依据。OpenClaw 复用前次从官方固定 commit 下载并已验 SHA-256 的源码缓存，而非重新解释浮动 main。

未执行真实飞书应用注册、公开 DNS/HTTPS 检查、Gateway 新功能运行、Pause/Resume、应用接收/响应丢失实验、drain 并发测试、Pod 终止或 rollout、线上覆盖值/imageID 读取、镜像构建发布及组件部署。未执行的运行检查不构成单独的设计阻塞。项目无新增业务实现，本轮现有适配器测试通过也不表示 Webhook 唤醒已经实现。

## 身份、独立性和输入绑定

Reviewer canonical name 为 `/root/webhook_design_reviewer`，工具未暴露额外 UUID。沿用本 reviewer 身份，最初显式派发配置为 `gpt-6.1-sol / high`、`agent_type=default`、`fork_turns=none`；本轮复用同一 reviewer 会话。累计未参与原设计或任何实质修订，只写过前次和本次审查报告，独立性保持。未再派 agent。主代理提供的是用户原话和事实导航，当前结论由我独立形成。

用户明确要求再次复审，足以授权本轮审查；用户选择标准协议和 E2B 入口使上述相关契约得以收敛，不等于其批准了尚未确定的配置或失败规则，也不授权实施/发布。[review-design/SKILL.md](/Users/sophon/Workspace/skills/airan-dev-kit/skills/review-design/SKILL.md) 规定“**Unable to conclude: an essential contract, stable target, decision, evidence or independent reviewer is missing.**”这是技能的结论规则；G1-R/G2-R 是否属于必要缺口是本 reviewer 根据具体场景作出的判断，不是技能额外要求新文件、重新审批或现场部署。

项目开始与报告完成前 `git status --short` 均无输出，HEAD 固定为 `5061001783fd3d9fd431c3e820f6862f7a5e4eb6`。路径相对项目根；下列 Git blob 标识绑定当前受审内容，状态标签不代替质量结论。

| 路径 | Git blob |
| --- | --- |
| `workitems/2-feishu-wake-openclaw/requirement.md` | `bb4eb804bc7478a136c0b32d767f5d57782523c1` |
| `workitems/2-feishu-wake-openclaw/decision.md` | `7feae3e782486828a988851324c643735a79031a` |
| `workitems/2-feishu-wake-openclaw/context.md` | `b72cf94e8a24b11f0afdef06cc1aba2700587548` |
| `workitems/2-feishu-wake-openclaw/metadata.yaml` | `c35a1f4699cc754aa0930992f7c7258377750a8a` |
| `workitems/21-webhook-gateway-code/requirement.md` | `8d166a82f043e5f3858fac44d1cdd0cd0f137a85` |
| `workitems/21-webhook-gateway-code/decision.md` | `3a0877a878ebad9a38ab74acc08b3ed0ea52c8a6` |
| `workitems/21-webhook-gateway-code/context.md` | `7bb4b3e746f1e08dfeed6a7ed55162f11a5a624b` |
| `workitems/21-webhook-gateway-code/metadata.yaml` | `f01fdf85285574b5a003eae0bc87db6c06da5ce5` |
| `workitems/22-webhook-ack-orchestration/requirement.md` | `73617002321dedb535278eb015c4a480b8325001` |
| `workitems/22-webhook-ack-orchestration/decision.md` | `857a3972e68942b28ab17f226ef2487ecff69cd8` |
| `workitems/22-webhook-ack-orchestration/context.md` | `0a5b01abce6b98a943629b4c41a991c415c0ade3` |
| `workitems/22-webhook-ack-orchestration/metadata.yaml` | `47f5a51f06592eb13647b6867436cd79ad967ab2` |
| `evidence/feishu-e2b-webhook-entry.md` | `6d40818b9bb279c917ffe96e25040b0db4c6e145` |

未变 evidence blob：ack shutdown `13c1972b657749b2ee228be535cd4f5088e1a332`；Feishu transports `6fb61a1ba85b471806e2aa1bff24d32b928238c1`；OpenClaw mechanism `f9c2ed5ae8a5f9f8fd33f7d97f8333d9f02a16a7`；wakeup paths `10fd397b3ac1f580478eff6258a726820a66741f`。本轮对它们适用性的判断基于前次完整覆盖、当前无差异及上述增量原始检查。

新增阅读源码 blob（agents c7f1bf5）：`native_e2b.go` 为 `6c2b1585395c011a63aa13bed804d7c9a7584795`；`filter.go` 为 `8ec3e6df7539aef2f117807ffe2d2c07774988ab`；`sandboxid.go` 为 `e83d34d045ed6e94087c0c15abe46ace34284d9f`；`sandboxroute/route.go` 为 `d68d49fcdd2cd9547b62a58312cf2f3e8d4bd4b8`；E2B `sandbox.go` 为 `82d9d60286233018686b0e3dbfb091f5a4e03fc5`。ACK 模板、values、default、component blob 分别仍为 `b743dccf5653e29e430ce13567e40bfecd984f99`、`76f09cd7d95dca8f5118b5d9a4b6c0833b6e35e6`、`1460abb66852817517bfb20b56852864c162291f`、`34dc332823167f24558f65136cd86e4b9fcde4e2`。

复用 OpenClaw 缓存：`/tmp/review-openclaw-monitor.transport.ts` SHA-256 `1c25c2402595a04b4aa9a463febb187e9af25876169d29d0b8bcdcdbf64fb4d3`；`/tmp/review-openclaw-feishu-ingress.ts` SHA-256 `56dc15bd79655f69bd2e4d4f6a706927bf2c8c65ccef16e054b4238d0f925a14`。固定 commit 仍为 `0a0d601bf12dfea5e4c94c3e8cd6d823c405d9a0`，不代表线上目标版本。

## Handoff

主代理保存本轮真实结论和输入身份，保留前次结果的原始目标。G1 标准协议选择与 G2 寻址部分已闭合；剩余 G1-R/G2-R 应由设计所有者集中完成对外行为契约，优先复用当前 reviewer 对变化及受影响交互复核。22 的编排契约独立通过继续成立，但代码/匹配镜像前置、环境验证、人工验收和实际交付分别以真实证据记录。本轮未改项目文件、代码或编排，未 commit/push，未写正式 implementable。
