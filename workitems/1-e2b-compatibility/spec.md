# E2B #1083、#1084、#1085 兼容修复

当前业务设计为 v7。2026-11-10，用户在 receiving-code-review 中明确回复「同意」，批准保留旧快照 ID、稳定错误文本、新游标方向校验与历史 token 兼容，以及 template 参数拒绝 tag、去空白和转小写；2026-11-11，用户在本会话审查未提交变更后选择「保留现在的做法」，批准省略 `order` 时沿用 `nextToken` 携带的排序方向，v6 中「省略 `order` 按默认降序校验」据此失效。独立评审状态为 review-pending；本次批准不替代独立评审。

## Why：消除合法请求的错误结果与静默语义偏差

三项问题均影响官方 E2B SDK 的正常调用：列表查询可能错误返回空集，暂停/快照可能保存了调用者要求排除的内存，命名查询可能返回未经筛选的全集。对无法履行的请求必须明确拒绝，不能返回误导性的成功。

用户已确认三项均需修复，并在后续会话中逐项确认了当前范围：完整修复 Sandbox 列表；Pause 暂时不支持单次 memory 选择，任何显式 `memory` 都返回 400；Snapshot 通过 body `memory` 或持久化内容扩展头选择内容，支持命名快照且保留各次创建的 ID，`names` 始终为数组。快照名称解析与对象保留分别处理，后续同名创建不会删除旧对象。

## 基线与边界

- 源码基线：`openkruise/agents` 的 `upstream/master@fd2bea7193d98c1d456fa6c43a2ae3e7e4f4fd48`。原设计点名的 `2b06e110` 与该基线之间 `pkg/servers/e2b`、分页与 checkpoint 相关路径无变化，设计适用性已单独评估。
- 协议依据：E2B OpenAPI `b52cd30c14bf7038ba5bfbd15456b1dabe567082`；问题中的 SDK 为 e2b 2.56.0。
- 本轮修正的评估目标为 PR #1103 head `e2dd1348883435758c12315b55e43f89f1b0344f`，PR 比较基线为 `0179aad20a43aad1fa6627c2a818372eb4e3f202`。实际本地工作树身份及组合目标验证见 `context.md`；原始开发基线继续保留其历史来源。
- E2B API 层负责参数、验证、错误与返回形状；快照名称解析留在 API 层。存储格式限制（如 label value 规则）由其 Infra 实现入口校验并返回领域错误，API 层负责状态码与稳定协议消息的映射。
- 既有认证、租户可见性、资源归属、Sandbox ID、资源查找错误、暂停保留期限、快照超时/清理语义保持不变。原生与定制路由的同一操作行为一致。
- 设计描述不构成源码实施授权；源码工作按用户授权范围与主工作区业务约束执行，实际评审与验收分别记录。

## #1083：Sandbox 列表

`GET /v2/sandboxes` 将 `order`、`template`、`startedAfter` 识别为独立保留参数，不再作为 metadata 键。

| 输入 | 可观察行为 |
| --- | --- |
| 省略 `order` | 首屏（无 `nextToken`）按启动时间降序，新 Sandbox 在前；携带新 stable cursor 时沿用 token 中的排序方向，token 无方向（历史裸排序键或不含方向的 stable cursor）时仍按降序。 |
| `order=asc` / `order=desc` | 按指定方向排序；空值或其他值返回 400。 |
| `template=<ID或别名>` | 查询值先去除首尾空白并转为小写，再与 Sandbox 解析出的模板身份（中性 Infra 的 `GetTemplate()`）精确匹配，和其他条件取交集；合法但不存在的模板得到空数组。包含 `:` 的 tag 形式以及归一化后为空的值返回 400。当前服务将 SandboxSet 名称同时作为模板 ID 与别名，不引入新的别名注册体系；API 层不叠加池名等其他标签匹配。 |
| `startedAfter=<RFC3339时间>` | 仅返回启动时间大于或等于给定时刻的 Sandbox；支持合法时区偏移及小数秒，按时间点而非字符串比较；空值或无效格式返回 400。 |

