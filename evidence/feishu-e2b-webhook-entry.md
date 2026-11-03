# 飞书 IM Webhook 的 E2B 数据面入口

核验日期：2026-11-04。用户将工作项 2 明确为独立飞书 IM Webhook 功能，并询问能否把 E2B 数据面域名注册到飞书。本记录区分现有源码能力、协议事实与仍需实现的行为；未配置真实飞书应用、修改 Gateway 或执行端到端验证。

## 入口与目标定位

可采用完整请求地址 `https://<port>-<sandbox-id>.<e2b-domain>/<应用事件路径>`。前提是该域名的公网 DNS、HTTPS 和入口转发均指向 Sandbox 外的 Gateway。裸基础域名没有携带目标 ID 与端口，不能直接替代完整地址。

源码依据为 agents develop `c7f1bf56966940fbfe2a73cd48b9a52c2b17de66`；对应已核验 ACK 镜像源码 `e55d70c7fc7d603e8a585918919788edd0374e31` 的相关 Host 格式、解析、路由与认证行为相同：

- `pkg/servers/e2b/adapters/native_e2b.go:68-120,134-136`：标准 Host 可提取 public Sandbox ID 和端口，无需飞书额外提供 E2B 路由头；地址生成格式为 `<port>-<sandboxID>.<domain>`。该解析只匹配 Host 前缀，不以域名后缀证明来源授权。
- `pkg/sandbox-gateway/filter/filter.go:133-149`：按 ID 查询已有路由，并在处理暂停或唤醒前认证。
- `pkg/sandboxroute/route.go:32-45,89-123`：已有路由保存 ID、namespace/name、UID 和 owner。因此无需仅为该地址再建立一套通用 endpoint-to-Sandbox 映射系统。

## 域名不能替代认证或对象身份

- `pkg/servers/e2b/sandbox.go:119-130`：Domain、EnvdAccessToken、TrafficAccessToken 是分别返回的字段，token 不包含在域名中。
- `pkg/sandbox-gateway/filter/filter.go:211-287`：目标要求 traffic JWT 时，缺少有效 token 返回 403（认证能力不可用时 503）；否则启用传统 EnableAuth 且路由带 AccessToken 时，缺少正确 `x-access-token` 返回 401。标准飞书事件请求的签名和 Verification Token 不会自动变成这些 E2B 凭证。未启用相应门禁时则没有此项阻断，不能据此推断任何具体部署已经放行。
- `pkg/sandboxid/sandboxid.go:93-104`：public ID 取标签或 `namespace--name`，不是 Kubernetes UID；同名重建可能复用 legacy ID。`filter.go:302-345` 已有唤醒前 UID fence，可复用其身份约束，但异步任务仍需绑定接收时的对象身份，不能投递到同名重建对象。

设计收敛方向是仅在显式启用的飞书入口范围内使用飞书来源验证，再登记内存任务并触发唤醒；其他数据面访问继续遵守已有认证。Gateway 在 Sandbox 暂停时也必须能取得验证配置。凭据配置载体、启停/更新规则和排队期间的重新校验仍待完整设计确定。使用 E2B 域名解决寻址，不自动完成这些契约。

## 标准飞书协议与交付完成

[飞书事件订阅官方说明](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/event-subscription-guide/event-subscriptions)规定，事件通过 HTTP POST 发往开发者地址，普通事件应在 3 秒内返回 HTTP 200；超时或失败存在有限重投。URL 校验的 challenge 是独立协议请求。

按用户指定的标准飞书协议及已批准内存接收边界，可将普通事件链路收敛为：飞书 POST → Gateway 验证并登记内存 → HTTP 200 确认飞书 → 异步唤醒 → 向应用的标准事件接收路径转交原始 body 与相关签名头 → 应用 HTTP 200 确认接收。该确认不证明模型回答完成、持久化或业务恰好一次，不要求 OpenClaw 私有 durable 响应头。应用仍须实际符合标准事件接收语义；不能把 challenge 或错误路由的任意 200 算作事件交付。

正常下线继续采用已批准的 60 秒业务排空，等待至应用接收确认。应用之后主动调用飞书消息 API 回复用户，不通过 Webhook HTTP 响应返回模型答案。延迟转交仍受目标应用签名时间窗约束；响应丢失后的重投、内存去重和总任务存活上限需共同收敛。

## 对前次审查的影响

G1 的接收协议选择收敛为标准 HTTP 200，不再要求选择私有 durable 确认；仍需明确失败及响应丢失的处理。G2 的目标定位可复用 E2B Host 和既有路由，剩余问题集中在飞书验证配置、对象身份与开关/配置变化语义。原始审查针对提交 `27e8ae8`，保持不变；本轮澄清尚未获得增量独立通过，不建立完整设计或交付事实。
