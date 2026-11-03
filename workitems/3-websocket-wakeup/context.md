# 当前上下文

`3-websocket-wakeup`（基于 WebSocket 事件的 Sandbox 自动唤醒）与 `2-feishu-wake-openclaw`（Webhook 唤醒）为同级需求，无相互前置依赖。`split_from` 仅记录原需求来源。

用户明确两种方式都要、能力需要通用化，并于 2026-11-03 要求保存原理分析后拆为两个并列需求。飞书与 OpenClaw 是首个场景。

长连接接收责任必须在 Sandbox 旧连接失效后仍有着落；平台不保证额外客户端广播消费或无限离线补投。外部 SDK 接收并适配应用、保留应用原客户端方式的协议代理，是不同候选兼容范围，均未选定。

当前完成协议研究、机制分析及需求登记，无正式 spec、独立审查、实施代码或运行验证。后续在已有设计探索授权内细化 requirement.md 的待决事项；实施仓库仍未选定。

知识入口：[链路与能力分析](../../evidence/im-wakeup-paths-and-capabilities.md)、[飞书协议原理](../../evidence/feishu-event-transports.md)、[OpenClaw 接入机制](../../evidence/openclaw-feishu-im-mechanism.md)。
