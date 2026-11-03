# OpenClaw 飞书 IM 接入机制

调研日期：2026-11-03。关联需求：[飞书消息自动唤醒 OpenClaw](../workitems/2-feishu-wake-openclaw/requirement.md)。基于官方在线文档和 `openclaw/openclaw` 的 `main` 源码页面，尚未绑定实际部署版本或执行端到端验证。

## 接入与消息处理

OpenClaw 使用官方 `@openclaw/feishu` 频道插件，通过飞书应用机器人接收私聊和群聊事件。应用凭据为 `appId` / `appSecret`，支持国内飞书和国际 Lark。[官方接入说明](https://docs.openclaw.ai/channels/feishu)

| 传输方式 | 工作机制 | 运行条件 |
| --- | --- | --- |
| WebSocket（默认） | OpenClaw 内的飞书 SDK 主动向平台建连，接收推送事件 | 接收进程持续运行且可访问公网，无须公网回调 URL |
| HTTP Webhook | 飞书向配置的事件回调 URL 发送 POST | 提供平台可访问的入口；当前文档默认与 OpenClaw Gateway 共用 `18789` 端口，路径 `/feishu/events`；旧安装可能保留独立监听地址 |

两者由 `channels.feishu.connectionMode` 选择。这里的 OpenClaw Gateway 是 OpenClaw 自身进程，与 Sandbox 的流量网关 `sandbox-gateway` 是两个组件。[配置 Schema](https://github.com/openclaw/openclaw/blob/main/extensions/feishu/src/config-schema.ts)、[传输实现](https://github.com/openclaw/openclaw/blob/main/extensions/feishu/src/monitor.transport.ts)

消息处理链路为：飞书事件 → 传输接收与鉴权 → 持久化入口 → 消息解析、去重和访问策略 → Agent/会话路由 → Agent 执行 → 飞书发送或回复 API。

关键源码位于 `extensions/feishu/src/`：

| 入口 | 职责 |
| --- | --- |
| [`monitor.account.ts`](https://github.com/openclaw/openclaw/blob/main/extensions/feishu/src/monitor.account.ts) | 注册消息事件 `im.message.receive_v1`，启动 WebSocket 或 Webhook |
| [`feishu-ingress.ts`](https://github.com/openclaw/openclaw/blob/main/extensions/feishu/src/feishu-ingress.ts) | 持久化接收，以 `event_id` 标识事件、`chat_id` 划分消息串行队列 |
| [`monitor.message-handler.ts`](https://github.com/openclaw/openclaw/blob/main/extensions/feishu/src/monitor.message-handler.ts) | 消息结构检查、去重、串行与合并处理 |
| [`bot.ts`](https://github.com/openclaw/openclaw/blob/main/extensions/feishu/src/bot.ts) | 私聊/群聊访问策略与 Agent、会话路由 |
| [`message-send.ts`](https://github.com/openclaw/openclaw/blob/main/extensions/feishu/src/message-send.ts) | 调用 `im.message.reply` / `im.message.create` 回复消息 |

路由使用 `channel`、`accountId` 和 `peer`：私聊通常按用户 `open_id`，群聊通常按 `chat_id`，话题配置会进一步影响会话划分。该路由选择 OpenClaw 内部 Agent；外部 Sandbox 映射仍需建立。[多账户与路由](https://docs.openclaw.ai/channels/feishu/advanced-configuration)

私聊默认采用 `pairing`，群聊默认采用 `allowlist`，还受发送者和 @mention 规则控制。飞书侧的机器人能力、事件订阅和消息权限决定哪些事件可被投递；OpenClaw 策略决定收到后是否执行。因此，“收到事件”与“应该唤醒并执行”须分别判断。[访问控制](https://docs.openclaw.ai/channels/feishu/access-control)

## 确认、消息保留与鉴权

所读版本对认证后的 `im.message.receive_v1` 提供持久化入队：Webhook 在入队后返回成功，携带 `x-openclaw-delivery-accepted: durable`。待处理或可重试事件可跨进程重启保留，依赖状态存储保留。验证 challenge、表情等其他事件不享有同样保证。接收成功也不表示 Agent 已完成或回复成功。[持久化说明](https://docs.openclaw.ai/channels/feishu/setup)

去重包含事件和消息两层。除队列 `event_id` 外，完整文本事件的逻辑键还使用发送者、聊天、创建时间和内容摘要，字段不全时回退到 `message_id`；媒体另有处理。该机制保护已接收事件，不能保证断线期间未收到的消息会被补投。[去重实现](https://github.com/openclaw/openclaw/blob/main/extensions/feishu/src/dedupe-key.ts)

飞书官方页面的搜索摘要列出以下约束；本次浏览工具无法读取这两篇正文，具体参数在设计采用前仍需复核：

- 长连接仅支持企业自建应用；同应用最多 50 条连接，多客户端按集群方式随机单客户端接收，不广播。[长连接说明](https://open.feishu.cn/document/ukTMukTMukTM/uYDNxYjL2QTM24iN0EjN/event-subscription-configure-)
- HTTP 事件须在三秒内返回 200，长连接 handler 须及时完成且不抛异常；失败重试间隔为 15 秒、5 分钟、1 小时、6 小时，最多四次。平台采用至少一次投递，成功接收也可能重复；v2 信封建议以 `event_id` 幂等。[事件订阅说明](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/event-subscription-guide/event-subscriptions)

当前 OpenClaw Webhook 配置要求 `verificationToken` 和 `encryptKey`，校验请求签名及时间戳，允许的时钟偏差为一小时。转发时修改原始 body 会影响签名，长时间排队后原样重放可能超时；后续需明确外部接收层与 OpenClaw 的鉴权边界。[Schema](https://github.com/openclaw/openclaw/blob/main/extensions/feishu/src/config-schema.ts)、[验签代码](https://github.com/openclaw/openclaw/blob/main/extensions/feishu/src/monitor.transport.ts)

## 对 Sandbox Pause 唤醒的约束

根据上述机制可推得：**产生唤醒信号的接收入口必须在目标 Sandbox Pause 时仍能接收事件。**

| 场景 | 判断与待验证点 |
| --- | --- |
| OpenClaw 和 WebSocket 接收进程一起 Pause | 暂停进程无法处理事件或主动重连，也不会自然产生经过 sandbox-gateway 的新 HTTP 请求。未找到断线期间事件必然保留、恢复后必然补投的官方保证 |
| 飞书 Webhook 经 sandbox-gateway 进入 OpenClaw | 从流量方向看存在使用 HTTP 自动唤醒的可能；须验证回调路由、鉴权、冷启动确认窗口和首条消息保留 |
| Sandbox 外保持接收器运行 | 可在 Sandbox Pause 时获知消息；仍须解决目标映射、唤醒权限、持久化与重投。同应用额外建立长连接可能分走事件，不能作为广播旁路 |

以上为研究方向，尚未选定实现方案。实施前需要确认实际 OpenClaw/插件版本与传输配置、接收进程部署位置、应用/用户/群聊到 Sandbox 的映射，以及触发范围、首条消息处理、时延和失败反馈要求。