查询参数按单值解析：`order`、`template`、`startedAfter` 以及既有的 `limit`、`nextToken` 在空值或重复提供时返回 400，避免同一请求出现多个互相冲突的语义。`state` 与 `metadata` 沿用既有解析方式（`state` 逗号分隔、`metadata` 组合键），未知参数仍按 metadata 处理。显式 `metadata` 内名为 `order`、`template` 或 `startedAfter` 的普通业务键仍按 metadata 处理，不与顶层保留参数混淆。

启动时间使用现有 Sandbox 领取时间，与 `startedAt` 的数据来源一致，而不是 Pod/CR 创建时间。缺失或无法解析启动时间的对象不参与时间有序列表（排序键为空的对象被分页器过滤），不伪造当前时间或零时间。排序键输出为固定宽度 UTC 纳秒串，字典序等于时间序。

排序和游标使用同一时间顺序；同一启动时刻按稳定的 Sandbox ID 决定次序。相同查询与方向、数据集未变化时，连续翻页不得丢失或重复同一时刻的对象；最后一页不返回下一页 token，空列表返回 `[]`。筛选先于分页。

`nextToken` 是不透明的续页位置：新 stable cursor 编码排序键、唯一键与排序方向；显式 `order` 与 token 携带的方向不一致时返回 400；省略 `order` 时以 token 携带的方向作为本次请求的有效方向，不按默认降序拒绝。理由是裸 HTTP 客户端与手工 `Sandbox.list(next_token=...)` 常不重发 `order`，只跳过校验会让相反方向的请求静默返回已经翻过的页。历史裸排序键和不含方向的 stable cursor 继续可读，按当前请求方向解释，不补猜历史方向。因此历史 token 不能检测跨方向误用，也不承诺跨排序/筛选变更或跨版本恢复一次旧遍历。并发增删下沿用既有非快照式分页，不保证跨请求数据集冻结。

共享分页能力的其他调用者保持既有默认升序，特别是快照列表不因 Sandbox 默认降序而被反转。

模板身份存在两项已接受限制，均源自既有 Sandbox 标签写入方，不在本轮修复：

- SandboxSet 使用 `spec.templateRef` 时，其 Sandbox 的模板标签是被引用的 SandboxTemplate 名，而模板列表的 ID 与别名是 SandboxSet 名，因此 `template=<SandboxSet 名>` 对该池返回空数组。该身份不一致属 SandboxSet 侧问题，另提上游 Issue 跟踪。
- 由快照恢复的 Sandbox，其模板身份是内部 Checkpoint/SandboxTemplate 名，因此 `template=<snapshotID 或别名>` 返回空数组。

## #1084：Pause 请求

`POST /sandboxes/{sandboxID}/pause` 读取可选请求体，且请求体整体必须为空或恰好一个 JSON 对象：

- 无请求体、仅空白、字面量 `null` 或 `{}`：保留现有暂停流程。
- 任意显式 `memory`（`true` 或 `false`）：返回 400，消息为 `Pause with memory selection is not supported`。本轮不支持单次暂停模式，即使该值与模板既有策略一致也一致拒绝，不按隐含策略伪装成支持。
- `memory` 为 `null`：视为未指定。其他非布尔值属于解析错误。
- 非法 JSON、非对象请求体或对象之后的尾随内容（第二个 JSON 值、垃圾字节）返回 400。
- 请求体按流式方式解析：在首个 JSON 对象之后必须只剩空白，避免 `{} {"memory":false}` 之类的请求被当作“未指定 memory”而静默执行。

无效或不支持的请求不得触发暂停、写入 timeout/annotation 或改变持久化策略；解析在取得 Sandbox 并完成归属校验之后执行，因此 400 可以携带既有资源上下文，而 404/鉴权失败仍先于体解析返回。成功仍为 204，既有 404/409/500 分类保持不变。

