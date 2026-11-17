# WebSocket 唤醒设计 v2 补充自审

日期：2026-11-17。结论：本次补充自审通过，按用户明确授权保持 `implementable`。这是作者参与的自审，不是新的独立设计 Pass；本次独立增量审查记为 `skipped_by_user`。

## 授权与输入

- 用户明确要求服务足够自包含、可插拔，以 Golang 包提供，通过 Builder 构造后调用 Start 即可独立运行，可放在单独容器、Gateway 容器、AdvancedTrafficManagement 等位置。
- 用户随后明确：“这部分你自审一下没问题就可以 implementable，不需要回到独立审查阶段”。原话及范围登记于 [decision.md](../decision.md)。这只调整本次补充的审查方式，不建立实现、合并、部署或运行验收。
- 比较基线：项目提交 `e50eba365e2493174dee1c1c46feffccfb64345c` 的设计 v1。v1 的 [独立报告](design-review-20261117.md) 原样保留，仍绑定其原目标与作者。
- 当前输入：[spec.md](../spec.md) v2，SHA-256 `e5c9963afe5db515ebf73d4b13f78d40a3f7aa647fc93e83f24c2e0123b5c183`。
- 自审者及本次补充落位者：Codex 主代理，会话 `01a1e84a-3acc-7e12-9870-7ff4bcdff90d`。本次服务形态由用户决定，当前主代理补入包／宿主责任及对应验收，累计作者信息已同步；不再作为该修订的独立审查者。

## 变更与自审结果

变更限定于服务包形态、Builder／Start 接入、宿主可迁移性、服务启停责任和对应 A/C 交付及包级验收。内部 HTTP 事件协议、账号映射、应用适配、授权、原目标身份、单活、消息确认、内存及失败边界没有变化。

1. **自包含与依赖边界相容。** Builder 接收配置及必要依赖，服务实例自主驱动连接、队列、恢复和交付，宿主只作装配及生命周期接入。自包含不等于取代 OKA 的目标授权／生命周期能力；原有 API、Manager、Infra 分层继续适用。包无需依附 Gateway 的私有启动顺序，因此可以被不同宿主调用。
2. **可迁移与单活相容。** 独立容器、Gateway、AdvancedTrafficManagement 是可选承载位置；多个宿主不能同时接管同一账号。迁移继续执行旧接收方停止后再启动新接收方，且宿主始终在目标 Pause 边界外。首期集成选择一个实际宿主，不因此扩大为同时交付所有宿主编排。
3. **Start 与停机语义相容。** 包管理自身连接和任务，宿主可请求停止，服务落实原停收／关连接／有限排空约定。没有将库级停止解释为退出整个宿主进程，也不要求宿主逐项驱动内部工作。具体 Go 方法签名及启动返回方式属于后续接口实现细化。
4. **Go 接收路径有原始源码可行性证据。** 本轮读取飞书官方 Go SDK 固定提交 `a3550335752a9af4662314e5838138562f04aa70`，不是直接将此前 Node SDK 证据当作 Go 实现。其 [生命周期](https://github.com/larksuite/oapi-sdk-go/blob/a3550335752a9af4662314e5838138562f04aa70/ws/client_lifecycle.go) 提供 `Start(context.Context)`、`Close` 和 `CloseAndWait`；[事件处理](https://github.com/larksuite/oapi-sdk-go/blob/a3550335752a9af4662314e5838138562f04aa70/ws/client_message.go) 在重组完整事件后调用 handler，按返回错误生成成功或失败确认；[dispatcher.Do](https://github.com/larksuite/oapi-sdk-go/blob/a3550335752a9af4662314e5838138562f04aa70/event/dispatcher/dispatcher.go#L322) 保留原始 payload 为 `EventReq.Body` 并把 handler 错误向上传递。因此准入后确认、原生事件交付与受控停止可在 Go 适配器中实现，不需引入必需的 Node 接收进程。
5. **验收仍覆盖真实边界。** A 增加包级构造／启动、停止与宿主解耦验收；C 在选定宿主执行原完整链路验收。原 v1 的应用接纳、回执丢失、身份重建和权限验证没有因宿主变化被放宽。

未发现本次补充的阻塞问题。v1 未改契约保留原报告证据；新增及受影响的宿主装配、生命周期、依赖和 SDK 假设由上述自审覆盖。本次登记 `implementable` 的依据是用户对审查方式的明确决定与实际自审结果，不是宣称 v2 获得了独立 Pass。

## 检查边界

已读取完整当前需求／设计／决策及变更 diff，并核对 Go SDK 原始源码。检查是设计一致性和静态可行性审查，未构建服务包、运行 SDK 测试、连接真实账号、部署候选宿主或执行 Pause／Resume。所查 SDK 提交用于证据定位，尚未选为实际依赖版本；实施时仍须在选定版本验证接纳失败的确认、原生载荷保留、停止资源释放及日志不泄露正文等既定契约。

代码实现、代码独立评审、交付和实际集成验收仍按各自授权及要求执行；本轮仅维护项目记录。

项目记录检查通过：YAML、v2／implementable／self-review pass／skipped_by_user 一致性、两处登记 SHA-256、六个既有契约章节逐字不变、v1 原报告逐字不变、11 份 Markdown 的围栏和 21 个本地链接，以及 `git diff --check`。
