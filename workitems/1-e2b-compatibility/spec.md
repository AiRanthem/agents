# E2B #1083、#1084、#1085 兼容修复

## Why：消除合法请求的错误结果与静默语义偏差

三项问题均影响官方 E2B SDK 的正常调用：列表查询可能错误返回空集，暂停/快照可能保存了调用者要求排除的内存，命名查询可能返回未经筛选的全集。对无法履行的请求必须明确拒绝，不能返回误导性的成功。

用户已确认三项均需修复，并在后续会话中逐项确认了当前范围：完整修复 Sandbox 列表；Pause 暂时不支持单次 memory 选择，任何显式 `memory` 都返回 400；Snapshot 通过 body `memory` 或持久化内容扩展头选择内容，支持命名快照与同名替换，`names` 始终为数组。本节记录当前生效的完整范围；历史设计中的“拒绝 name”“`memory:true` 返回 400”等表述已被后续决定取代。

## 基线与边界

- 源码基线：`openkruise/agents` 的 `upstream/master@fd2bea7193d98c1d456fa6c43a2ae3e7e4f4fd48`。原设计点名的 `2b06e110` 与该基线之间 `pkg/servers/e2b`、分页与 checkpoint 相关路径无变化，设计适用性已单独评估。
- 协议依据：E2B OpenAPI `b52cd30c14bf7038ba5bfbd15456b1dabe567082`；问题中的 SDK 为 e2b 2.56.0。
- E2B API 层负责参数、验证、错误与返回形状；协议兼容编排（如同名替换顺序）留在 API 层。存储格式限制（如 label value 规则）由其 Infra 实现入口校验并返回领域错误，API 层只做状态码映射。
- 既有认证、租户可见性、资源归属、Sandbox ID、资源查找错误、暂停保留期限、快照超时/清理语义保持不变。原生与定制路由的同一操作行为一致。
- 设计描述不建立代码所有权；源码实现仍须满足项目审批、独立评审与 development-start 门禁。

## #1083：Sandbox 列表

`GET /v2/sandboxes` 将 `order`、`template`、`startedAfter` 识别为独立保留参数，不再作为 metadata 键。

| 输入 | 可观察行为 |
| --- | --- |
| 省略 `order` | 按启动时间降序，新 Sandbox 在前。 |
| `order=asc` / `order=desc` | 按指定方向排序；空值或其他值返回 400。 |
| `template=<ID或别名>` | 与 Sandbox 解析出的模板身份（中性 Infra 的 `GetTemplate()`）精确匹配，和其他条件取交集；合法但不存在的模板得到空数组。当前服务将 SandboxSet 名称同时作为模板 ID 与别名，不引入新的别名注册体系；API 层不叠加池名等其他标签匹配，以保持 Infra 接口中立。空值返回 400。 |
| `startedAfter=<RFC3339时间>` | 仅返回启动时间大于或等于给定时刻的 Sandbox；支持合法时区偏移及小数秒，按时间点而非字符串比较；空值或无效格式返回 400。 |

查询参数按单值解析：`order`、`template`、`startedAfter` 以及既有的 `limit`、`nextToken` 在空值或重复提供时返回 400，避免同一请求出现多个互相冲突的语义。`state` 与 `metadata` 沿用既有解析方式（`state` 逗号分隔、`metadata` 组合键），未知参数仍按 metadata 处理。显式 `metadata` 内名为 `order`、`template` 或 `startedAfter` 的普通业务键仍按 metadata 处理，不与顶层保留参数混淆。

启动时间使用现有 Sandbox 领取时间，与 `startedAt` 的数据来源一致，而不是 Pod/CR 创建时间。缺失或无法解析启动时间的对象不参与时间有序列表（排序键为空的对象被分页器过滤），不伪造当前时间或零时间。排序键输出为固定宽度 UTC 纳秒串，字典序等于时间序。

排序和游标使用同一时间顺序；同一启动时刻按稳定的 Sandbox ID 决定次序。相同查询与方向、数据集未变化时，连续翻页不得丢失或重复同一时刻的对象；最后一页不返回下一页 token，空列表返回 `[]`。筛选先于分页。