明确保留的限制是：本轮不实现单次暂停模式，不改 controller 生命周期策略，也不改变 connect/resume 的恢复模式。

## #1085：Snapshot 请求与响应

### 创建与 memory

`POST /sandboxes/{sandboxID}/snapshots` 要求请求体存在且可解码为一个 JSON 对象：缺失、非法 JSON、非对象返回 400，而不是服务器错误。尾随多余内容不在本轮新增拒绝范围。

- `memory:true`：等价于持久化内容 `memory,filesystem`。
- `memory:false`：等价于持久化内容 `filesystem`，不包含 `memory`；复用现有 checkpoint 的 filesystem-only 创建及恢复路径。
- 省略 `memory`：不修改持久化内容；扩展头没有有效内容时继续继承 Sandbox 持久化策略。省略不隐式补成 true，也不擅自改成 false。

`x-e2b-kruise-snapshot-persistent-contents` 是请求级内容选择入口：解析时去除项两侧空白，多个头值按首次出现顺序合并并去重，空白值或解析为空集合的值不构成覆盖；含非法内容的头返回 400。

body `memory` 与有效扩展头同时出现时，扩展头优先：只要头解析出非空内容集合，就忽略 body，不因 body 与头不同而拒绝，也不让 body 覆盖头。

| 创建输入 | 结果（其他条件合法时） |
| --- | --- |
| `{"memory":true}`，无内容头 | 持久化内容 memory+filesystem。 |
| `{"memory":false}`，无内容头 | 持久化内容仅 filesystem；成功为 201。 |
| body 省略 memory，无有效内容头 | 原有源策略继承路径及真实后端结果不变。 |
| body 任意 memory，`filesystem` 头 | 持久化内容仅 filesystem（头优先）。 |
| body 任意 memory，`memory` 或含 memory 的头 | 持久化内容按头解析结果，可能包含 memory。 |
| memory 为 `null` | 视为未指定，按头或源策略处理。 |
| memory 为字符串、数字或其他非布尔值 | 参数类型错误 400，不当作省略。 |

内容选择只作用于本次 checkpoint，不修改源 Sandbox 的长期策略或模板。源 Sandbox 默认继续运行；显式使用既有 `snapshot-keep-running` 扩展头的调用继续遵守该头的既有语义。filesystem-only 快照不包含运行进程、内存状态或连接的恢复承诺，基于它创建的 Sandbox 按现有 filesystem-only 路径从磁盘重新启动；不扩大可保存的文件系统范围或新增存储能力。

通过校验的请求继续沿用既有 TTL、同步等待、取消、失败清理和成功返回条件；不能将后端失败包装成成功。

### 命名快照 name

创建 JSON 的 `name` 是本版本支持的快照别名：

- `name` 为 `null` 或空串视为未命名；非空时作为别名写入 Checkpoint label `agents.kruise.io/checkpoint-alias`（Infra 的中性 `Alias` 概念，不进入 Checkpoint CRD spec）。
- 别名格式属于存储限制：`sandboxcr.CreateCheckpoint` 入口按 Kubernetes label value 规则校验，非法时返回领域错误 `ErrorBadRequest`，API 层保留 400 映射并返回稳定的 `Invalid snapshot name`；原始后端错误只写内部日志。其他 checkpoint 创建失败仍保留既有状态分类，对外使用稳定的 `Failed to create snapshot`。API 层不做格式校验，未来其他 Infra 后端可放宽。
- 别名查询的作用域是「同一 owner（API key）+ team namespace」。同一 owner 可保留多个同名 Succeeded checkpoint，按 name 查询只返回最新可见的一条；其他 owner 的同名对象不可见。每次创建返回本次创建的 ID，不以另一个并发请求的 ID 替换。
- 恢复链路按 namespace 与 checkpointID 查找 Checkpoint，不受别名查询影响；显式删除继续遵循既有 owner 校验。

