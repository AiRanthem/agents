# IM 平台四类接入的沙箱休眠行为调查

调查日期：2026-11-04。本文研究消息接收与恢复语义，不建立设计批准、代码交付或真实环境验证。结论按公开平台文档、固定版本源码和场景推论分层；公开资料未承诺的补投行为保持未知。

## 1. 范围与统一前提

覆盖此前讨论的15个平台：飞书、微信腾讯iLink、QQ、钉钉、企业微信、Slack、Discord、WhatsApp、Mattermost、Telegram、Matrix、Microsoft Teams、LINE、Google Chat、IRC。统计沙箱与外部IM服务之间的消息接收方式：WebSocket、HTTP Webhook、HTTP轮询（主要长轮询）、原生TCP/TLS。Signal、iMessage及沙箱内部的SSE、stdio/RPC不在范围内。

每个平台只调查其实际支持的接入形式，不要求所有平台支持四种。共形成22个基线场景：8个WebSocket、10个Webhook、3个HTTP轮询、1个TCP/TLS；其中钉钉HTTP是平台能力，所查connector未实现，因此实际插件接入为21个场景。企业微信Bot与Agent虽然同属一个平台，也分别记录。Slack relay作为外部接收方仍在线的条件变体，不另计协议或基线场景。

本次穷举限定为这15个平台及明确列出的OpenClaw实现，不代表所有社区fork、个人账号协议、历史插件和未来平台API。平台提供某种API或协议，不代表所查OpenClaw插件实现了该入口；平台能力、插件行为和当前部署分别记录。

统一假设：

- 机器人/应用/账号原本正常，用户原本具有发送权限，相关发布、群成员与事件订阅配置原本有效。
- 沙箱休眠意味着接收插件及必要辅助进程停止执行；沙箱未被删除，内存可以保留，但不能执行心跳、回调、重连或轮询。
- 所有旧连接均已中断，不依赖残留socket、缓冲区或短暂停顿偶然成功；没有其他在线消息接收客户端。
- 除明确说明的Webhook外部可达入口分支外，没有独立唤醒信号。涉及回复时，指OpenClaw生成的业务回复，不把平台自带自动应答或其他设备的响应算进去。

| 时点 | 要区分的事实 |
| --- | --- |
| T0：正常运行 | 已建连接/轮询或已配置Webhook，平台和插件能正常交换消息 |
| T1：休眠且旧连接全断 | 平台怎样识别接收端失联；已经投递但未确认的事件怎样处理 |
| T2：休眠期间用户新发消息 | 用户能否发到IM；平台是否接纳；是否生成并保留可交付的事件；是否产生新的入站请求 |
| T3：由外部机制恢复 | 客户端怎样重连、恢复会话或续拉游标；平台能补什么、插件实际会处理什么 |

T1的失败重试规则不能直接当作T2完全离线新事件的保留承诺。T3也不是自动发生的唤醒：恢复沙箱、接收进程重新运行、收到事件、Agent完成和回复送达是不同结果。

## 2. 四类接入的共同边界

| 接入形式 | 新连接/请求的发起方 | T2时的消息接收与唤醒边界 |
| --- | --- | --- |
| WebSocket | 沙箱中的客户端/SDK主动连接IM服务 | 客户端停止且旧连接全断后，没有可用通道交付给该客户端。服务端重连提示不等于服务端反向建连；暂停的客户端不能自行执行重连来唤醒自身 |
| HTTP Webhook | IM平台向配置的接收URL发起新HTTP请求 | 可以不依赖任何旧连接发出请求。能否触发恢复取决于入口可达性、授权和唤醒能力；选择Webhook本身不保证自动唤醒或业务成功 |
| HTTP轮询 | 沙箱中的客户端主动请求IM的拉取/同步API | 全断后没有待响应的旧请求，暂停客户端也不能发出新轮询。平台保存的消息需要客户端后来恢复并满足游标、保留及过滤条件才能再拉取 |
| 原生TCP/TLS | 本轮IRC客户端主动连接服务器 | 连接失效后不能靠暂停客户端重连；IRC还存在nick与频道成员属于在线会话的特殊语义，不能套用持久机器人账号的单聊行为 |

