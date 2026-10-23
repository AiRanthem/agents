# 当前上下文

- 来源：https://github.com/openkruise/agents/issues/1115，标题为 `[feature request] Implement E2B team limits and status endpoints`。
- 2026-10-23 通过 GitHub 连接器读取 Issue 正文及评论；当前为 open，无评论。Issue 报告缺少两个路由并导致客户端收到 404，此次尚未从源码或运行环境独立复现。
- 必要性结论：用户本轮明确要求解决该 Issue，按该原始指令记录为需要解决，无须重复索要同一确认。理由为补齐官方团队查询协议及消除调用方遇到的路由缺口。
- Issue 的协议参考：https://github.com/e2b-dev/E2B/blob/db8d80dad5be3d6a94c960e29017c8a9e29680c4/spec/openapi.yml；报告的 Agents 基线为 `6c50bb16d810a9bdf0c2363f0906c39338b4d85f`。这些是问题报告中的参考，尚未作为当前源码事实核验。
- 设计待确定：完整响应字段及必填性、QuotaSpec 与团队有效限制的关系、平台默认值与未支持字段的表达、团队标识和缺失团队判定、403/404 语义、是否存在封禁或阻断能力、实际开发基线及 E2E 环境。
- 本次为新需求登记；尚无设计候选、设计批准、独立审查、实现、测试或交付证据。与既有工作项不预设依赖，设计时依据实际调用链与基线确认。

