# 当前上下文

`2-feishu-wake-openclaw` 当前标题为“基于 Webhook 事件的 Sandbox 自动唤醒”。保留稳定 ID，范围收敛到 HTTP Webhook 入口；WebSocket 入口由同级 `3-websocket-wakeup` 承接。本项按用户要求成为汇总项，子任务 `21-webhook-gateway-code` 负责代码，`22-webhook-ack-orchestration` 负责 ACK 编排且依赖前者交付。整体契约与验收责任仍在本项。

用户早期要求两种方式都要、能力通用化；2026-11-04 明确本项是单独的飞书 IM Webhook 功能，采用标准飞书协议，OpenClaw 为目标应用场景。WebSocket 项不随此次澄清改变范围。

用户于 2026-11-03 启动本项设计，并进一步明确“可靠接收”无需强可靠：采用 Gateway 内存接收，Gateway 退出导致事件丢失可以接受。此前持久化及跨进程恢复方向已被替代。当前继续细化设计，无正式 spec、实施代码或运行验证；独立审查的实际结论见下节。

用户此前回复“都按照推荐来”，确认每个接入绑定一个已有 Sandbox，应用内部负责用户/群聊路由；自动唤醒开关开启时，手动 Pause 也可唤醒，持续保持暂停需关闭开关。两项无需再次确认。

## 独立设计审查

最新复审：用户要求“再次独立复审”后，原 reviewer `/root/webhook_design_reviewer` 独立评估提交 `5061001783fd3d9fd431c3e820f6862f7a5e4eb6`，未参与任何设计修订。[第二轮报告](records/design-review-20261104-r2.md) SHA-256 为 `ff935af58f61419fa14fd12d2fa1ed11524a39ef7880d7b626ceeb573c5cdfb9`。标准 HTTP 200、原始 body/签名头转交及 E2B URL 寻址已闭合；剩余 G1-R 是 ACK 后失败/响应丢失的有限处理责任，G2-R 是飞书入口配置/授权及启停变化语义。父项和 21 仍为 **Unable to conclude**，没有认定候选已选定错误实现；22 的编排契约继续 **Independent review passed**。保留正常下线、60/120 秒预算和交付依赖的原覆盖，新增现有适配器窄测试通过。未实施或开展真实集成验证，未写 implementable。

以下保留首轮原始审查事实及其目标：

2026-11-04，用户明确要求独立 reviewer。`/root/webhook_design_reviewer` 以 clean-context、指定 `gpt-6.1-sol / high` 审查项目提交 `27e8ae89472e3844104ec75a18182091e3088c12`，未参与设计编写或修订。原始 [审查报告](records/design-review-20261104.md) 原样保存，内容 SHA-256 为 `fcf599dc88564b5bb045a4e8b94d3f9943718912fd083a442c32051e56740600`。

父项和子项 21 均为 **Unable to conclude**，必要缺口为 G1（应用交付/有效接收确认及响应丢失后的责任）与 G2（接入配置、授权目标身份及变更/关闭开关后的处置）；不是已证明的代码缺陷。子项 22 的当前编排语义契约为 **Independent review passed**，仍依赖子项 21 的真实代码交付与匹配镜像。正常下线的并发边界、60 秒绝对截止、120 秒预算及子任务依赖未发现阻塞缺陷。

Reviewer 独立检查了固定版本 Gateway/OpenClaw/Envoy 原文、实际 ACK 组件，并重新 Helm 渲染现有包；未运行新功能、部署或改动候选设计。本轮仅登记审查事实，不写 implementable，不把局部覆盖变成完整链路通过。后续收敛 G1/G2 时复用仍有效的下线和编排覆盖，由独立 reviewer 复核变化及受影响范围。

## 飞书专用入口澄清

用户在独立审查后提出使用 E2B 数据面域名作为飞书请求地址，并明确标准飞书 IM 协议。源码核验确认 `https://<port>-<sandbox-id>.<e2b-domain>/<应用事件路径>` 可经已有 Host 解析与路由找到目标，不需要额外建设通用目标映射注册系统。前提是公网 DNS/HTTPS 入口实际通向 Gateway；本轮未执行现场连通或飞书配置验证。

