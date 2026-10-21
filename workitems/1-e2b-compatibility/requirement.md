# E2B 兼容性

## 目标与项目约束

管理 OKA 的 E2B 兼容性问题；每个问题先记录现象与证据，与用户讨论解决必要性，经用户确认后再进入设计。此约束适用于本总项及后续子项；未确认的问题保持待讨论，不把项目创建或差异存在当成批准。

## 本轮已确认范围

2026-10-20，用户要求「解决上游 #1083 #1084 #1085 三个 Issue」。核对最新上游后已讨论三项的必要性：合法列表请求返回错误空集，以及暂停/快照返回成功但未遵守请求语义，均需修复。

同日用户先选择“最小修复”，随后逐项明确了扩展后的当前范围：Pause 本轮暂时禁止指定 memory，任何显式 `memory` 都返回 400；Snapshot 的 body `memory` 绑定到本次持久化内容（`true` 等价 memory+filesystem，`false` 等价 filesystem，持久化内容扩展头优先）；本版本支持快照 `name`（Checkpoint label 存储、Infra 侧格式校验、同名替换、列表按 name 过滤），`names` 始终为数组。

2026-10-21，用户确认两项补充决定：同名替换必须在新快照创建成功后再删除旧快照，任何替换失败都不得丢失既有快照；Pause 必须拒绝首个 JSON 对象之后仍有内容的请求体，避免显式 memory 请求被静默忽略。

### #1083：Sandbox 列表筛选与排序

来源：https://github.com/openkruise/agents/issues/1083

修复 `GET /v2/sandboxes` 将 `order`、`template`、`startedAfter` 当作 metadata 的错误。按模板 ID 或现有别名筛选；按 RFC3339 时间筛选在给定时刻及之后启动的 Sandbox；支持 `asc`/`desc` 且默认 `desc`；分页游标与排序方向一致；不支持的参数值返回 400。保留相关既有 metadata 与其他列表功能。查询参数按单值解析，空值或重复值返回 400。

### #1084：Pause memory

来源：https://github.com/openkruise/agents/issues/1084

读取 `POST /sandboxes/{sandboxID}/pause` 的可选请求体。无请求体、空白、`null` 或 `{}` 保留现有暂停流程；任何显式 `memory`（`true` 或 `false`）返回 400 并说明本轮不支持单次 memory 选择。非法 JSON、非对象请求体或对象之后的尾随内容返回 400，且不触发暂停或任何写入。不以修改 Sandbox 持久化策略模拟单次模式。

### #1085：Snapshot 参数与响应

来源：https://github.com/openkruise/agents/issues/1085

复用既有 checkpoint 能力支持 filesystem-only 快照：`memory:false` 仅保存文件系统，`memory:true` 保存 memory+filesystem，body `memory` 与持久化内容扩展头同时出现时以扩展头为准。创建和列表响应的 `names` 始终为数组，至少为 `[]`。

本版本支持创建请求的 `name` 与列表的 `name` 查询：`name` 作为 Checkpoint label 别名存储，格式由 Infra 按其存储约束校验并以 400 拒绝非法值；同名创建采用替换语义，旧 Succeeded 快照只在新快照创建成功之后删除，创建失败时保留旧快照；列表按 name 过滤时保持 user 级可见性并返回最新一条。不引入 tag/build 版本体系。

## 验收条件

- 三个新列表参数不进入 metadata；筛选取交集、时间边界包含等号、默认降序与显式升序可观察，连续分页不因相同启动时间遗漏或重复对象；新增与既有分页参数的空值/重复值返回 400。
- Pause 的 `memory:true` 与 `memory:false` 都无副作用地返回 400；省略、`{}`、空 body 保持既有行为；带尾随内容的请求体返回 400 且不暂停。
- `memory:false` 快照仅保存文件系统，`memory:true` 保存 memory+filesystem，有效持久化内容扩展头优先于 body，均不修改源 Sandbox 的长期策略。
- 合法 `name` 创建返回 `names:[name]`；同名旧 Succeeded 快照在新快照成功后被删除；新快照创建失败或 name 非法时旧快照保留；`GET /snapshots?name=` 按 user 可见范围返回最新一条。
- 创建与列表的 `names` 是 JSON 数组而非 `null`；参数错误属于客户端错误；既有认证、资源归属、租户可见性、共享分页的其他调用和相关生命周期行为不退化。
- 请求字段、边界和兼容限制的完整候选见 `spec.md`；完整设计仍以当前审批版本为准。

## 证据与交付边界

三个 Issue 于 2026-10-20 查询时均为 OPEN、无评论；其报告基线为 OpenKruise Agents `ee289a6b0410f64eb03a59ee20b18f8cc59ed3cd`、E2B OpenAPI `b52cd30c14bf7038ba5bfbd15456b1dabe567082` 及 e2b SDK 2.56.0。已在 `upstream/master@2b06e110327f52da85053730a531ec3b3b0d6a46` 及当前开发基线 `fd2bea7193d98c1d456fa6c43a2ae3e7e4f4fd48` 静态核对三项仍存在。

修复目标源码仓库为 `openkruise/agents`，已注册实现工作树 `worktrees/1-e2b-compatibility`，开发分支 `fix/e2b-1083-1085-261020`。项目记录发布不授权源码提交/推送、创建 PR 或关闭 Issue；具体交付记录以实际证据为准。
