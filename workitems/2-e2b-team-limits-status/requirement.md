# E2B 团队 limits/status 接口评估（不实施）

## 当前结论

用户于 2026-10-23 明确决定：「那结束了，这次两个接口全都不做，在 Issue 中评论回复，然后关掉」。本工作项结束设计探索并归档，`GET /teams/{teamID}/limits` 与 `GET /teams/{teamID}/status` 本次均不实施，继续保持未支持状态。

## 决策依据

- `status` 查询团队封禁／阻断状态；sandbox-manager 当前没有对应的团队管理能力，本次不引入这套能力或固定返回未阻断状态的接口。
- `limits` 的官方协议描述团队并发限制及单沙箱资源上限，而现有 `QuotaSpec` 按 API key 计量，CPU 和内存是多个沙箱的总额，无法直接映射为等价语义。
- Issue 指定的 [E2B OpenAPI](https://github.com/e2b-dev/E2B/blob/db8d80dad5be3d6a94c960e29017c8a9e29680c4/spec/openapi.yml) 要求全部 11 个限制字段为非空整数；省略字段或返回 `null` 不满足该协议，协议也未定义 `-1` 代表未知。
- 现有每个 API key 的配额可通过 `GET /api-keys` 的 `quota` 字段查询。

## 处理结果

已在 [Issue #1115 的评论](https://github.com/openkruise/agents/issues/1115#issuecomment-6359584828) 中说明两个接口均不实施及原因，并于 2026-10-23 核验 Issue 已以 `not_planned` 关闭。

本次没有接口实现、测试或源码交付；Issue 关闭代表暂不实施的决定。当前没有待完成的设计审批、实现验收或交付义务。未来如有明确客户端需求及相应团队级能力，再重新评估。