域名不含数据面 token 或 Kubernetes UID。已有 token/JWT 门禁不会自动认可飞书签名；飞书专用入口需要在 Sandbox 外取得来源验证配置，并保留任务的对象身份约束。正常事件的标准 HTTP 200 可作为应用接收确认，不要求 OpenClaw 私有 durable 标记。第二轮独立复审确认 G1 的协议选择和 G2 的目标寻址已收敛，响应丢失后的有限处置、凭据配置与开关变化仍需细化。事实、源码版本与官方协议见 [入口核验](../../evidence/feishu-e2b-webhook-entry.md)。

## 当前下线核验

按用户要求，仅以实际 ack-components 的 Gateway 编排为配置依据，并匹配其镜像源码；没有使用 Agents 示例编排推断部署行为。主检出已刷新，组件与源码原文、渲染结果及分析见 [ACK Gateway 下线证据](../../evidence/ack-gateway-webhook-shutdown.md)。

默认 drain=30 秒、preStop 调用 drain 后 sleep 30 秒、Pod 总 grace=90 秒。对应 Envoy 1.37.3 的 graceful drain 期间仍可接收连接；Gateway 退出代码只清理 peer/system 服务，没有跟踪已 ACK 的后台内存任务。即使每次唤醒固定 10 秒，也不能由当前机制推出“所有事件必然完成”。用户已接受先停收、排空、再退出的方向，不需要因此引入持久存储。未修改编排或业务源码，未进行线上 Pod 终止实验。

用户于 2026-11-04 确认由 preStop 先调用只在 Pod 内可达的业务 drain 接口，关闭新事件接收并等待进程持有的排队与执行中事件，再进入现有 Envoy drain + sleep，最后发送 TERM。业务排空最多 60 秒，空队列立即结束；本地调用预算 65 秒，加现有 curl 最多 5 秒及 sleep 30 秒，preStop 预算最多约 100 秒，目标总 grace 调整为 120 秒以保留约 20 秒退出余量。现有 90 秒不能容纳这个完整上限。任务需要由进程持有，不能随 ACK 后的 stream 销毁取消；停收与任务登记必须形成同一个并发边界。

进入排空后 readiness 返回失败，但保留内部路由就绪状态、路由同步和 peer/outbound 等任务依赖，liveness 继续正常。新 Webhook 返回 503，不确认接收；应用按标准事件协议返回 HTTP 200 后，该事件才算成功交付，模型回答不在等待范围。具体事件终态和重试策略仍属于整个 Webhook 设计的待决范围。详见下线证据中的当前约定；数值和管理接口尚非已实现能力。

按用户明确要求先建立两个子任务，保留全部已确认契约和待决事项；仍没有完整父 spec 或父项独立通过可供继承，三个范围的实际审查结论分别记录。子任务 22 的当前编排契约已独立通过，实际编排变更仍须等待子任务 21 的真实代码交付证据，并在启用新 hook 前取得匹配的镜像与接口身份。不得将现有旧镜像与新 hook 拼装成交付物。

## 交付链路证据

本轮核对 OpenClaw 固定源码提交 `0a0d601bf12dfea5e4c94c3e8cd6d823c405d9a0`，该快照不代表实际部署版本：

