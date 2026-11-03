# 当前上下文

`2-feishu-wake-openclaw` 当前标题为“基于 Webhook 事件的 Sandbox 自动唤醒”。保留稳定 ID，范围收敛到 HTTP Webhook 入口；WebSocket 入口由同级 `3-websocket-wakeup` 承接。

用户明确两种方式都要、能力需要通用化，并要求先研究飞书原理、再保存链路分析并拆为两个并列需求。飞书与 OpenClaw 是首个场景。

用户于 2026-11-03 启动本项设计，并进一步明确“可靠接收”无需强可靠：采用 Gateway 内存接收，Gateway 退出导致事件丢失可以接受。此前持久化及跨进程恢复方向已被替代。当前继续细化设计，无正式 spec、独立审查、实施代码或运行验证。

用户此前回复“都按照推荐来”，确认每个接入绑定一个已有 Sandbox，应用内部负责用户/群聊路由；自动唤醒开关开启时，手动 Pause 也可唤醒，持续保持暂停需关闭开关。两项无需再次确认。

## 当前下线核验

按用户要求，仅以实际 ack-components 的 Gateway 编排为配置依据，并匹配其镜像源码；没有使用 Agents 示例编排推断部署行为。主检出已刷新，组件与源码原文、渲染结果及分析见 [ACK Gateway 下线证据](../../evidence/ack-gateway-webhook-shutdown.md)。

默认 drain=30 秒、preStop 调用 drain 后 sleep 30 秒、Pod 总 grace=90 秒。对应 Envoy 1.37.3 的 graceful drain 期间仍可接收连接；Gateway 退出代码只清理 peer/system 服务，没有跟踪已 ACK 的后台内存任务。即使每次唤醒固定 10 秒，也不能由当前机制推出“所有事件必然完成”。若要在正常下线排空这类任务，设计需增加进程级事件归属、停止接收及等待任务完成的衔接；不需要因此引入持久存储。未修改编排或业务源码，未进行线上 Pod 终止实验。

## 交付链路证据

本轮核对 OpenClaw 固定源码提交 `0a0d601bf12dfea5e4c94c3e8cd6d823c405d9a0`，该快照不代表实际部署版本：

- [Webhook 入口](https://github.com/openclaw/openclaw/blob/0a0d601bf12dfea5e4c94c3e8cd6d823c405d9a0/extensions/feishu/src/monitor.transport.ts)：以原始请求体验签，签名时间戳允许与本地时钟相差一小时；持久化接收成功时返回 `x-openclaw-delivery-accepted: durable`，challenge 的普通 200 不带该标记。
- [持久化入口](https://github.com/openclaw/openclaw/blob/0a0d601bf12dfea5e4c94c3e8cd6d823c405d9a0/extensions/feishu/src/feishu-ingress.ts)：等待 `monitor.admit` 后才报告 durable；所查 Feishu 接线中未发现供外部接收器提交已认证事件的专用 HTTP 接口。
- [消息发送](https://github.com/openclaw/openclaw/blob/0a0d601bf12dfea5e4c94c3e8cd6d823c405d9a0/extensions/feishu/src/message-send.ts)：OpenClaw 在独立出站请求中调用 `im.message.reply` 或 `im.message.create`，Webhook 确认与最终回复是不同结果。

因此，延迟交付不能假定旧签名永远有效；应用持久化接收可作为交付完成判据的候选，但仍须确定实际目标版本和交付鉴权方式。已完成源码与官方文档核对，未进行真实消息、Pause/Resume 或端到端验证。

进一步核对同一 OpenClaw 提交：

- [队列保留默认值](https://github.com/openclaw/openclaw/blob/0a0d601bf12dfea5e4c94c3e8cd6d823c405d9a0/src/channels/message/ingress-monitor.ts#L44-L51) 为 completed/failed 各 30 天、各最多 20,000 条；数量限制可能先于时间上限清除记录。Feishu 使用该 standard 策略。
- [重复事件入队](https://github.com/openclaw/openclaw/blob/0a0d601bf12dfea5e4c94c3e8cd6d823c405d9a0/src/channels/message/ingress-queue.ts#L348-L376) 对仍存在的 pending、claimed、completed、failed 记录均返回 duplicate；[admission](https://github.com/openclaw/openclaw/blob/0a0d601bf12dfea5e4c94c3e8cd6d823c405d9a0/src/channels/message/ingress-monitor-admission.ts#L197-L225) 将其视为 durable。因此 durable 仅表示应用接收责任，包含已进入失败终态的同 ID 事件，不证明业务执行或回复成功；响应丢失后的重投可复用尚存记录，但不能推出无限期业务恰好一次。

另以 Node 内置 crypto 和虚构密钥执行了与所读验签公式一致的最小断言：两小时前的原签名因时间窗失效；保持原始 body 和事件 ID、使用当前时间戳与新 nonce 重签后通过；修改 body 则验签失败。该结果仅证明重签公式可行，未运行完整 SDK、真实 Webhook 或部署集成；是否采用可信中继重签仍需确认。

## 先前存储调查的适用边界

只读调查使用工作项 1 隔离工作树的固定提交 `cfbd102bc05c6df663965c5e23463a0eafd34948`，通过 `git show` 排除其中无关的未提交改动；该提交只作能力参考，不是本项已选实现基线。

- `pkg/servers/e2b/keys/interface.go`、`mysql.go`、`factory.go`：MySQL/GORM 后端持久化团队及 API Key，接口是 KeyStorage，默认后端是 Kubernetes Secret；没有通用事件接收接口。
- `pkg/sandbox-manager/quota/redis.go`、`antidrift.go`：Redis 用于动态配额记账，校正队列是进程内 workqueue 与 pendingEvents Map，不能恢复逐条 Webhook 消息。
- 当前证据没有可直接复用的可靠 Webhook 队列。用户当前已选择内存接收，此调查不再构成引入持久存储的理由。

## 待决范围

- 固定目标的身份与配置变更规则，以及关闭自动唤醒时新事件和积压事件的处理。
- 内存容量、满载处理、短时重试、去重及正常下线排空规则，以及交付完成和应用业务执行的边界。
- 首期事件范围、凭据与目标配置，以及 Gateway 内部的接收/任务生命周期归属。

知识入口：[链路与能力分析](../../evidence/im-wakeup-paths-and-capabilities.md)、[飞书协议原理](../../evidence/feishu-event-transports.md)、[OpenClaw 接入机制](../../evidence/openclaw-feishu-im-mechanism.md)。
