# 飞书入口配置输入与有限投递

2026-11-04。用户要求了解配置和授权所需信息，并确定按当前默认配置等待唤醒，之后指数退避最多重试五次，最终失败记日志放弃。本记录区分已确认投递责任、源码事实和待选择的配置方案；未新增真实凭据、API、源码或编排。

## 配置需要表达什么

| 输入 | 用途与归属 |
| --- | --- |
| 完整 E2B Webhook URL | 目标 Sandbox public ID、应用端口和事件路径；Gateway 解析 ID 后从已有路由取得对象 UID，不要求用户手工提供 UID。 |
| 飞书 App ID | 校验事件所属应用，并与获准访问的目标入口绑定；App ID 不是秘密。 |
| Verification Token | 飞书应用“事件与回调 → 加密策略”中的验证信息；用于对应协议校验及 URL challenge。只需配置秘密引用，不把值写入项目记录。 |
| Encrypt Key | 飞书协议层按加密策略使用；本项目所查 OpenClaw `0a0d601` 的 Webhook 模式要求同时配置 Encrypt Key 和 Verification Token，接入该实现时必须具备。Gateway 使用对应 Key 验签/解密检查，原始请求转交给应用；实际部署版本仍待核对。 |
| 显式启用及允许范围 | 只授权该应用向指定 Sandbox 的端口/路径投递，普通数据面认证继续按原规则；按订阅配置允许 IM 消息事件。 |
| 企业范围（按需） | 若同一个应用服务多个企业，需要明确允许的 tenant_key，避免仅凭共享应用身份跨企业投递；企业自建单租户场景可直接绑定对应企业。 |

飞书后台还需要选择向开发者服务器推送事件、填写该 HTTPS URL、完成 challenge，并订阅 `im.message.receive_v1` 及需要的消息权限。单聊、群内 @ 机器人和全群消息的权限不同，按实际需要选择；同步卡片操作不自动加入本项。

