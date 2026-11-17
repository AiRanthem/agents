# 当前上下文

## 当前契约与授权

`3-websocket-wakeup`（基于 WebSocket 事件的 Sandbox 自动唤醒）与 `2-feishu-wake-openclaw`（Webhook 唤醒）并列，无相互前置依赖；`split_from` 仅记录来源。

2026-11-17，用户对本会话集中呈现的完整首期契约及 `workitems/3-websocket-wakeup/spec.md` 正式落位回答“确认”。当前唯一正式设计为 [spec.md](spec.md)，版本 1、`review-pending`。作者为 Codex 主代理（本会话）；用户决定的具体来源见 [decision.md](decision.md)。

契约采用暂停边界外接收、平台适配器和统一唤醒核心，首期交付公共框架与飞书／OpenClaw 适配。账号／接入固定绑定一个已有 Sandbox，一个 Sandbox 可有多个绑定；应用允许调整为内部事件接入。运维配置及凭据可恢复，消息只在外部接收器内存暂存，进程退出可以丢失已确认消息。

首期同账号单活、受控重启，旧实例是否停止尚不确定时不自动接管。完整业务事件在内存接纳后按平台协议确认；恢复和交付固定到原实例身份，不能转向同名重建对象。内部入口返回 HTTP `202` 和相同交付 ID，表示原生队列接纳；Agent 处理及回复另外观察。恢复、容量和消息期限有限，应用交付临时失败最多再重试 5 次。停用后旧消息按原目标有限处理，换绑不迁移旧消息。详细行为、配置内容和验收均以正式设计为准。

## 固定版本证据

以下是此前设计探索期间的静态源码证据，本次正式落位没有重新查询实际部署版本或执行运行验证。

- 飞书官方 Node SDK `b188be60134d409b61259546bcf69c731d2b0b7c`（`@larksuiteoapi/node-sdk` 1.76.0）的 [WebSocket 事件处理](https://github.com/larksuite/node-sdk/blob/b188be60134d409b61259546bcf69c731d2b0b7c/ws-client/index.ts) 在分片重组得到完整事件后等待事件分发入口返回，再发送业务确认。外部接收层可在内存准入后及时返回；不能将分片缓存当作消息持久队列，也不能遗漏接纳处理入口而仍成功确认。
- OpenClaw `f7257f2c66884611f4f4043367eada029b704918` 的 [channel inbound SDK](https://github.com/openclaw/openclaw/blob/f7257f2c66884611f4f4043367eada029b704918/docs/plugins/sdk-channel-inbound.md) 提供进程内方法，核读范围内未发现可直接使用的通用跨频道外部 HTTP 注入入口。薄适配入口需要新增；应用仍须使用实际频道和同一宿主运行时生成 [channel ingress](https://github.com/openclaw/openclaw/blob/f7257f2c66884611f4f4043367eada029b704918/docs/plugins/sdk-channel-ingress.md) 证据，不能将外部 JSON 或旧宿主证据直接当作业务授权。
- 同一 OpenClaw 快照的 [飞书 ingress](https://github.com/openclaw/openclaw/blob/f7257f2c66884611f4f4043367eada029b704918/extensions/feishu/src/feishu-ingress.ts) 已使用原生事件 ID 入队及去重；[durable ingress 契约](https://github.com/openclaw/openclaw/blob/f7257f2c66884611f4f4043367eada029b704918/docs/plugins/sdk-channel-plugins/durable-ingress.md) 区分接纳和执行完成，去重保留受 TTL 与容量限制。复用应用已有队列不改变外部接收器仅内存的选择，不形成永久或全局恰好一次保证。
- 同一快照的 [飞书回复](https://github.com/openclaw/openclaw/blob/f7257f2c66884611f4f4043367eada029b704918/extensions/feishu/src/message-send.ts) 使用消息 API；[WhatsApp socket 会话](https://github.com/openclaw/openclaw/blob/f7257f2c66884611f4f4043367eada029b704918/extensions/whatsapp/src/inbound/socket-session.ts) 和 [IRC monitor](https://github.com/openclaw/openclaw/blob/f7257f2c66884611f4f4043367eada029b704918/extensions/irc/src/monitor.ts) 的现有回复路径依赖活动连接。后续这些平台的适配必须覆盖外部会话上的回复／必要操作，首期不实现它们。
- 设计探索所查 Agents 固定基线为 `cfbd102bc05c6df663965c5e23463a0eafd34948`。原 Gateway 唤醒调用按 namespace/name 查找，不能据此认定本设计要求的原实例身份约束已贯穿恢复写入与交付。`worktrees/1-gateway-wakeup-lifecycle` 中既有未提交代码也不是本项已交付前置能力；本次未修改该源码工作树。

此前证据提取由 `im_adapter_evidence` 协助，主代理直接核读关键 SDK 契约和源码后承担设计判断。这些工作不是独立设计评审；未运行 SDK、真实账号或 Pause／Resume 验证。

## 后续边界

设计已获用户批准并正式落位，独立评审尚未执行。A 公共接收／唤醒能力与 B 应用适配共同约束事件和回执，C 集成依赖 A、B 的实际交付；完整依赖和验收见正式设计。设计记录的后续分解方向为 `split`，应先完成父项独立评审，再在相应授权内分解，不在本次创建子项。

本项实施仓库、分支、匹配应用构建、镜像及编排位置尚未确定；无本项业务实现、源码合并、部署或真实集成验收结果。代码合并交付义务继续为 pending。项目记录推送不建立这些结果。

知识入口：[链路与能力分析](../../evidence/im-wakeup-paths-and-capabilities.md)、[飞书协议原理](../../evidence/feishu-event-transports.md)、[OpenClaw 接入机制](../../evidence/openclaw-feishu-im-mechanism.md)、[跨平台休眠调查](../../evidence/im-platform-sandbox-sleep.md)。
