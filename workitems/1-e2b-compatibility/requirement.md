# E2B 兼容性

## 目标与项目约束

管理 OKA 的 E2B 兼容性问题；每个问题先记录现象与证据，与用户讨论解决必要性，经用户确认后再进入设计。此约束适用于本总项及后续子项；未确认的问题保持待讨论，不把项目创建或差异存在当成批准。

## 本轮已确认范围

2026-10-20，用户要求「解决上游 #1083 #1084 #1085 三个 Issue」。核对最新上游后已讨论三项的必要性：合法列表请求返回错误空集，以及暂停/快照返回成功但未遵守请求语义，均需修复。

同日，用户在本会话关于“本轮对暂不支持的单次无内存暂停、命名快照采用明确 400，还是必须补齐完整能力？”的选择中明确回答“最小修复 (Recommended)”。据此确认三项均解决，但不扩展单次无内存暂停与命名版本能力。

### #1083：Sandbox 列表筛选与排序

来源：https://github.com/openkruise/agents/issues/1083

修复 `GET /v2/sandboxes` 将 `order`、`template`、`startedAfter` 当作 metadata 的错误。按模板 ID 或现有别名筛选；按 RFC3339 时间筛选在给定时刻及之后启动的 Sandbox；支持 `asc`/`desc` 且默认 `desc`；分页游标与排序方向一致；不支持的参数值返回 400。保留相关既有 metadata 与其他列表功能。

### #1084：Pause memory

来源：https://github.com/openkruise/agents/issues/1084

读取 `POST /sandboxes/{sandboxID}/pause` 的可选请求体。`memory:false` 明确返回 400，并说明单次 filesystem-only 暂停暂不支持；`memory:true` 或省略保留现有策略。不以修改 Sandbox 持久化策略模拟单次模式，不再静默忽略 false 并返回成功。

### #1085：Snapshot 参数与响应

来源：https://github.com/openkruise/agents/issues/1085

复用既有 checkpoint 能力支持 `memory:false` 的 filesystem-only 快照；创建和列表响应的 `names` 始终为数组，至少为 `[]`。本轮明确拒绝创建和列表请求的 `name` 参数并返回 400，不忽略名称查询而返回全集，也不增加别名/tag/同名版本体系。

## 验收条件

- 三个新列表参数不进入 metadata；筛选取交集、时间边界包含等号、默认降序与显式升序可观察，连续分页不因相同启动时间遗漏或重复对象。
- Pause 的 `memory:false` 无副作用地返回 400，省略/true 保持既有行为。
- filesystem-only 快照仅保存文件系统，不通过修改源 Sandbox 的长期策略实现。
- 创建/查询带 `name` 明确报错；合法创建及列表的 `names` 是 JSON 数组而非 `null`。
- 参数错误属于客户端错误；既有认证、资源归属、租户可见性、共享分页的其他调用和相关生命周期行为不退化。
- 请求字段、边界和兼容限制的完整候选见 `spec.md`；完整设计仍须批准及独立评审，范围确认不是对尚未展示细节的批准。

## 证据与交付边界

三个 Issue 于 2026-10-20 查询时均为 OPEN、无评论；其报告基线为 OpenKruise Agents `ee289a6b0410f64eb03a59ee20b18f8cc59ed3cd`、E2B OpenAPI `b52cd30c14bf7038ba5bfbd15456b1dabe567082` 及 e2b SDK 2.56.0。已在当前 `upstream/master@2b06e110327f52da85053730a531ec3b3b0d6a46` 静态核对三项仍存在。

本项为需求管理总项，保留问题、用户结论及当前设计。修复目标源码仓库为 `openkruise/agents`；项目当前尚未注册具体代码仓库与开发项，未建立实现工作树。代码实现须先满足当前审批、独立评审和所有权门禁。项目记录发布不授权源码提交/推送、创建 PR 或关闭 Issue；具体交付记录以实际证据为准。