`nextToken` 是不透明的续页位置：stable cursor 编码排序键与唯一键，旧版裸排序键 token 继续可读，续页比较服从当前排序方向；不承诺跨排序/筛选变更或跨版本恢复一次旧遍历。并发增删下沿用既有非快照式分页，不保证跨请求数据集冻结。

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
- 别名格式属于存储限制：`sandboxcr.CreateCheckpoint` 入口按 Kubernetes label value 规则校验，非法时返回领域错误 `ErrorBadRequest`，API 层映射为 400，消息包含 `invalid checkpoint alias`。API 层不做格式校验，未来其他 Infra 后端可放宽。
- 别名的作用域是「同一 owner（API key）+ team namespace」：顺序替换完成后，同一 owner 的同一别名只保留一个 Succeeded checkpoint；同 team 的不同 owner 可各自持有同名别名，互不替换、互不删除。同一 owner 的并发重复由下述收敛规则消除。
- 该作用域与 `GET /snapshots?name=` 的 user 级可见性、以及 Checkpoint 删除的 owner 校验一致：别名收敛不放宽任何既有资源归属边界。恢复链路按 namespace 与 checkpointID 查找 Checkpoint，不受别名作用域影响。

同名替换（E2B：新的 build 分配到已有 template）由 API 层编排，顺序固定为“先建、成功后再收敛别名”：

1. 直接调用 `CreateCheckpoint` 创建新 checkpoint，不在创建前读取或删除旧对象；失败（含别名非法、后端失败、等待超时）时不产生任何删除副作用，旧快照保持原样。
2. 创建成功后，按别名列出同 namespace 下该 owner 当前 Succeeded 的 checkpoint（owner 作用域，保留 user 过滤），并按 Checkpoint 创建时间（固定宽度 UTC 纳秒串）与对象名组成确定的全序，选出最新者。
3. 若本次新建的是最新者，删除其余所有同别名 Succeeded checkpoint；若本次新建的不是最新者（并发中已被更新的请求取代），删除本次新建的 checkpoint，并在 201 响应中返回当前最新者的 `snapshotID`。删除仍经既有 owner 校验，不引入跨 owner 的删除授权旁路。删除失败只记录日志，不影响 201，也不把已成功的创建标记为失败；后续同名创建会继续清理残留。

不变量：收敛必须以非空 owner 为前提。owner 为空时跳过收敛并记录日志，不得因空值退化为跨 owner 的列举与删除。

该顺序保证创建失败不会丢失既有快照，并让同一 owner 的并发同名创建收敛到同一个最新对象。收敛依赖 Checkpoint 的创建时间：创建时把本地时钟以 RFC3339 纳秒精度写入 Checkpoint annotation `agents.kruise.io/checkpoint-creation-timestamp`，`AsCheckpointInfo` 统一输出固定宽度 UTC 纳秒时间戳，字典序等于时间序，避免同一秒内的并发创建退化为按随机名称决定胜者；存量对象缺失该 annotation 时回退到秒级 `metadata.creationTimestamp`，排序精度降级但结果确定。已知限制：记录时间来自创建副本的本地时钟且早于 API 创建完成，跨副本时钟偏差或创建延迟可能使排序与真实先后不一致，此时可能保留较旧者。

收敛是尽力而为：它只读取一次本副本可见的 Succeeded 集合，不重试、不做后台补偿、不使用 `APIReader` 列举、不引入分布式锁。列举或删除失败只记录日志，不影响 201；多副本或 watch 滞后下，重复对象可能残留到下一次同名创建才被清理。带 `name` 的查询始终返回可见集合中最新的一条，因此对外解析结果稳定；不带 `name` 的列表在收敛完成前可能短暂出现两条。

仍存在的竞态：较早的请求先返回 201 后，较新的请求仍可能删除它，因此并发同名创建中已经返回的 `snapshotID` 可能随后失效，这是“不保留旧 build”语义的固有取舍。删除使用与请求上下文解耦的有限超时，客户端断开不影响清理。

`GET /snapshots` 的 `name` 查询参数按别名精确过滤：

