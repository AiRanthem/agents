# IM 自动唤醒

管理消息和流量唤醒相关需求，关联 OKAWorkspace。

- 工作项 1：Gateway 流量自动唤醒后的 shutdownTime/pauseTime 调整及流量续期，从 oka-daily-open-source 迁入，保留既有开发状态、设计与审查证据。
- 工作项 2：基于 Webhook 事件的 Sandbox 自动唤醒，保留既有 ID `2-feishu-wake-openclaw`，汇总两个子任务：`21-webhook-gateway-code` 负责 Gateway 代码，`22-webhook-ack-orchestration` 负责 ACK 编排，后者依赖前者代码交付。
- 工作项 3：基于 WebSocket 事件的 Sandbox 自动唤醒，ID 为 `3-websocket-wakeup`。

工作项 2、3 为并列需求，无相互前置依赖。能力面向通用 IM 与应用，飞书和 OpenClaw 是首个场景。用户已要求设计探索、两种方式都支持，并于 2026-11-03 要求保存原理分析和拆分需求。工作项 2 随后开始设计，用户最终明确采用 Gateway 内存接收；工作项 3 保持需求登记。两项尚无完整正式 spec 或业务实现。2026-11-04 按用户要求完成 Webhook 独立设计审查：父项 2 与代码子项 21 因必要契约未决而 Unable to conclude，编排子项 22 的语义契约 Independent review passed；原始结果见 `workitems/2-feishu-wake-openclaw/records/design-review-20261104.md`。这些结论不建立代码、镜像或编排交付。

Webhook 采用 Gateway 内存接收后确认、异步恢复与交付，用户接受该 Gateway 退出后事件丢失。首期每个接入绑定一个已有 Sandbox，自动唤醒开关开启时允许手动 Pause 后唤醒。2026-11-04，用户确认正常下线的细化方案，并指定业务排空最多等待 60 秒，排空后再执行原有 Envoy drain。编排按本地调用 65 秒、Envoy 调用 5 秒、连接等待 30 秒及退出余量 20 秒核算，目标总 grace 为 120 秒。实际 ack-components 编排仍是此前核验的 90 秒；项目记录不是编排变更。证据与当前约定见 `evidence/ack-gateway-webhook-shutdown.md`。Webhook 的选择不自动成为 WebSocket 的已批准契约。

具体契约、状态及交付义务以各工作项为准。