命名创建直接调用既有 `CreateCheckpoint`，成功后返回本次 `snapshotID`。创建阶段不列举同名对象或执行别名清理，失败（含别名非法、后端失败、等待超时）也不会删除既有快照。已返回的 ID 不因后续同名创建而失效；显式删除、TTL 和其他既有生命周期清理仍可使其失效。

名称查询依赖 Checkpoint 的创建时间：创建时把本地时钟以 RFC3339 纳秒精度写入 annotation `agents.kruise.io/checkpoint-creation-timestamp`，`AsCheckpointInfo` 输出固定宽度 UTC 纳秒时间戳，字典序等于时间序；存量对象缺失该 annotation 时回退到秒级 `metadata.creationTimestamp`。同一时间用对象名打破平局。跨副本时钟偏差或创建延迟可能使排序与真实完成先后不一致。

known-limit: 名称查询只读取本副本 informer 可见的 Succeeded 集合，因此在 watch 滞后期间，各副本可能返回不同的最新对象；历史快照持续占用存储，直到显式删除或既有生命周期清理。若未来需要线性一致的别名解析，应单独设计带版本校验的绑定，不恢复基于缓存列表的对象删除。

`GET /snapshots` 的 `name` 查询参数按别名精确过滤：

- 空值按未提供处理；重复值沿用既有快照列表解析（取第一个）。
- 查询保持 user 级 owner 过滤，不因 name 过滤绕过资源归属。
- 命中多条时返回创建时间最新的一条（分页器按创建时间升序排序后取末元素）；带 name 时忽略 `limit`/`nextToken` 的分页效果（非法 `limit` 仍按参数错误返回 400），结果恒为 0 或 1 条且不返回 nextToken。
- 创建进行中或新对象尚未进入本副本可见的 Succeeded 集合时，查询仍可返回旧快照；新对象可见后重新选择最新者。不带 name 的列表可返回全部保留的同名对象。

### 响应

创建成功仍为 201，返回既有 `snapshotID`（`status.checkpointId`，不采用 `team-slug/name:tag` 别名格式）与 `names`。命名快照的 `names` 为 `[name]`，未命名为 `[]`；列表每个元素同样始终包含数组类型的 `names`，不得为 `null` 或省略字段；空列表为 `[]`。

## 可观察验收示例

1. 多个属于模板 `python` 的 Sandbox 存在时，附带 `template=python&order=desc` 不会仅因参数被误当 metadata 而返回空集，且逐条命中该模板的 Sandbox；不匹配的模板合法返回空集。
2. 两个表示相同时刻的 RFC3339 时区写法在 `startedAfter` 中得到相同结果，恰好在边界的 Sandbox 被包含；相同领取时刻且不同 ID 的对象能够跨页完整遍历。
3. 省略排序得到从新到旧的 Sandbox 列表，指定 `asc` 得到相反时间方向；快照列表保持原有升序。
4. `limit`、`nextToken`、`order`、`template`、`startedAfter` 的重复值或空值返回 400；显式 metadata 中的同名业务键仍按 metadata 过滤。
5. Pause 的 `memory:true` 与 `memory:false` 都返回 400，且调用前后的 Sandbox 暂停状态、timeout、annotation 和持久化策略均不变化；省略 memory、`{}`、空 body 保持原流程。
6. Pause 请求体为 `{}garbage` 或 `{} {"memory":false}` 时返回 400 且不暂停；尾随空白仍被接受。
7. `memory:false` 创建快照时该 checkpoint 仅保存文件系统，源策略不变；`memory:true` 保存 memory+filesystem；有效内容头优先于 body。
8. 同一 owner 的多次同名创建分别返回本次新建的 ID，全部既有对象保持存在；创建失败不影响旧对象，其他 owner 的同名快照不受影响。`GET /snapshots?name=` 返回该 owner 最新可见的一条，不带 name 的列表可见多条。
9. 非法 `name` 由后端存储规则拒绝并映射为 400 `Invalid snapshot name`，响应不含 Checkpoint/Kubernetes 校验细节，且不创建 Checkpoint、不删除旧快照；`name:null` 与 `name:""` 创建未命名快照。
10. 不带 `name` 的创建与列表响应在 JSON 上都是数组类型的 `names`，空数组不会变成 `null`；带 `name` 的列表只返回该 user 可见的最新一条。
11. 升序和降序新游标在同方向可续页，在显式相反方向返回 400；省略 order 时沿用 token 携带的方向继续翻页，token 无方向时按默认降序解释；历史裸 token 与无方向 stable cursor 在两种方向均继续可读。
12. `template=base:latest` 与纯空白 template 返回 400；`template=%20TEST-Template%20` 归一化为 `test-template` 后能命中该模板。