Gateway 不调用发送消息 API，入站验证不需要 App Secret。App ID/App Secret 继续由 OpenClaw 用于获取出站凭据和回复。依据：[飞书事件概述](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/event-subscription-guide/event-subscriptions)、[消息事件与权限](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1)、[官方验签与解密说明](https://open.feishu.cn/document/event-subscription-guide/callback-subscription/receive-and-handle-callbacks)。最后一个链接用于事件/回调共用的安全算法，不将同步 callback 的响应规则用于普通 IM 事件。

## 配置责任与入口关闭（部分已确认）

用户已确定由运维直接配置 Kubernetes，不调整 OpenClaw。当前建议由运维在 Sandbox 配置中显式启用飞书入口，写入 App ID、端口/路径以及同 namespace 的 Secret 引用；Gateway 从 Sandbox 外读取验证信息。这个配置把“飞书来源合法”和“允许访问这个目标”连接起来。具体字段/API 尚待收敛，不是当前已经存在的 CRD 字段；本项不以增加 E2B 配置 API 为前提。

用户已确定关闭 Webhook 入口只拒绝新事件：以 Gateway 观察到关闭配置为界，已登记并 ACK 的任务继续原有唤醒与有限投递，不因关闭入口而取消；正常下线的 60 秒截止及任务总期限仍有效。关闭入口不等于关闭全局自动唤醒，也不等于删除目标或修改授权绑定。后几种变化及它们与在途任务的交互仍需明确，不能沿用此前“关闭入口就取消旧任务”的建议。

本轮限定读取的 Gateway/ACK 插件配置中未找到可直接复用的飞书凭据引用。`api/v1alpha1/securityprofile_types.go:622-671` 的 `AuditWebhook` 是出站审计目标，header 值为普通模板字符串，不能据此认定已有入站飞书验证配置。

OpenClaw 已有 `channels.feishu` 配置，默认保存在 `~/.openclaw/openclaw.json`，敏感字段支持 SecretRef；详见 [OpenClaw 存储与配置](openclaw-feishu-im-mechanism.md#配置存储与复用)。依用户“不调整”的决定，保持其现有配置存储和部署方式，撤回要求两侧共用注入 Secret 的建议。可由运维在 Gateway 专用 Secret 中另行配置与飞书/OpenClaw 一致的 Verification Token 与 Encrypt Key；不是生成另一套密钥，也不包含 App Secret。此方式需要运维保持值一致，不建立自动从 OpenClaw 导出或同步配置的能力。实际部署是否已启用标准 Webhook 及拥有必要验证信息仍待联调核验。

## 应用场景、换绑与轮换的背景

应用类型不改变 E2B URL 定位一个 Sandbox 的机制。询问应用场景的目的，是明确是否需要额外限制消息所属企业；仅凭 App ID 不能一般性地认定只有一个企业使用它。飞书商店应用可由多个企业安装；如同一个应用服务企业 A/B，而目标只允许 A 的事件，就需要明确企业范围。若允许该应用的消息都进入同一 Sandbox，则这是应用级授权范围，不需要按企业分配 Sandbox。用户尚未选择企业范围，不能把“企业自建单企业”或“允许所有企业”当作已批准条件。官方依据：[应用类型与能力](https://open.feishu.cn/document/home/app-types-introduction/robots-web-applications-and-mini-programs)。

修改绑定指运维改动入口对应的 App ID、目标 Sandbox 或允许的端口/路径。例如消息已被接收且正在等待旧目标 A 恢复，随后入口切到 B，需要定义这条旧消息是否仍送 A；不应因重新读取最新配置而把已接收事件悄悄改投 B。Sandbox 改变意味着 E2B URL 也改变，不引入可随意重定向的通用注册表。仅关闭入口已有用户选择；换绑中的任务行为仍未选择。

密钥轮换指更换入站 Verification Token/Encrypt Key，例如管理员重置或主动替换；它不是每次唤醒时的操作，也不是 OpenClaw 获取/刷新出站访问令牌。由于转交保留原始签名和密文，Gateway、飞书与 OpenClaw 的相关配置需匹配；若 OpenClaw 已改用新 Key，仍在队列中的旧密文可能无法通过验证/解密。当前不调整 OpenClaw，不要求自动轮换或双 Key 无缝切换。可考虑由运维停收并等在途任务结束后再变更配置，这是用于简化首期的建议，尚未登记为用户决定。共同安全算法见 [飞书校验与解密](https://open.feishu.cn/document/event-subscription-guide/callback-subscription/receive-and-handle-callbacks)。

## Gateway 读取链路：现状与所需能力

2026-11-04 针对用户“Gateway 读取这些配置需要做些什么”补查。agents 主检出为 `c7f1bf56966940fbfe2a73cd48b9a52c2b17de66`，实际 ACK `main/v0.6.14-release.1` 的 Gateway 镜像对应源码 `e55d70c7fc7d603e8a585918919788edd0374e31`。ack-components 刷新至 `3ec66bb0a7b037844111c9db84668b327e06e16`，该组件目录相对此前 `02d1a5f3b1c7fe5478ea69e105eb9dddfada8934` 无差异；未读取集群现场或真实 Secret。

现有能力与缺口：

- Gateway 已有 Kubernetes 客户端、Sandbox informer 和路由缓存；`pkg/sandbox-gateway/controller/gateway_controller.go:116-182,203-221` 仅配置 Sandbox 缓存与事件处理，尚无飞书配置或 Secret informer。
- `pkg/peersecurity/load.go:31-37,87-100` 的 peer 凭据读取是启动时按名称直接 Get，不能视为已有业务 Secret 更新监听。
- 实际 Chart 的 `templates/sandbox-gateway.yaml:40` 使用独立 `-gateway` ServiceAccount，`templates/rbac.yaml:71-102` 未授予 Secret 权限。`templates/peer-rbac.yaml` 仅在可选 peer 开关开启时授予固定 namespace、指定名称的 Secret get；`values.yaml:25-26` 两个开关默认 false，`configs/default.yaml` 未覆盖。Manager 的 Secret 权限不会自动赋予 Gateway。
- `pkg/proxy/routes.go:39-43,69-80` 会将整个 `sandboxroute.Route` 序列化给 peer refresh。新增飞书密钥应保存在独立的进程内缓存，不加入这个同步对象或日志；路由只关联必要的非秘密配置与引用。

据此，建议新增以下能力，准确字段/API 与授权范围仍待收敛：

1. 由有权管理 Sandbox 的主体提交入口启用、App ID、允许的端口/路径和同 namespace 的专用 Secret 引用。配置保存在 Sandbox 外，暂停期间即可读取；不依赖访问 OpenClaw 进程或解析其任意 env/file/exec SecretRef。
2. 复用 Sandbox 监听解析入口绑定，补充引用 Secret 的同步与本地缓存，处理启动同步、更新、删除和引用变化。配置缺失、格式错误或尚未就绪时拒绝接收，不先 ACK 或触发恢复。更新以本实例观察到为界，不承诺各 Gateway 与 OpenClaw 原子切换。
3. 飞书请求按 E2B Host 定位目标后，使用缓存验证来源、应用身份和端口/路径授权，通过后才登记内存任务及返回事件 ACK；每条请求无需同步访问 Kubernetes API。URL challenge 按标准飞书协议单独处理。
4. 在实际 ACK 编排中为 Gateway 增加与所选读取方式匹配的 Secret 权限，并限制到需要的 namespace/对象。标准 RBAC 不能按 Secret 的 data 字段授权；缓存 label selector 也不是权限边界。若使用 resourceNames 限制 list/watch，客户端必须带匹配的 metadata.name field selector，不能直接用全量 informer。具体授权供给方式仍是配置设计的待定部分。
5. 保持 OpenClaw 现有配置方式，由运维维护 Gateway 验证信息与其一致；本项不改造 OpenClaw 配置注入或实现自动同步。若未来发生密钥变更，需要协调相关配置的生效；具体轮换方式仍未选择。

代码读取/缓存能力归子项 21；实际 ACK 的权限配置归子项 22，继续依赖代码与匹配镜像交付。本记录包含上述明确标注的用户决定、源码事实及剩余建议；未修改 API、源码、RBAC 或运行配置，未建立新的独立通过。

官方依据：[Secret 最小权限及读取后的保护](https://kubernetes.io/docs/concepts/security/secrets-good-practices/)、[RBAC resourceNames 与 list/watch 限制](https://kubernetes.io/docs/reference/access-authn-authz/rbac/#referring-to-resources)、[Secret 环境变量更新语义](https://kubernetes.io/docs/tasks/inject-data-application/distribute-credentials-secure/#define-container-environment-variables-using-secret-data)。

## 当前默认等待的实际含义

源码 agents `c7f1bf56966940fbfe2a73cd48b9a52c2b17de66` 与固定 Gateway 镜像源码 `e55d70c7fc7d603e8a585918919788edd0374e31` 的相关配置/等待逻辑一致：

- `pkg/sandbox-gateway/filter/config.go:84-100,159-165`：`wake-timeout-seconds` / `WakeTimeoutSeconds` 的二进制缺省和非正值 fallback 是 60 秒。
- 实际 ack-components `02d1a5f3b1c7fe5478ea69e105eb9dddfada8934`，`addons/ack-sandbox-manager/main/v0.6.14-release.1/charts/ack-sandbox-manager/values.yaml:374-381` 明确设置 `wakeTimeoutSeconds: 600`；`templates/_gateway-helpers.tpl:106-107` 将其输出为插件配置。`config_schema.json:504-514` 默认同样是 600，`configs/default.yaml` 未另行覆盖。因此该实际 Chart 默认等待为 **600 秒/10 分钟**，不是二进制缺省 60 秒。单个安装的覆盖值未读取。
- `filter.go:152-171` 在认证与可唤醒判断后创建等待 context。当前普通流量唤醒成功后复查 route Running 再转发（`:369-392`），失败返回错误；这不是应用事件接口已经可用的证明，恢复后暂不可接收由有限投递重试处理。
- 现有 `sandboxcr/sandbox.go:657-669` 在等待恰好耗尽 context 但成功时，会给 post-resume refresh 新建最多 30 秒 context。因此 600 秒是配置的等待预算，不应将旧代码当作整个新任务硬截止的证明。新内存任务仍须兑现自己的总截止及下线 60 秒截止；不延长终止预算。

## 本轮已确定的有限责任

沿用有效唤醒配置；唤醒等待失败或超时记日志结束。恢复后首次投递失败再指数退避，最多五次重试，即最多六次请求；HTTP 200 为成功，连接失败、超时/响应丢失或非 200 按失败处理。耗尽后记日志释放任务，不持久化或启动新一轮。响应丢失可能导致重复投递，沿用原事件 ID，由应用去重，不承诺恰好一次。

每次 HTTP 请求与退避有界。实现者选择有限默认参数，并从登记时设置不超过“有效唤醒预算 + 六次 HTTP 超时 + 五次退避”的总任务期限，排队/重试不刷新；进入下线时与首次停收后 60 秒取较早截止。日志只含事件标识、目标、次数与失败原因，不含凭据或完整正文。第二轮独立报告仍绑定旧提交 `5061001`，本轮新决定未被登记为独立通过。