- 空值按未提供处理；重复值沿用既有快照列表解析（取第一个）。
- 查询保持 user 级 owner 过滤，不因 name 过滤绕过资源归属。
- 命中多条时返回创建时间最新的一条（分页器按创建时间升序排序后取末元素）；带 name 时忽略 `limit`/`nextToken` 的分页效果（非法 `limit` 仍按参数错误返回 400），结果恒为 0 或 1 条且不返回 nextToken。
- 创建进行中、新对象尚未 Succeeded 时，查询返回旧快照而不是空结果；创建成功且收敛完成前可能短暂看到新旧两条，收敛后只剩一条。快照排序键为固定宽度 UTC 纳秒时间戳，同一时刻的对象由名称决定次序。

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
8. 带合法 `name` 创建返回 `names:[name]`，同一 owner 的同名旧 Succeeded 快照在新快照成功后按“最新者胜出”被删除；创建失败时旧快照保留；其他 owner 的同名快照不受影响。同一 owner 的两个并发同名创建在收敛成功时至多保留一个 Succeeded checkpoint；被更新请求取代的一方删除自己的 checkpoint，并以最新者的 `snapshotID` 返回。`GET /snapshots?name=` 在收敛完成前仍能解析到可用快照。
9. 非法 `name` 由后端存储规则拒绝并映射为 400，且不创建 Checkpoint、不删除旧快照；`name:null` 与 `name:""` 创建未命名快照。
10. 不带 `name` 的创建与列表响应在 JSON 上都是数组类型的 `names`，空数组不会变成 `null`；带 `name` 的列表只返回该 user 可见的最新一条。

## 非目标与取舍

不增加内存快照能力承诺、单次 filesystem-only 暂停、tag/build 版本历史、按 name 的独立 get/delete 端点、connect 的模式选择、全局分页新协议、Checkpoint CRD 字段、存储后端、监控指标或与三个 Issue 无关的 metadata 修复。命名快照复用 Checkpoint label 与既有 Succeeded 列表能力，不新增别名注册中心或分布式锁，并发收敛依赖 Checkpoint 创建时间排序。替换不保留旧 build，旧对象删除后其 SandboxTemplate 按既有 ownerRef GC 清理。别名唯一性不跨 owner，因此不引入 team 级删除授权旁路；SandboxSet `templateRef` 的模板身份不一致与快照恢复 Sandbox 的模板身份均由既有写入方决定，本轮不修复。不修改源策略继承、直接 Checkpoint CR 或其他 API 的能力约束。

本设计不承诺运行环境已经验证，也不将设计完成等同于独立评审、实现、人工验收或上游 Issue 关闭。

## 主要证据

- `pkg/servers/e2b/list.go`：列表参数解析与筛选、Sandbox 排序键、快照列表与 name 收敛。
- `pkg/utils/pagination/pagination.go`：方向感知的 cursor 比较与分页。
- `pkg/servers/e2b/sandbox.go`：模板身份与启动时间来源；`pkg/servers/e2b/templates.go`：模板 ID/别名。
- `pkg/servers/e2b/pause_resume.go`：暂停流程与可选请求体解析；`pkg/sandbox-manager/infra/interface.go`：现有 PauseOptions 不含单次持久化内容。
- `pkg/servers/e2b/snapshot.go`、`pkg/servers/e2b/models/sandbox.go`、`pkg/servers/e2b/models/extensions.go`：快照请求模型、扩展头与别名替换编排。
- `pkg/sandbox-manager/infra/sandboxcr/clone.go`：checkpoint 创建、别名校验与 label 写入、固定宽度创建时间戳；`pkg/sandbox-manager/infra/sandboxcr/infra.go`：按别名选择 Succeeded checkpoint。
- `api/v1alpha1/labels.go`：`CheckpointLabelAlias`；`api/v1alpha1/annotations.go`：`AnnotationCheckpointCreationTime`；`api/v1alpha1/checkpoint_types.go`：KeepRunning 默认行为。
- https://github.com/e2b-dev/E2B/blob/b52cd30c14bf7038ba5bfbd15456b1dabe567082/spec/openapi.yml ：`SandboxPauseRequest`、`SandboxSnapshotRequest`、`GET /v2/sandboxes` 与 `/snapshots`。
- https://github.com/openkruise/agents/issues/1083
- https://github.com/openkruise/agents/issues/1084
- https://github.com/openkruise/agents/issues/1085
- https://help.aliyun.com/zh/cs/user-guide/clone-agent-sandbox-using-checkpoint ：官方当前仅支持 filesystem，请求级覆盖、KeepRunning 默认值及按快照 ID 恢复文件的契约；实际使用须具备文档要求的 ACS 后端及接入组件，不等同于纯开源默认构建已具备完整后端。
