# 当前上下文

`2-feishu-wake-openclaw` 当前标题为“基于 Webhook 事件的 Sandbox 自动唤醒”。保留稳定 ID，范围收敛到 HTTP Webhook 入口；WebSocket 入口由同级 `3-websocket-wakeup` 承接。

用户明确两种方式都要、能力需要通用化，并要求先研究飞书原理、再保存链路分析并拆为两个并列需求。飞书与 OpenClaw 是首个场景。

用户于 2026-11-03 启动本项设计，并明确选择可靠接收：Sandbox 外持久化成功后确认，异步恢复并重试交付。当前继续细化设计，无正式 spec、独立审查、实施代码或运行验证。外部接收组件的部署、存储产品、应用交付协议及实施仓库仍未选定。

## 交付链路证据

本轮核对 OpenClaw 固定源码提交 `0a0d601bf12dfea5e4c94c3e8cd6d823c405d9a0`，该快照不代表实际部署版本：

- [Webhook 入口](https://github.com/openclaw/openclaw/blob/0a0d601bf12dfea5e4c94c3e8cd6d823c405d9a0/extensions/feishu/src/monitor.transport.ts)：以原始请求体验签，签名时间戳允许与本地时钟相差一小时；持久化接收成功时返回 `x-openclaw-delivery-accepted: durable`，challenge 的普通 200 不带该标记。
- [持久化入口](https://github.com/openclaw/openclaw/blob/0a0d601bf12dfea5e4c94c3e8cd6d823c405d9a0/extensions/feishu/src/feishu-ingress.ts)：等待 `monitor.admit` 后才报告 durable；所查 Feishu 接线中未发现供外部接收器提交已认证事件的专用 HTTP 接口。
- [消息发送](https://github.com/openclaw/openclaw/blob/0a0d601bf12dfea5e4c94c3e8cd6d823c405d9a0/extensions/feishu/src/message-send.ts)：OpenClaw 在独立出站请求中调用 `im.message.reply` 或 `im.message.create`，Webhook 确认与最终回复是不同结果。

因此，延迟交付不能假定旧签名永远有效；应用持久化接收可作为交付完成判据的候选，但仍须确定实际目标版本和交付鉴权方式。已完成源码与官方文档核对，未进行真实消息、Pause/Resume 或端到端验证。

## 待决范围

- 接入到 Sandbox 的映射：每个接入固定一个已有目标，或按用户/会话路由多个目标。
- 手动 Pause 与自动唤醒开关的关系。
- 消息保留、重试和失败终止规则，以及去重、交付完成和应用业务执行的边界。
- 首期事件范围、凭据与目标配置、接收层故障容忍范围、代码与部署归属。

知识入口：[链路与能力分析](../../evidence/im-wakeup-paths-and-capabilities.md)、[飞书协议原理](../../evidence/feishu-event-transports.md)、[OpenClaw 接入机制](../../evidence/openclaw-feishu-im-mechanism.md)。
