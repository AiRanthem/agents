# E2B #1083、#1084、#1085 最小兼容修复

## Why：消除合法请求的错误结果与静默语义偏差

三项问题均影响官方 E2B SDK 的正常调用：列表查询可能错误返回空集，暂停/快照可能保存了调用者要求排除的内存，命名查询可能返回未经筛选的全集。即便本轮不实现全部新增能力，也必须明确拒绝无法履行的请求，不能继续返回误导性的成功。

2026-10-20，用户要求解决三个 Issue；在讨论影响及能力成本后，于本会话选择“最小修复 (Recommended)”。确认范围为：完整修复 Sandbox 列表查询；暂停的 `memory:false` 明确 400；快照支持 filesystem-only、`names` 始终为数组，创建和列表的 `name` 明确 400。本说明将该范围补充为完整行为候选，范围选择不冒充对随后新增细节的批准。

## 基线与边界

- 源码基线：`openkruise/agents` 的 `upstream/master@2b06e110327f52da85053730a531ec3b3b0d6a46`。当前内部 `develop` 不是本设计的开源实现基线。
- 协议依据：E2B OpenAPI `b52cd30c14bf7038ba5bfbd15456b1dabe567082`；问题中的 SDK 为 e2b 2.56.0。
- E2B API 层负责参数、验证、错误与返回形状。复用现有中立 checkpoint 能力；不把 E2B 参数下沉到 Manager/Infra，不新增 API 到具体后端的访问。
- 既有认证、租户可见性、资源归属、Sandbox ID、资源查找错误、暂停保留期限、快照超时/清理语义保持不变。原生与定制路由的同一操作行为一致。
- 本总项尚无已注册的开发仓库及具体开发项。设计描述不建立代码所有权；进入源码实现仍须满足项目注册、当前设计审批、独立评审和 development-start 门禁。

## #1083：Sandbox 列表

`GET /v2/sandboxes` 将 `order`、`template`、`startedAfter` 识别为独立保留参数，不再作为 metadata 键；现有 `state`、`metadata`、`limit`、`nextToken` 和其他已支持的 metadata 查询行为不随此修复重写。

| 输入 | 可观察行为 |
| --- | --- |
| 省略 `order` | 按启动时间降序，新 Sandbox 在前。 |
| `order=asc` / `order=desc` | 按指定方向排序；空值或其他值返回 400。 |
| `template=<ID或别名>` | 与 Sandbox 的实际模板身份匹配，和其他条件取交集；合法但不存在的模板得到空数组。当前服务将 SandboxSet 名称同时作为模板 ID 与别名，不引入新的别名注册体系。空值返回 400。 |
| `startedAfter=<RFC3339时间>` | 仅返回启动时间大于或等于给定时刻的 Sandbox；支持合法时区偏移及小数秒，按时间点而非字符串比较；空值或无效格式返回 400。 |

新保留参数各为单值；重复提供时返回 400，避免请求出现多个互相冲突的语义。既有参数的重复值行为不在此修复中改变。显式 `metadata` 内名为 `order`、`template` 或 `startedAfter` 的普通业务键仍按 metadata 处理，不与顶层保留参数混淆。

启动时间使用现有 Sandbox 领取时间，与 `startedAt` 的数据来源一致，而不是 Pod/CR 创建时间。缺失或无法解析启动时间的对象不能参与时间有序列表，不伪造当前时间或零时间。

排序和游标使用同一时间顺序；同一启动时刻按稳定的 Sandbox ID 决定次序，两项共同构成完整顺序。相同查询与方向、数据集未变化时，连续翻页不得丢失或重复同一时刻的对象；最后一页不返回下一页 token，空列表返回 `[]`。筛选必须先于分页，不能先截取一页再筛选。

`nextToken` 是不透明的续页位置，不承诺跨排序/筛选变更或跨版本恢复一次旧遍历；改变这些条件或从旧默认升序升级后应重新开始遍历。保留已有游标编码及其既有读取能力，续页比较须服从当前排序方向；不为这次修复新增游标存储或会话。并发增删下沿用既有非快照式分页，不保证跨请求数据集冻结。

共享分页能力的其他调用者保持既有默认顺序，特别是快照列表不得因为 Sandbox 默认降序而被一起反转。

## #1084：Pause 请求

`POST /sandboxes/{sandboxID}/pause` 读取可选 JSON 对象：

- 无请求体或 `{}`：保留现有行为。
- `{"memory":true}`：保留现有暂停策略，不重写 Sandbox 的持久化策略；这不保证覆盖模板/创建阶段已经选择的 filesystem-only 策略。
- `{"memory":false}`：返回 400，明确说明单次 filesystem-only 暂停暂不支持；即使模板原本不保存内存也一致拒绝该请求，不根据隐含策略伪装成支持。
- 非法 JSON、非对象请求体或 `memory` 不是布尔值（包括显式 `null`）：返回 400。

无效或不支持的请求不得触发暂停、写入 timeout/annotation 或改变持久化策略。保留既有认证与资源查找边界，不在未授权时披露资源诊断；成功仍为 204，既有 404/409/500 分类保持不变。

明确保留的限制是：本轮不实现单次暂停模式，不改 controller 生命周期策略，也不改变 connect/resume 的恢复模式。

## #1085：Snapshot 请求与响应

### 创建与 memory

`POST /sandboxes/{sandboxID}/snapshots` 仍要求 JSON 对象，请求体缺失、非法 JSON、非对象或 `memory` 非布尔值（包括显式 `null`）返回 400，而不是服务器错误。