前述网络方向及其在统一前提下的结果属于机制推论；WebSocket客户端握手与HTTP长轮询的请求生命周期分别可见 [RFC6455](https://www.rfc-editor.org/rfc/rfc6455.html#section-4.1)、[RFC6202](https://www.rfc-editor.org/rfc/rfc6202.html#section-2.1)。平台是否保存离线事件，需要各平台自己的公开契约，不能从底层传输形式推出。

Webhook需要进一步区分：

| 分支 | 平台和接收端的边界 |
| --- | --- |
| H0：入口无法有效响应 | 平台遇到连接失败、超时或非成功结果，是否重试、重试多久和是否停推由各平台规则决定 |
| H1：仍存在已授权且具备唤醒能力的可达入口 | 新HTTP请求可以到达该入口；恢复、应用就绪与交付需要入口实际实现，冷启动耗时与平台确认窗口可能冲突 |
| H2：已成功ACK，后续应用处理失败 | 平台只看到了自己的接收确认；后续是否保存、重试或丢失由接收端契约决定，不能假定平台知道Agent失败并补发 |

H0是平台观察到的响应失败，不证明沙箱没有被唤醒：请求可能已经触发外部恢复流程，随后才超时或返回错误。唤醒是否发生与事件是否被平台确认需要分别判断；及时ACK或持久化写入不是“曾触发唤醒”的必要条件。本文不新增持久化保存要求。

## 3. 证据层级与版本

- **D：公开文档契约。** 平台官方规范、产品文档或明确的官方说明。
- **C：所查实现。** 特定SDK、OpenClaw或外部插件源码；实现文档与代码证据会注明来源，不能当成实际安装版本。
- **I：机制推论。** 根据D/C与本文统一前提推演的行为，未在真实沙箱中验证。
- **U：尚无公开保证或环境未知。** 不用“必补”“必丢”“永久保存”替代未知项。

共用OpenClaw研究快照为 [`f7257f2c66884611f4f4043367eada029b704918`](https://github.com/openclaw/openclaw/tree/f7257f2c66884611f4f4043367eada029b704918)，其中package.json标注版本`2026.10.10`。Slack和WhatsApp使用release `v2026.10.10`的实际提交`7dc3350cb9f08fcf9a0af5c4845a20d5b2f1a8be`；相同版本字符串不代表相同提交。外部插件分别为微信2.4.10、QQ2.0.4、钉钉0.8.27、企业微信2026.10.19，固定提交和依赖身份见各节及[机器可读矩阵](im-platform-sandbox-sleep.yaml)。这些身份不证明用户已安装或部署相同代码。

OpenClaw的本地持久接收队列，只保护已经到达并被写入的事件。平台聊天历史、平台未交付事件、WS会话回放和应用本地队列属于不同边界。尤其本地completed tombstone的去重期限不是平台离线消息保留期。[OpenClaw durable ingress说明](https://github.com/openclaw/openclaw/blob/f7257f2c66884611f4f4043367eada029b704918/docs/plugins/sdk-channel-plugins/durable-ingress.md#transport-classes-and-retention)

## 4. 平台行为矩阵

下表专门描述T2新消息与T3恢复。所有WS、轮询和IRC行均以“唯一接收端停止、旧连接全断、没有外部唤醒方”为前提，不能靠用户新消息使暂停客户端执行。Webhook行均适用H0/H1/H2；其新HTTP请求可以触达外部唤醒入口，但不保证该入口存在或动作成功。

除IRC会话外，暂停接收进程通常不删除平台上的bot/app/account、已安装应用或会话。身份仍存在、连接离线、客户端显示的在线标志是三件事；未找到明确平台契约的UI状态一律不推定。一般用户仍能按原权限发消息，但微信iLink和QQ的公开资料不足以承诺接收端完全离线时平台如何接纳与排队。所有行都不表示暂停中的OpenClaw能回复。

| 平台 / 模式 | T2用户能否发送 | 平台怎样交付或保留 | T3恢复后能否处理 |
| --- | --- | --- | --- |
| 飞书 / WebSocket | 原有权限正常时，单聊和群聊消息仍可进入飞书 | 无可用连接交付给暂停客户端；对完全无在线客户端时新产生事件的保留与补投，未找到公开保证 | SDK/插件主动重连；仅重连成功不能证明取回离线新事件；已入站本地队列另计 |
| 飞书 / Webhook | 仍可向飞书会话发送 | 平台发新HTTP请求；失败推送有限重试，成功ACK后不因Agent失败继续重投 | 剩余重试可能送达恢复后的入口；取决于事件未过期、入口和授权等条件 |
| 微信iLink / HTTP长轮询 | 所查插件仅私聊；可寻址，完全离线时服务端接纳规则未公开 | 无待决轮询；游标存在不等于离线保留保证 | 读取本地`get_updates_buf`续拉；保留期、游标失效和完整回放保证未知 |
| QQ / WebSocket | 文档支持C2C、群@；完全离线时平台接纳/UI规则未公开 | 官方说明“短时间内”恢复可补遗漏事件，但没有数值窗口 | SDK保存sessionId/lastSeq并尝试RESUME，失效时IDENTIFY；不保证任意休眠时长的完整补投 |
| QQ / Webhook | 同上 | SDK有效回调启动异步处理并立即200/op12；平台精确重试契约未找到 | 无WS Resume；只可能接到平台仍重投的回调，且宿主须支持该route |
| 钉钉 / Stream WebSocket | 原有机器人单聊/群@场景仍是目标；离线接纳/UI细节未知 | 普通机器人消息是fire-and-forget；不能借用EVENT订阅的ACK重试规则 | connector主动重连；没有恢复游标，不保证补收离线新消息 |
| 钉钉 / HTTP Webhook | 平台应用机器人提供该模式 | **所查connector不支持**；普通机器人HTTP精确重试规则未证实 | 不属于该connector可执行的恢复链路；需另有实现才能讨论交付 |
| 企业微信Bot / WebSocket | 已有单聊和群@入口；发送权限/可见性原本有效 | 连接断开后无法交付；未找到离线新事件保留/回放契约 | SDK重新连接并subscribe；没有公开恢复cursor，不能承诺回放 |
| 企业微信Bot / HTTP JSON | 已有Bot单聊/群场景可发送 | 加密JSON回调；正常插件先200返回stream占位，平台后续刷新；精确入站重试窗口未知 | 剩余回调/刷新取决于平台状态；6分钟是流式等待上限，不是事件保留期 |
| 企业微信Agent / HTTP XML | 可向已可见的自建应用发消息；群语义不照搬Bot | 5秒内响应；网络连接失败或请求超时时最多重试3次；插件先200再异步处理 | 剩余回调可能送达；成功ACK后Agent失败不自动变为平台重试 |
| Slack / Socket Mode | 已有DM/频道可按权限发送，事件范围受订阅限制 | envelope须ACK；未找到零在线客户端新事件保留或完整回放保证 | 重新获取WS URL并连接；无历史自动补拉；HTTP延迟重试规则不能直接套用 |
| Slack / HTTP Events | 同上 | 3秒成功响应；普通最多3次重试；可选Delayed Events延至24小时，best-effort | 剩余重试可能送达；长期失败还可能停用订阅，需要恢复配置 |
| Discord / Gateway WebSocket | 原有DM/频道权限正常时可发；在线显示可能离线 | 可恢复session有条件回放，失效后无此保证；聊天历史另计 | 同进程且session有效可RESUME；重建进程缺少内存session时通常重新IDENTIFY |
| WhatsApp Web / Baileys WebSocket | 原有账号私聊/群聊可发送；送达勾不证明该设备/Agent收到 | 平台未交付消息暂存政策不等于关联设备回放SLA；Baileys receipt也不是本地入队确认 | 重连后可能收到离线batch；OpenClaw按upsert类型和重连状态过滤，历史同步另计 |
| Mattermost / WebSocket | 原有DM/频道权限正常时可发，消息历史仍可保存 | 所查服务端源码有界、条件式WS续传；该插件未使用恢复参数 | 插件重新认证为新连接；无自动补齐错过的posted事件；线程上下文回填另计 |
| Telegram / HTTP长轮询 | 原有单聊/群权限与Bot可见范围正常时可发送 | Pending Updates保留最长不超过24小时；客户端未运行时没有拉取请求 | 从保留的offset续拉未确认更新；所查插件启动轮询明确不丢弃pending，仍受保留期、身份和游标状态限制 |
| Telegram / Webhook | 同上 | 平台POST并对失败结果重试；通用Updates保留上限为24小时；固定重试次数和总窗口未公开 | 剩余pending有机会继续送达；成功ACK后的本地任务恢复与平台补发不同 |
| Matrix / HTTP同步 | 在权限正常的房间中可发消息，homeserver接纳事件 | 通过`since`/`next_batch`同步；大间隔的timeline可能limited，并非必然返回全部历史 | 有效cursor下恢复主动同步；所查自动接收路径不自动补齐所有gap；无cursor首登会排除启动前历史 |
| IRC / TCP或TLS | 单聊取决于nick是否仍有在线会话；频道按发送者权限发送给现存成员 | 服务器确认目标nick不存在后，私聊可返回`401 ERR_NOSUCHNICK`；普通IRC不承诺离线消息邮箱 | 插件新建连接、注册并JOIN；当前接入不请求CHATHISTORY，不自动处理断线期间错过的消息 |

各模式来源、数值适用范围和未知项见下节及同名YAML。恢复后的去重、访问策略、@触发、账号token和回复权限仍然生效，收到事件不等于Agent一定处理或成功回复。

## 5. 平台特有规则与未知项

公开资料没有保证的项目保留为明确未知，不能以有限重试或聊天历史存在推断完整补投。

### 飞书

飞书普通消息事件的处理确认窗口为3秒；HTTP文档另列TCP建连超时2秒，成功确认是HTTP 200。已尝试但未成功确认的事件，文档列出15秒、5分钟、1小时、6小时的失败重试间隔，最多重试4次。长连接文档也要求handler在3秒内完成且不抛异常。这些是失败推送规则，不是“没有任何在线WS客户端时新事件一定被保存并补推”的保证；本轮未找到后者的公开契约。[事件订阅概览](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/event-subscription-guide/event-subscriptions)、[长连接接入](https://open.feishu.cn/document/ukTMukTMukTM/uYDNxYjL2QTM24iN0EjN/event-subscription-configure-)

所查OpenClaw的WS监督层可以在SDK终止后重建客户端；这些动作必须等进程恢复执行，服务端不替它建连。Webhook入口对特定durable事件入队后返回200，入队异常返回500；200与Agent执行完成分离。正常恢复的事件仍受事件类型、稳定ID、权限和去重限制。[WS与Webhook实现](https://github.com/openclaw/openclaw/blob/f7257f2c66884611f4f4043367eada029b704918/extensions/feishu/src/monitor.transport.ts)、[入站接收实现](https://github.com/openclaw/openclaw/blob/f7257f2c66884611f4f4043367eada029b704918/extensions/feishu/src/feishu-ingress.ts)

### 微信腾讯iLink

本轮指腾讯维护的`@tencent-weixin/openclaw-weixin` 2.4.10，固定提交`874637a0dbc24050f72d1385add4fc6170a2d726`，不是泛指所有“微信桥接”。所查OpenClaw文档只承诺私聊接入，群聊不纳入该插件能力。接收端POST `ilink/bot/getupdates`，服务器等待消息或轮询超时；进程暂停且旧请求全断后，没有新请求供服务端响应。[插件协议参考](https://github.com/Tencent/openclaw-weixin/blob/874637a0dbc24050f72d1385add4fc6170a2d726/docs/protocol.md)、[OpenClaw渠道说明](https://docs.openclaw.ai/channels/wechat)

恢复后monitor从本地`.sync.json`读取`get_updates_buf`续拉；收到非空新cursor时，先保存cursor，再处理该批`msgs`，这里没有逐消息ACK。这是崩溃/重启恰好发生在交接期间的风险线索，不能直接推成保留内存的普通Pause必丢消息。协议参考明确基于客户端代码，不是完整服务端契约；离线事件保留期、cursor有效期、空cursor起点、完整回放和离线发送接纳保证均未找到公开说明。`-14`失效token会使插件暂停API调用一小时再试，不会自动扫码重新登录。[monitor接收与cursor顺序](https://github.com/Tencent/openclaw-weixin/blob/874637a0dbc24050f72d1385add4fc6170a2d726/src/monitor/monitor.ts)、[token保护](https://github.com/Tencent/openclaw-weixin/blob/874637a0dbc24050f72d1385add4fc6170a2d726/src/api/session-guard.ts)

### QQ

腾讯插件2.0.4固定提交`89988812442583bf47c34b89f9abf5fd4b85df0b`，实现WS与Webhook；OpenClaw较窄的渠道说明不能用来否定插件中的Webhook实现。Webhook route依赖兼容且正在运行的OpenClaw Gateway ingress API；缺少helper时只记录日志并不注册路由。账号后台是否开放某模式未核实。历史BotGo“计划在2024年底前淘汰WS”的文字不证明该计划已经执行，当前实现仍同时包含两种模式。[腾讯插件配置](https://github.com/tencent-connect/openclaw-qqbot/blob/89988812442583bf47c34b89f9abf5fd4b85df0b/README.md)、[Webhook适配器](https://github.com/tencent-connect/openclaw-qqbot/blob/89988812442583bf47c34b89f9abf5fd4b85df0b/src/adapter/webhook.ts)

WS由客户端获取gateway地址并主动连接。官方协议明确描述断线后“短时间内”恢复会补发遗漏事件，成功RESUME按seq之后补发，完成后发RESUMED；未给“短时间”的数值、容量或任意离线时长保证。官方建议处理过事件再记录s；QQ的4009允许RESUME，4006/4007要求重新IDENTIFY，不要套用Discord的同号错误码含义。[QQ官方WS协议](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/event-emit/websocket.html)

恢复时SDK使用保存的`sessionId,lastSeq`尝试RESUME；`INVALID_SESSION d=false`清状态并重新IDENTIFY，`d=true`保留状态。平台重连指令仍需客户端运行后处理，不是平台反向连到沙箱。机器人身份不因本地进程暂停而由插件注销，但具体客户端UI和完全离线时平台接纳/排队规则未知。[SDK连接与恢复实现](https://github.com/tencent-connect/qqbot-nodejs/blob/ca55d9c395b582b7fcfad0ec27209c35dd04e0b3/src/protocol/gateway/gateway-connection.ts)

有一项文档/代码冲突必须保留：OpenClaw文档称raw ingress先于sequence推进；本插件仓库锁定的SDK1.0.4却先推进`lastSeq`、调用session保存，再不等待异步`onMessage`的完成。主代理直接核读了该顺序。这里确认的是调用顺序，不声称磁盘已经fsync，也不证明普通Pause丢失。插件依赖范围是`^1.0.4`，发布文件列表不包含仓库lock，因此锁定组合不等于所有安装实例；SDK1.0.5交叉阅读仍有相同顺序。[OpenClaw较强的文档声明](https://github.com/openclaw/openclaw/blob/f7257f2c66884611f4f4043367eada029b704918/docs/channels/qqbot.md)、[插件依赖与发布范围](https://github.com/tencent-connect/openclaw-qqbot/blob/89988812442583bf47c34b89f9abf5fd4b85df0b/package.json)

Webhook的所查SDK先启动异步dispatch，随即对有效回调返回HTTP200/op12；官方定义op12为HTTP Callback收到数据的确认，不是业务完成后ACK。处理异常只记录日志，没有稍后负确认。SDK注释提到超时可能重投，但本轮未找到平台独立公开的精确次数、间隔或窗口；成功ACK后也不能凭SDK代码保证平台一定不重复。5秒内存message ID去重是插件行为，不是离线保存期。[QQ官方Webhook](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/event-emit/webhook.html)、[官方payload定义](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/event-emit/payload.html)、[Webhook处理与ACK](https://github.com/tencent-connect/qqbot-nodejs/blob/ca55d9c395b582b7fcfad0ec27209c35dd04e0b3/src/protocol/transport/webhook.ts)、[内存去重](https://github.com/tencent-connect/qqbot-nodejs/blob/ca55d9c395b582b7fcfad0ec27209c35dd04e0b3/src/middleware/message-filter.ts)

### 钉钉

平台应用机器人提供Stream和HTTP两种消息接收模式；本轮所查`@dingtalk-real-ai/dingtalk-connector` 0.8.27，提交`88df00ee594072e9941ef3f71da90a37f3291ad3`，只实现Stream。群自定义机器人供外部向群发消息的Webhook地址，不等于接收用户消息的应用机器人HTTP入口。[平台接收说明](https://opensource.dingtalk.com/developerpedia/docs/learn/bot/appbot/receive/)、[connector启动路径](https://github.com/DingTalk-Real-AI/dingtalk-openclaw-connector/blob/88df00ee594072e9941ef3f71da90a37f3291ad3/src/channel.ts)

Stream由客户端取endpoint/ticket再连接WS。官方协议明确，**普通机器人消息是fire-and-forget，不会因为网络超时而重发**；EVENT订阅消息的ACK/失败重试不能套用到机器人CALLBACK。所查connector收到回调先ACK再开展解析/业务，无持久恢复cursor。断开后只有恢复执行的客户端能重连，未找到完全离线新消息保留/回放保证；不能因“Stream有ACK”宣称机器人消息必补。[官方Stream协议](https://opensource.dingtalk.com/developerpedia/docs/learn/stream/protocol/)、[connector连接与回调](https://github.com/DingTalk-Real-AI/dingtalk-openclaw-connector/blob/88df00ee594072e9941ef3f71da90a37f3291ad3/src/core/connection.ts)

普通应用机器人HTTP的精确超时、重试次数与离线保留未证实；该connector也无法据此形成HTTP恢复路径。这里保留平台能力行并标记`plugin_support: false`，不把平台与插件混为一谈。

### 企业微信

所查官方维护插件2026.10.19固定提交`2b8c84e696ec98c967ff95030270c6acb5c4b51d`，支持Bot WS、Bot HTTP JSON及自建应用Agent HTTP XML。Agent路由独立注册；Bot配置包含botId/secret时优先走WS，没有这组凭证且选择Webhook才启动Bot HTTP。Bot+Agent共存不是同一Bot同一事件双投。[插件模式说明](https://github.com/WecomTeam/wecom-openclaw-plugin/blob/2b8c84e696ec98c967ff95030270c6acb5c4b51d/README.zh.md)、[实际选择分支](https://github.com/WecomTeam/wecom-openclaw-plugin/blob/2b8c84e696ec98c967ff95030270c6acb5c4b51d/src/channel.ts)

**Bot WS：**客户端连接后subscribe；同一Bot只允许一个活跃连接，新连接可使旧连接收到`disconnected_event`。SDK会主动心跳/重连，但需要进程执行。官方对进入会话、卡片事件要求5秒内应答，不能把这个数字套到普通消息；普通回复授权24小时、流式从首次发送起10分钟完成，也不是离线事件保留期。未找到resume cursor、离线新消息回放期限或完整补投保证。[官方WS说明](https://developer.work.weixin.qq.com/document/path/101463)

**Bot HTTP JSON：**平台发加密回调；插件正常接收消息后先返回200与stream占位，异步处理，后续`stream_refresh`取回流式结果；异常处理也可能以200返回加密错误内容，因此不能把200当Agent已执行。普通回调可能重复，但精确重试节奏未公开。最多6分钟的刷新等待从用户消息开始计算，是回复等待限制，不是事件重试/保留期。插件stream状态在内存中；Pause保留内存与进程重建丢状态必须分开。缺失stream的refresh会结束，不等于重新处理原消息。[官方HTTP说明](https://developer.work.weixin.qq.com/document/path/100719)、[Bot处理实现](https://github.com/WecomTeam/wecom-openclaw-plugin/blob/2b8c84e696ec98c967ff95030270c6acb5c4b51d/src/webhook/handler.ts)

**Agent HTTP XML：**自建应用是另一种身份。官方写明5秒内响应，因网络连接失败或请求超时最多重试3次；不应扩大成所有非2xx/所有企业微信入口都相同。插件先HTTP200 `success`，再异步业务，后续失败没有传回平台；10分钟内存去重也不是平台离线邮箱。Agent的群场景未以Bot群@能力代替证明。[自建应用回调处理](https://developer.work.weixin.qq.com/document/path/90930)

### Slack

所查OpenClaw release提交`7dc3350cb9f08fcf9a0af5c4845a20d5b2f1a8be`，依赖Bolt5.1.0、socket-mode3.1.0。Socket Mode由客户端`apps.connections.open`取得URL再连WSS；平台的disconnect/reconnect提示仍由运行中的客户端处理。envelope要求ACK，但Socket Mode公共指南没有给出统一的重试次数、离线保留窗口或恢复回放保证。HTTP的Delayed Events规则对Socket Mode是否完全适用未查到明确保证，不借用。[Socket Mode](https://docs.slack.dev/apis/events-api/using-socket-mode)、[所查插件入站源码](https://github.com/openclaw/openclaw/tree/7dc3350cb9f08fcf9a0af5c4845a20d5b2f1a8be/extensions/slack/src)

**HTTP Events：**3秒内成功确认；失败最多重试3次，约立即、1分钟、5分钟。可选Delayed Events在普通重试后按小时继续，最长24小时，官方明确best-effort；不是默认每条都保证补送24小时。过去60分钟超过95%失败可能暂时停用订阅；每小时不足1000事件的应用有豁免。默认对延迟超过2小时的事件还有停止投递规则，启用Delayed Events时另算。30分钟SDK重试预算属于外发Web API，不能当作入站事件保留期。[Events API失败与重试](https://docs.slack.dev/apis/events-api/)、[Delayed Events公告](https://docs.slack.dev/changelog/2026/02/05/retry-events-feature/)

所查OpenClaw按event_id入队后ACK；平台成功ACK与Agent完成分离。恢复后不会自动扫描全部`conversations.history`补触发。Slack relay若在沙箱外仍在线，已经改变唯一接收端随沙箱休眠的前提；relay是否有队列、是否触发恢复须另证，不能由`relay`配置名推断。[Slack HTTP与Socket模式文档](https://github.com/openclaw/openclaw/tree/7dc3350cb9f08fcf9a0af5c4845a20d5b2f1a8be/docs/channels/slack)

### Discord

Gateway Resume使用session_id、resume_gateway_url和最后sequence；session有效时可回放遗漏事件。意外TCP断开后服务端保留session“几分钟”，没有精确TTL承诺；正常1000/1001关闭会使session失效并标为offline。`INVALID_SESSION false`、4007/4009等需要重新IDENTIFY，不能继续承诺回放。聊天历史存在不代表新IDENTIFY会把历史转成MESSAGE_CREATE事件。[Gateway恢复会话](https://docs.discord.com/developers/events/gateway)、[关闭码与opcode](https://docs.discord.com/developers/topics/opcodes-and-status-codes)

所查OpenClaw把恢复字段保存在Gateway对象内存。保留同进程状态、旧session仍有效且没有被干净关闭时，Pause恢复可尝试RESUME；插件主动`disconnect()`使用1000，若休眠流程调用该方法便会使旧session失效。进程重建没有自动从磁盘恢复这三个字段的路径，通常重新IDENTIFY。已回放的MESSAGE_CREATE可进入接收处理；文档中的15分钟@优先级逻辑不是统一的旧消息丢弃期。[固定Gateway实现](https://github.com/openclaw/openclaw/blob/f7257f2c66884611f4f4043367eada029b704918/extensions/discord/src/internal/gateway.ts)

### WhatsApp Web / Baileys

本轮为OpenClaw WhatsApp Web设备接入，依赖Baileys7.0.0-rc14，固定提交`7e7b0757e3f9f3c7789fb1cfd2f241d5002a199a`；不是WhatsApp Business Cloud API的Webhook集成。关联设备有自己的连接和加密交付，其他设备收到不等于这个Baileys设备收到，消息双灰勾也不能证明OpenClaw本地队列或Agent已接受。[关联设备说明](https://faq.whatsapp.com/378279804439436/)、[消息勾状态](https://faq.whatsapp.com/665923838265756/)

所查英国隐私政策版本说明未交付加密消息可在服务端暂存最多30天，届时仍未交付会删除；这是该政策范围的未交付消息规则，**不是这个关联设备的完整回放SLA**，也不是30天内必有OpenClaw回复。主手机超过14天未使用导致关联设备退出，与关联设备本身超过30天不活跃自动断开，是两种条件，也均不同于未交付消息的30天暂存规则。[英国隐私政策2026-03-26版本](https://www.whatsapp.com/legal/privacy-policy-uk/revisions/20260326)、[关联设备活跃规则](https://faq.whatsapp.com/378279804439436/)

Baileys delivery receipt早于`messages.upsert`处理，不等于OpenClaw持久接收。历史同步`messaging-history.set`与实时/离线upsert是不同路径；该插件不启用完整历史同步，不能保证历史自动触发Agent。`offline_batch`的100是批大小线索，不是总计最多补100条的保证。[Baileys消息接收源码](https://github.com/WhiskeySockets/Baileys/blob/7e7b0757e3f9f3c7789fb1cfd2f241d5002a199a/src/Socket/messages-recv.ts)

OpenClaw的旧消息过滤只针对`append`，不适用于`notify`。默认阈值是连接建立时间减60秒，并非每一刻都按“现在减60秒”过滤。符合条件且近期收到消息的同一controller重连，会临时放宽catch-up，最多覆盖20分钟；窗口结束恢复默认阈值。新controller启动通常走默认startup guard。因此“恢复后一律补20分钟”或“一律丢60秒前的消息”都不正确。被过滤的append仍可能完成接收/已读，却不触发Agent。[实际年龄过滤](https://github.com/openclaw/openclaw/blob/7dc3350cb9f08fcf9a0af5c4845a20d5b2f1a8be/extensions/whatsapp/src/inbound/message-delivery.ts)、[重连catch-up窗口](https://github.com/openclaw/openclaw/blob/7dc3350cb9f08fcf9a0af5c4845a20d5b2f1a8be/extensions/whatsapp/src/auto-reply/monitor.ts)

### Mattermost

需要区分平台恢复能力与插件接入。所查服务端提交`69d345c93a527cc1361792cc967714fea9f99083`支持通过`connection_id`、`sequence_number`及升级时已认证的同一用户尝试恢复被保留的WebConn。服务端内存中deadQueue的128个已写事件、inactive sendQueue的256个待发事件不是聊天消息条数保证；队列溢出、清理、hub/进程变化都会限制恢复。清理按最后用户活动时间，不是保证断线后整整5分钟有效。[服务端WS入口](https://github.com/mattermost/mattermost/blob/69d345c93a527cc1361792cc967714fea9f99083/server/channels/api4/websocket.go)、[连接队列](https://github.com/mattermost/mattermost/blob/69d345c93a527cc1361792cc967714fea9f99083/server/channels/app/platform/web_conn.go)、[hub与清理](https://github.com/mattermost/mattermost/blob/69d345c93a527cc1361792cc967714fea9f99083/server/channels/app/platform/web_hub.go)

所查OpenClaw插件没有附带恢复参数，也没有在HTTP Upgrade时带token认证；它在WS建立后发送`authentication_challenge`。主代理直接核读双方入口，确认该插件走新连接，不能获得上述条件式补收。客户端action的`seq`也不是服务端事件恢复序号。重连不会自动补齐断线时错过的`posted`触发；后来新消息引起的线程上下文回填，只是读上下文，不是让旧消息逐条重新触发Agent。[插件建连/认证](https://github.com/openclaw/openclaw/blob/f7257f2c66884611f4f4043367eada029b704918/extensions/mattermost/src/mattermost/monitor-websocket.ts)、[线程回填](https://github.com/openclaw/openclaw/blob/f7257f2c66884611f4f4043367eada029b704918/extensions/mattermost/src/mattermost/monitor-thread-backfill.ts)

### Microsoft Teams

Bot Framework Service向注册endpoint POST activity；应用安装和身份不依赖沙箱进程持续运行。所查OpenClaw普通message和`adaptiveCard/action`进入本地durable ingress；typing、reaction等不能据此统称durable消息。普通message入队后完成SDK请求，入队失败不成功ACK；卡片invoke走自己的响应。没有启动时自动扫描历史补事件的路径。[固定Teams接收实现](https://github.com/openclaw/openclaw/blob/f7257f2c66884611f4f4043367eada029b704918/extensions/msteams/src/monitor.ts)、[可入队活动类型](https://github.com/openclaw/openclaw/blob/f7257f2c66884611f4f4043367eada029b704918/extensions/msteams/src/msteams-ingress.ts)

通用Bot Framework文档说“most channels”超15秒会504，不能把它变成Teams普通消息的专属精确SLA。Teams `composeExtensions/submitAction`的5秒和client两次重试是消息扩展invoke特例，不能套用到用户普通聊天；该invoke也不在固定插件durable allowlist，不能凭支持`adaptiveCard/action`推定消息扩展submit已实现。Teams agent slash命令属于targeted普通message，是否在目标manifest公开仍未核。普通Teams message的精确失败重试次数、间隔、总窗口和离线事件保留，本轮未找到公开保证。外部入口可能先唤醒再超时；HTTP200也不能证明Agent完成。[Bot Framework HTTP说明](https://learn.microsoft.com/en-us/azure/bot-service/bot-builder-basics?view=azure-bot-service-4.0)、[消息扩展submitAction](https://learn.microsoft.com/en-us/microsoftteams/platform/messaging-extensions/how-to/action-commands/respond-to-task-module-submit)、[Teams消息与命令路由](https://learn.microsoft.com/en-us/microsoftteams/platform/teams-sdk/essentials/on-activity/overview)

### Google Chat

所查OpenClaw实现是HTTPS interaction endpoint，不接Pub/Sub。Google Chat可以向配置URL发新请求；同步响应需在30秒内，异步任务先空JSON确认。网络错误、timeout、非2xx时，平台可能在几分钟内重试几次，但明确不保证；成功HTTP请求若payload无效则不重试。精确次数/节奏/独立HTTP超时未公开，不把30秒同步回复期推成离线保留期。[官方接收与回复](https://developers.google.com/workspace/chat/receive-respond-interactions)、[插件模式说明](https://github.com/openclaw/openclaw/blob/f7257f2c66884611f4f4043367eada029b704918/docs/channels/googlechat.md)

插件仅把MESSAGE写入durable ingress后回200 `{}`，入队失败回503；其他交互有独立处理，不全是Agent turn。收到200后平台看不到后续Agent失败。Workspace Events API/Pub/Sub是另一种能力，不是本插件已实现的恢复通道；也未发现自动历史补拉。[Webhook实现](https://github.com/openclaw/openclaw/blob/f7257f2c66884611f4f4043367eada029b704918/extensions/googlechat/src/monitor-webhook.ts)、[MESSAGE入队](https://github.com/openclaw/openclaw/blob/f7257f2c66884611f4f4043367eada029b704918/extensions/googlechat/src/monitor-ingress.ts)

旧式Chat事件的slash命令属于MESSAGE；新式add-on envelope需要另看payload。所查插件把`chat.messagePayload`规范化为MESSAGE，未把`chat.appCommandPayload`映射或纳入durable turn。因此不能把“空间中有app command”推成当前插件对所有新旧命令都能唤醒后处理；实际app事件格式仍需核配置。[事件规范化源码](https://github.com/openclaw/openclaw/blob/f7257f2c66884611f4f4043367eada029b704918/extensions/googlechat/src/monitor-event.ts)

### LINE

LINE Official Account/Messaging API channel身份仍存在，原有好友私聊、已加入群/多人会话可产生事件。Webhook redelivery默认关闭；需同时启用Webhook接收及重投。没有获得2xx时才按平台预设策略重送，次数、间隔和总窗口不公开且可变，明确best-effort。持续失败后可能停止发送并通知。错误统计将未在2秒内响应归类为`request_timeout`；这是诊断定义，不扩写成所有路径的SLA。[接收与redelivery](https://developers.line.biz/en/docs/messaging-api/receiving-messages/)、[错误统计](https://developers.line.biz/en/docs/messaging-api/check-webhook-error-statistics/)、[停止与通知](https://developers.line.biz/en/docs/partner-docs/error-notification/)

所查插件校验签名并入队后回200，写入失败回500；standby批次可以200但不入队/不回复。message按message ID去重，其他事件按webhookEventId。重投可能重复、乱序；平台没有通用聊天文本历史拉取API来弥补已停止的回调。插件5秒body-read guard和本地队列退避，均不是平台入站重试窗口。[LINE处理与队列说明](https://github.com/openclaw/openclaw/blob/f7257f2c66884611f4f4043367eada029b704918/docs/channels/line.md)、[Webhook handler](https://github.com/openclaw/openclaw/blob/f7257f2c66884611f4f4043367eada029b704918/extensions/line/src/webhook-node.ts)

replyToken单次使用，通常在收到Webhook后1分钟内使用；收到重投时可在重投后1分钟内尝试，但原token已使用或事件已发生20分钟就不能再用。因此补事件不保证原token可回复。OpenClaw可条件式fallback为push：识别到HTTP status时，仅4xx且非408允许；没有HTTP status时，先拒绝AbortError/ambiguous，再允许pre-connect，最后除精确`TypeError("fetch failed")`外其他未分类错误也可放行。partial delivery另行禁止fallback；predicate放行不证明具体结果安全或送达。尝试后token slot标为已用，push自身仍可能失败。这是回复路径，不是平台redelivery或唤醒保证。[replyToken官方规则](https://developers.line.biz/en/reference/messaging-api/nojs/)、[主代理核读的fallback实现](https://github.com/openclaw/openclaw/blob/f7257f2c66884611f4f4043367eada029b704918/extensions/line/src/auto-reply-delivery.ts)

### Telegram

Bot API公开说明`getUpdates`与Webhook互斥；pending Updates最长不超过24小时。`getUpdates`只有在后续请求的offset高于某条update_id时，才将那条update视为已确认。WebHook失败会重试，但所查公开文档未规定统一次数或总重试窗口，不能将24小时上限改写成每条事件必重试整整24小时。显式`drop_pending_updates=true`会丢弃待处理更新；持续对全部Webhook请求返回410超过23小时，Webhook可能被自动移除。[Bot API](https://core.telegram.org/bots/api#getting-updates)、[官方变更记录](https://core.telegram.org/bots/api-changelog)

所查插件的轮询启动调用`deleteWebhook({drop_pending_updates:false})`，Webhook注册省略该丢弃参数。入站先写本地队列，再推进接收确认/offset；本地队列能恢复未被Agent采用的事件，但只覆盖已经入队的内容。文档中的超过24小时旧spool迁移过滤属于旧本地数据导入，不能误当成普通启动清空平台pending。[Telegram传输与入队边界](https://github.com/openclaw/openclaw/blob/v2026.10.10/docs/channels/telegram/transports.md)

### Matrix

`/sync`使用上次`next_batch`作为`since`请求增量状态和事件，`timeout`是服务端等待时长。timeline可能被标记为`limited`，只包含最近一段并留下gap；协议提供`/rooms/{roomId}/messages`分页补洞机制，但不能由“有这个API”推出客户端一定会自动调用。homeserver历史保留与房间可见性也不保证永久完整历史。[Matrix Client-Server API v1.19](https://spec.matrix.org/v1.19/client-server-api/#get_matrixclientv3sync)

所查OpenClaw先将入站事件写入本地spool再推进sync cursor。无已保存cursor的首次接入，会排除启动前历史，并保持该排除状态；这不是忽略整个初始sync中的所有消息。已经保留cursor的Pause/Resume与丢失状态后首次登录不同。所查自动接收路径消费sync batch，不能承诺自动回填所有limited timeline缺口。[Matrix入站恢复说明](https://github.com/openclaw/openclaw/blob/f7257f2c66884611f4f4043367eada029b704918/docs/channels/matrix/messaging.md)

### IRC

IRC的nickname和频道成员资格依赖在线会话。TCP断开被服务端识别后，会话退出，nick通常释放；NickServ保留名字不等于存在消息邮箱。给当前不存在的nick发`PRIVMSG`，协议定义`401 ERR_NOSUCHNICK`；给仍有其他成员、且发送者有权发言的频道发消息，则按现存成员分发。服务器尚未识别死连接的窗口内，不能保证用户立刻收到离线错误。[RFC2812的PRIVMSG与错误回复](https://www.rfc-editor.org/rfc/rfc2812.html#section-3.3.1)、[IRC连接关闭与频道语义](https://www.rfc-editor.org/rfc/rfc1459.html)

当前OpenClaw IRC客户端会重建TCP/TLS连接、重新注册并JOIN配置频道，没有CHATHISTORY/SASL协商实现。IRCv3历史或外部bouncer可以提供额外能力，但不属于本轮普通IRC插件的补投保证。插件本地已接收队列只保护接收后的工作；其旧连接epoch私聊还可能因nick重新归属风险而被排除。[IRC插件行为](https://github.com/openclaw/openclaw/blob/f7257f2c66884611f4f4043367eada029b704918/docs/channels/irc.md)、[客户端](https://github.com/openclaw/openclaw/blob/f7257f2c66884611f4f4043367eada029b704918/extensions/irc/src/client.ts)、[接收与重连](https://github.com/openclaw/openclaw/blob/f7257f2c66884611f4f4043367eada029b704918/extensions/irc/src/monitor.ts)、[IRCv3 CHATHISTORY](https://ircv3.net/specs/extensions/chathistory)

## 6. 校验与运行验证边界

先由9路专题调查分别负责平台，再由另一批5路交叉校验检查其他调查者的结果：飞书/钉钉/企业微信，微信/QQ/Telegram/Matrix，Slack/Discord/Mattermost/WhatsApp，Teams/Google Chat/LINE/IRC，以及全局范围/计数/因果一致性。平台校验读取关键原始文档与固定源码，聚合校验负责范围和跨组语义；实际分工与结果记录在YAML。主代理核读关键源码并整合，不把资料复核标为设计/代码批准或人工验收。

本轮校验已整合的实质补充包括：QQ官方短时Resume补发契约与未公开数值窗口；LINE完整fallback判定而非过窄白名单；Teams普通消息与特例invoke、Google Chat新旧命令payload的支持边界；Discord干净关闭对Resume的影响；Mattermost有界源码能力与插件未接入的区别；WhatsApp地域政策及条件过滤的范围。15平台、22基线场景、4协议、21个插件实现及来源引用通过结构核对。

本轮仅进行官方资料检索、维护方源码阅读、平台与插件行为交叉核对。未配置真实机器人、未登录平台账号、未发送消息、未抓包、未执行SDK或沙箱Pause/Resume/E2E。本文不证明任何目标部署具备实际唤醒能力。实际插件版本、账号后台开关、外部入口职责、内存/磁盘恢复方式仍未知；平台没有公开的保留/重试保证也仍是未知，不能用实测之外的推测补成必达或必丢。

既有飞书专题见 [飞书事件接收原理](feishu-event-transports.md)；候选唤醒链路的既有边界见 [IM唤醒能力边界](im-wakeup-paths-and-capabilities.md)。本调查不改变项目既有需求、可靠性约定或工作项状态。
