# 当前上下文

- 来源：https://github.com/openkruise/agents/issues/1115，标题为 `[feature request] Implement E2B team limits and status endpoints`。
- 2026-10-23 读取 Issue 正文及评论时为 open、无评论。用户已确认需要解决，并授权开始需求 2 的设计。
- 当前范围：用户在了解 `status` 用于团队封禁／阻断查询后，明确决定「这个接口我们先不支持」。本工作项仅推进 `GET /teams/{teamID}/limits`，`status` 暂不支持，不属于本次验收或交付范围；这不表示整个 Issue 已解决。
- 已核验协议为 https://github.com/e2b-dev/E2B/blob/db8d80dad5be3d6a94c960e29017c8a9e29680c4/spec/openapi.yml；`TeamLimitsResponse.limits` 的 11 个 int64 字段均必填，协议未定义未知值哨兵。
- 设计调查使用已 fetch 的社区提交 `09f1d7f1857a8c3c16f1c0069a0d7f9c6df14161`。其 `pkg/servers/e2b/routes.go` 尚未注册 limits；这是源码检查结论，未运行接口或部署环境复现。
- 已核验现有团队身份规则：`Team.Name` 用于团队鉴权和 namespace，`Team.ID` 是兼容／展示元数据；`keys.listedTeam` 将 UUID 输出为 `GET /teams` 的 `teamID`。UUID 地址解析与现行 `pkg/servers/e2b/AGENTS.md` 的查找限制存在需要用户决定的契约差异。
- 已核验现有配额规则：`QuotaSpec` 按 API key 计量；CPU、内存维度是该 key 多个沙箱的总额，不能直接等同官方团队或单沙箱上限。依据为 `pkg/servers/e2b/create.go`、`pkg/sandbox-manager/api.go`、`quota/spec/model.go` 和 `docs/specs/2026-06-17-api-key-sandbox-quota-redis.md`。全局 timeout 配置约束单次输入，存在续期和 never-timeout，不能直接宣称为团队沙箱的总寿命上限。
- 待决定：limits 的团队路径标识、缺失／跨团队语义，以及无法准确映射字段的表示方式。此前提出的 UUID 地址别名及 `-1` 扩展都未获用户批准；移除 status 不代表批准这两项。用户希望逐项展开讨论。
- 当前仍在设计讨论；尚无正式设计批准、独立审查、实现、测试或交付证据。实现基线、工作树及 E2E 环境尚未建立；不预设工作项依赖。