## 非目标与取舍

不增加内存快照能力承诺、单次 filesystem-only 暂停、tag/build 版本 API、按 name 的独立 get/delete 端点、connect 的模式选择、全局分页新协议、Checkpoint CRD 字段、存储后端、监控指标或无关 metadata 修复。命名快照复用 label 与既有 Succeeded 列表能力，保留各次创建的对象，不新增别名注册中心或分布式锁。SandboxSet `templateRef` 的模板身份不一致与快照恢复 Sandbox 的模板身份仍由既有写入方决定。不修改源策略继承、直接 Checkpoint CR 或其他 API 的能力约束。

本设计不承诺运行环境已经验证，也不将设计完成等同于独立评审、实现、人工验收或上游 Issue 关闭。

## 主要证据

- `pkg/servers/e2b/list.go`：列表参数解析与筛选、Sandbox 排序键、快照名称的最新可见者查询。
- `pkg/utils/pagination/pagination.go`：方向感知的 cursor 比较与分页。
- `pkg/servers/e2b/sandbox.go`：模板身份与启动时间来源；`pkg/servers/e2b/templates.go`：模板 ID/别名。
- `pkg/servers/e2b/pause_resume.go`：暂停流程与可选请求体解析；`pkg/sandbox-manager/infra/interface.go`：现有 PauseOptions 不含单次持久化内容。
- `pkg/servers/e2b/snapshot.go`、`pkg/servers/e2b/models/sandbox.go`、`pkg/servers/e2b/models/extensions.go`：快照创建、稳定错误映射、请求模型与扩展头。
- `pkg/sandbox-manager/infra/sandboxcr/clone.go`：checkpoint 创建、别名校验与 label 写入、固定宽度创建时间戳；`pkg/sandbox-manager/infra/sandboxcr/infra.go`：按别名选择 Succeeded checkpoint。
- `api/v1alpha1/labels.go`：`CheckpointLabelAlias`；`api/v1alpha1/annotations.go`：`AnnotationCheckpointCreationTime`；`api/v1alpha1/checkpoint_types.go`：KeepRunning 默认行为。
- https://github.com/e2b-dev/E2B/blob/b52cd30c14bf7038ba5bfbd15456b1dabe567082/spec/openapi.yml ：`SandboxPauseRequest`、`SandboxSnapshotRequest`、`GET /v2/sandboxes` 与 `/snapshots`。
- https://github.com/openkruise/agents/issues/1083
- https://github.com/openkruise/agents/issues/1084
- https://github.com/openkruise/agents/issues/1085
- https://help.aliyun.com/zh/cs/user-guide/clone-agent-sandbox-using-checkpoint ：官方当前仅支持 filesystem，请求级覆盖、KeepRunning 默认值及按快照 ID 恢复文件的契约；实际使用须具备文档要求的 ACS 后端及接入组件，不等同于纯开源默认构建已具备完整后端。
