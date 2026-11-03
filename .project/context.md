# IM 自动唤醒

管理消息和流量唤醒相关需求，关联 OKAWorkspace。

- 工作项 1：Gateway 流量自动唤醒后的 shutdownTime/pauseTime 调整及流量续期，从 oka-daily-open-source 迁入，保留既有开发状态、设计与审查证据。
- 工作项 2：基于 Webhook 事件的 Sandbox 自动唤醒，保留既有 ID `2-feishu-wake-openclaw`。
- 工作项 3：基于 WebSocket 事件的 Sandbox 自动唤醒，ID 为 `3-websocket-wakeup`。

工作项 2、3 为并列需求，无相互前置依赖。能力面向通用 IM 与应用，飞书和 OpenClaw 是首个场景。用户已要求设计探索、两种方式都支持，并于 2026-11-03 要求保存原理分析和拆分需求。工作项 2 随后开始设计，用户最终明确采用 Gateway 内存接收；工作项 3 保持需求登记。两项尚无完整正式设计、独立审查或业务实现。

Webhook 采用 Gateway 内存接收后确认、异步恢复与交付，用户接受该 Gateway 退出后事件丢失。首期每个接入绑定一个已有 Sandbox，自动唤醒开关开启时允许手动 Pause 后唤醒。内存任务的正常下线排空仍需设计；已按实际 ack-components 编排核验现有机制，见 `evidence/ack-gateway-webhook-shutdown.md`。Webhook 的选择不自动成为 WebSocket 的已批准契约。

具体契约、状态及交付义务以各工作项为准。