- `memory:false`：该次 checkpoint 的持久化内容仅为 `filesystem`，不得包含 `memory`；复用现有 checkpoint 的 filesystem-only 创建及恢复路径。
- `memory:true`：该次 checkpoint 同时保存 `filesystem` 与 `memory`。
- 省略 `memory`：保持现有扩展头优先、否则继承 Sandbox 持久化内容的行为，不借此修改已有默认策略。这是保留的兼容限制，并非声称所有模板都符合 E2B 省略时默认完整内存快照的语义。

与 `x-e2b-kruise-snapshot-persistent-contents` 的关系：未显式提供 `memory` 时，扩展头沿用既有语义；两者同时提供时，解析后的内容集合必须与显式 `memory` 所要求的集合一致，否则返回 400。集合比较忽略顺序，不静默选择任一方覆盖另一方；扩展头自身无效仍返回 400。

模式只作用于本次 checkpoint，不修改源 Sandbox 的长期策略或模板。源 Sandbox 默认继续运行；显式使用既有 `snapshot-keep-running` 扩展头的调用继续遵守该头的既有语义。filesystem-only 快照不包含运行进程、内存状态或连接的恢复承诺，基于它创建的 Sandbox 按现有 filesystem-only 路径从磁盘重新启动；不扩大可保存的文件系统范围或新增存储能力。

TTL、同步等待、取消、创建失败后的清理和成功返回条件全部沿用既有 checkpoint 实现。前置参数错误不得创建 Checkpoint/SandboxTemplate 或触发源 Sandbox 状态变化；不会将后端失败包装成成功。

### 暂不支持的 name

- 创建 JSON 只要显式出现 `name`，包括空串或 `null`，即返回 400，说明命名快照暂不支持。
- `GET /snapshots` 只要出现 `name` 查询参数，包括空值，即返回 400，说明名称筛选暂不支持；不得忽略参数后返回全集。
- 不把随机 checkpoint 名称或某个 annotation 冒充 E2B 的模板别名/同名 build/tag 体系。
- 不带 `name` 的快照列表保留现有 `sandboxID`、`limit`、`nextToken`、可见性及排序规则。

### 响应

创建成功仍为 201，返回既有 `snapshotID` 与 `names: []`。列表每个元素也总是包含 `names: []`，不得为 `null` 或省略字段；空列表为 `[]`。没有命名能力时不合成虚假的名字。

## 可观察验收示例

1. 多个属于模板 `python` 的 Sandbox 存在时，附带 `template=python&order=desc` 不会仅因参数被误当 metadata 而返回空集；不匹配的模板合法返回空集。
2. 两个表示相同时刻的 RFC3339 时区写法在 `startedAfter` 中得到相同结果，恰好在边界的 Sandbox 被包含；相同领取时刻且不同 ID 的对象能够跨页完整遍历。
3. 省略排序得到从新到旧的 Sandbox 列表，指定 `asc` 得到相反时间方向；快照原有列表顺序保持不变。
4. Pause 的 `memory:false` 返回 400，且调用前后的 Sandbox 暂停状态、timeout、annotation 和持久化策略均不因该请求变化；省略和 `true` 保持原流程。
5. 内存持久化模板的 Sandbox 使用 `memory:false` 创建快照时，该 checkpoint 仅保存文件系统，源策略不变；`memory:true` 选择完整内容，互相冲突的持久化头在创建前返回 400。
6. 创建或查询带 `name` 时明确 400；不带 `name` 的创建与列表响应在 JSON 上都是数组类型的 `names`，空数组不会变成 `null`。
7. 错误 JSON、错误布尔类型和非法新增列表参数得到客户端错误；拒绝路径没有生命周期或 checkpoint 写入副作用，租户可见性和错误分类不退化。

## 非目标与取舍

不增加单次 filesystem-only 暂停、命名快照/同名版本/别名注册、connect 的模式选择、全局分页新协议、CRD 字段、存储后端、监控指标或与三个 Issue 无关的 metadata 修复。显式拒绝未支持能力是用户本轮接受的交付边界；只有后续明确需要完整能力时才重新讨论这些限制。

本设计不承诺运行环境已经验证，也不将设计完成等同于独立评审、实现、人工验收或上游 Issue 关闭。

## 主要证据

以下代码位置均以本说明的开源基线为准：

- `pkg/servers/e2b/list.go:105`：列表参数解析；`:196`：筛选；`:222`：快照列表。
- `pkg/utils/pagination/pagination.go:59`：当前升序及稳定游标；Sandbox 与快照共用此能力。
- `pkg/servers/e2b/sandbox.go:119`、`:168`：模板身份与启动时间；`pkg/servers/e2b/templates.go:178`：已公开的模板 ID/别名。
- `pkg/servers/e2b/pause_resume.go:43`：暂停流程；`pkg/sandbox-manager/infra/interface.go:149`：现有 PauseOptions 不含单次持久化内容。
- `pkg/servers/e2b/snapshot.go:71`、`:96`：checkpoint 参数传递与解析；`pkg/servers/e2b/models/extensions.go:465`：快照扩展头。
- `pkg/sandbox-manager/infra/sandboxcr/clone.go:547`、`:586`：checkpoint 创建与单次内容覆盖；`api/v1alpha1/checkpoint_types.go:136`：KeepRunning 默认行为。
- https://github.com/e2b-dev/E2B/blob/b52cd30c14bf7038ba5bfbd15456b1dabe567082/spec/openapi.yml ：`SandboxPauseRequest`、`SandboxSnapshotRequest`、`GET /v2/sandboxes` 与 `/snapshots`。
- https://github.com/openkruise/agents/issues/1083
- https://github.com/openkruise/agents/issues/1084
- https://github.com/openkruise/agents/issues/1085