- [Webhook 入口](https://github.com/openclaw/openclaw/blob/0a0d601bf12dfea5e4c94c3e8cd6d823c405d9a0/extensions/feishu/src/monitor.transport.ts)：以原始请求体验签，签名时间戳允许与本地时钟相差一小时；持久化接收成功时返回 `x-openclaw-delivery-accepted: durable`，challenge 的普通 200 不带该标记。
- [持久化入口](https://github.com/openclaw/openclaw/blob/0a0d601bf12dfea5e4c94c3e8cd6d823c405d9a0/extensions/feishu/src/feishu-ingress.ts)：等待 `monitor.admit` 后才报告 durable；所查 Feishu 接线中未发现供外部接收器提交已认证事件的专用 HTTP 接口。
- [消息发送](https://github.com/openclaw/openclaw/blob/0a0d601bf12dfea5e4c94c3e8cd6d823c405d9a0/extensions/feishu/src/message-send.ts)：OpenClaw 在独立出站请求中调用 `im.message.reply` 或 `im.message.create`，Webhook 确认与最终回复是不同结果。

因此，延迟交付不能假定旧签名永远有效。当前已选择标准飞书 HTTP 200 接收语义，私有 durable 标记仅保留为该 OpenClaw 快照的实现证据，不是本项协议要求；仍须核对实际目标版本的兼容性。未进行真实消息、Pause/Resume 或端到端验证。

进一步核对同一 OpenClaw 提交：

- [队列保留默认值](https://github.com/openclaw/openclaw/blob/0a0d601bf12dfea5e4c94c3e8cd6d823c405d9a0/src/channels/message/ingress-monitor.ts#L44-L51) 为 completed/failed 各 30 天、各最多 20,000 条；数量限制可能先于时间上限清除记录。Feishu 使用该 standard 策略。
- [重复事件入队](https://github.com/openclaw/openclaw/blob/0a0d601bf12dfea5e4c94c3e8cd6d823c405d9a0/src/channels/message/ingress-queue.ts#L348-L376) 对仍存在的 pending、claimed、completed、failed 记录均返回 duplicate；[admission](https://github.com/openclaw/openclaw/blob/0a0d601bf12dfea5e4c94c3e8cd6d823c405d9a0/src/channels/message/ingress-monitor-admission.ts#L197-L225) 将其视为 durable。因此 durable 仅表示应用接收责任，包含已进入失败终态的同 ID 事件，不证明业务执行或回复成功；响应丢失后的重投可复用尚存记录，但不能推出无限期业务恰好一次。

先前以 Node 内置 crypto 和虚构密钥执行过与所读验签公式一致的最小断言：两小时前的原签名因时间窗失效；保持原始 body 和事件 ID、使用当前时间戳与新 nonce 重签后通过；修改 body 则验签失败。该结果只说明公式，不是完整 SDK 或部署验证。当前方向保留原始 body 和签名头，可信中继重签未被采用为已批准契约。

## 先前存储调查的适用边界

只读调查使用工作项 1 隔离工作树的固定提交 `cfbd102bc05c6df663965c5e23463a0eafd34948`，通过 `git show` 排除其中无关的未提交改动；该提交只作能力参考，不是本项已选实现基线。

- `pkg/servers/e2b/keys/interface.go`、`mysql.go`、`factory.go`：MySQL/GORM 后端持久化团队及 API Key，接口是 KeyStorage，默认后端是 Kubernetes Secret；没有通用事件接收接口。
- `pkg/sandbox-manager/quota/redis.go`、`antidrift.go`：Redis 用于动态配额记账，校正队列是进程内 workqueue 与 pendingEvents Map，不能恢复逐条 Webhook 消息。
- 当前证据没有可直接复用的可靠 Webhook 队列。用户当前已选择内存接收，此调查不再构成引入持久存储的理由。

## 待决范围

- 飞书验证配置、固定目标的对象身份与配置变更规则，以及关闭自动唤醒时新事件和积压事件的处理；E2B Host 定位能力已有源码依据。
- 内存容量、满载处理、短时重试、去重及响应丢失后的责任。应用确认采用标准 HTTP 200；下线顺序与 60 秒业务等待上限已确认，不重复征询。
- 首期事件范围、凭据与目标配置，以及 Gateway 内部的接收/任务生命周期归属。

知识入口：[链路与能力分析](../../evidence/im-wakeup-paths-and-capabilities.md)、[飞书协议原理](../../evidence/feishu-event-transports.md)、[OpenClaw 接入机制](../../evidence/openclaw-feishu-im-mechanism.md)。
