# 当前上下文

`2-feishu-wake-openclaw` 当前标题为“基于 Webhook 事件的 Sandbox 自动唤醒”。保留稳定 ID，范围收敛到 HTTP Webhook 入口；WebSocket 入口由同级 `3-websocket-wakeup` 承接。

用户明确两种方式都要、能力需要通用化，并要求先研究飞书原理、再保存链路分析并拆为两个并列需求。飞书与 OpenClaw 是首个场景，外部接收组件、队列、应用内部 HTTP 交付接口均未选定。

当前完成协议研究、机制分析和需求拆分，无正式 spec、独立审查、实施代码或运行验证。后续在已有设计探索授权内细化 requirement.md 的待决事项；实施仓库仍未选定。

知识入口：[链路与能力分析](../../evidence/im-wakeup-paths-and-capabilities.md)、[飞书协议原理](../../evidence/feishu-event-transports.md)、[OpenClaw 接入机制](../../evidence/openclaw-feishu-im-mechanism.md)。
