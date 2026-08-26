---
title: Sandbox-manager 状态模型与分层
authors:
  - "@AiRanthem"
reviewers: []
creation-date: 2026-07-15
last-updated: 2026-08-26
status: provisional
---

# Sandbox-manager 状态模型与分层

## 摘要

本提案为 sandbox-manager 定义一套后端中立的结构化 State。它把用户交付、释放、Pause/Resume
转换和当前工作负载能力分开，使可见性、路由、操作准入和配额不再分别解释 Sandbox CR 的
Phase、Condition、annotation 或 reason。

State 包含四个互相独立的维度：

    State {
        Delivery    unclaimed | claimed | ready | reserved-failed
        Release     none | due | terminal | committed
        PauseResume none | pausing | resuming
        Workload    provisioning | ready | paused | unready | completed
    }

Claim 和 Clone 使用两阶段交付。第一阶段的 Sandbox CR 写持久化 owner、公开 ID、claim lock、quota
reservation 引用和固定交付截止时间，产生隐藏且不可路由的 `claimed`。只有当前 Pod 的 runtime、
credential、CSI 和 TrafficPolicy
服务就绪事实全部完成后，第二阶段的最终条件写才提交 `DeliveryReady=True`，产生 `ready`。该最终写
是可见性、running Route 和成功响应的提交点。

claim lock UUID 是一次交付的轮次标识（DeliveryEpoch，后文简称 epoch）。所有流量和要求安全状态
已得到证明的操作都必须匹配当前 epoch；缺失或不匹配时一律拒绝。Recycle 在允许下一次 claim 前
形成完整隔离屏障，使旧 epoch 的资源、
credential、连接和迟到操作都不能影响下一名 owner。

本设计以健康 sandbox-manager 和 Gateway 副本共享同一个权威对外服务快照为前提。这个快照是
各副本回答请求和转发流量时共同使用的 Sandbox CR 与 Route 视图。未追平或尚未完成初始快照的
副本不提供服务。本提案定义终态，不提供降级或混合版本兼容。

本提案保持 `provisional`。

## 背景

Sandbox 状态同时影响池候选选择、Create 和 Clone 完成、Pause 和 Resume、流量转发、owner
可见性、配额以及释放。把这些问题压缩成一个扁平状态，会混淆以下不能互换的事实：

- 资源已归属用户，但交付尚未完成；
- 初始交付已经完成，但当前 workload 正在 Pause、Resume 或升级；
- workload 已停止，但清理尚未提交；
- 截止时间已到，但 release 变更尚未赢得并发提交；
- release 已不可逆提交，但 Recycle 屏障仍在收敛。

现有 Sandbox CR 仍是后端事实的权威来源。State 不创建第二套生命周期存储；它建立统一解释边界：
Sandbox CR 映射器产生中立事实，Manager 执行业务策略，API 负责认证、授权和公开协议映射，Route
只负责流量投影。

Recycle 会保留同一个 Sandbox CR 和 UID，却允许同一个对象先后交付给不同 owner。因此 UID、名称
或公开 ID 都不能单独标识一次交付。没有 delivery epoch 和完整隔离屏障，旧操作、credential 或
TrafficPolicy 可能越过 Recycle 边界影响下一次交付。

### 目标

- 在安全交付完成前隐藏 Sandbox 并拒绝流量。
- 将归属、释放、Pause/Resume 和工作负载能力分开。
- Manager 和 API 不直接读取 Sandbox CR Phase、Condition、annotation 或 reason。
- Infra Observation 和 Route 投影共用同一个 Sandbox CR 映射器。
- 第一次 claim 写之后的所有交付能力都绑定到已授权的 DeliveryEpoch 和后端对象版本。
- 使用有效 workload digest 证明当前 Pod 与期望输入一致。
- 无法证明状态安全时，拒绝流量和其他要求安全状态的操作。
- 在健康副本之间提供一致的可见性和 Route 对外服务快照。

### 非目标

- 不引入 SandboxRecord 或其他权威可见性存储。
- 不保证 Sandbox CR 实际不存在时仍能恢复可见性。
- 不把 `ShutdownTime` 变成严格墙钟流量截止点，也不向 Route 增加截止时间。
- 不持久化每个交付步骤，也不恢复进程崩溃前的同一次交付执行。
- 不改变 E2B API 的公开状态集合或既有错误类别。
- 除下文契约明确命名的存储事实外，不规定具体 annotation、label、RPC、selector、缓存数据结构、
  hash 算法或 Recycle 清理步骤。
- 不设计 legacy 对象迁移、mixed-version 协议、版本握手或降级 fallback。
- 除 delivery provenance 和隔离外，不改变 Checkpoint 的生命周期或存储策略。

## 设计终态

### 1. 总体边界和前提

依赖方向固定为：

    Sandbox CR
        |
        | Sandbox CR 映射器
        v
    neutral State + Observation
        |                              |
        | Infra capabilities           | Route projection
        v                              v
    Manager policy -> API       Manager/Gateway Route stores
                                         |
                                         v
                                Gateway traffic admission

中立 State 包只定义状态取值、校验和 MutationToken 契约。MutationToken 是 Infra 返回给 Manager
的不透明变更凭据，Manager 只能原样带回，不能解析。Sandbox CR 专用映射器负责解释 CR 字段。
具体 Kubernetes 读写只位于 Sandbox CR Infra；Manager 只依赖中立 Observation 和能力。
Sandbox Controller 是独立 operator，不依赖 Manager、API 或具体 Infra 实现。

本设计依赖两个终态前提：

1. **Recycle 隔离屏障。** 在清除旧认领身份并重新进入候选池前，所有可能影响下一次交付的
   旧 runtime、credential、长连接、CSI 状态、Pod 身份、TrafficPolicy 匹配、Route、内部
   Checkpoint 和迟到 writer 都已失效。无法证明屏障完成时，Sandbox 必须删除或隔离，不能重新
   claim。可独立存在的用户 Snapshot 不被删除，但保留源 epoch 的来源证明，不能作为下一次交付的
   活动状态。
2. **一致的对外服务快照。** 所有健康 Manager 和 Gateway 只基于同一个权威 Sandbox CR 快照及其
   Route 投影提供服务。落后、失联、重启后未完成初始快照，或无法拒绝旧副本事件的副本退出
   readiness。primary Lease 只选择后台清理器，不成为 owner API 的单点入口。

权威发布方提供单调递增的发布水位。ready 对象的 Kubernetes resourceVersion（后文简称 RV）和对应
Route 被该水位覆盖后，才成为共同对外服务状态。Manager 或 Gateway 只有追平水位后才能宣告健康；
新加入或恢复的副本追平前保持 unready，因此不会改变一个已经开始的发布等待所代表的健康副本集合。

一致快照不替代 MutationToken 或条件比较并写入（CAS）。请求取得快照后，状态仍可能被另一个请求
修改；所有变更必须在真正生效的边界再次验证对象版本和 DeliveryEpoch。本地时钟在截止时间边界
可能产生不同的 `due` Observation；Route 忽略 `due`，因此这不形成 Route 分歧。

### 2. State 和 Observation

| 维度 | 取值 | 回答的问题 |
|---|---|---|
| Delivery | unclaimed / claimed / ready / reserved-failed | 这次用户交付已经到哪一步？ |
| Release | none / due / terminal / committed | 当前观察到了哪一种释放事实？ |
| PauseResume | none / pausing / resuming | 是否正在执行普通 Pause 或 Resume？ |
| Workload | provisioning / ready / paused / unready / completed | 当前能够证明什么工作负载能力？ |

对象不存在是 State 之外的 `NotFound` 结果。缺失对象不能伪装成某个 State；无效 State 也不能伪装
成 NotFound。

Infra 查询从同一个快照返回：

    Observation {
        State         State
        Owner         string
        MutationToken // 不透明变更凭据
    }

MutationToken 至少绑定 Sandbox ObjectKey、UID、resourceVersion、claimed marker、owner、公开 ID、
当前 claim lock、quota reservation ID 与 generation、claim timestamp 和交付截止时间。
Manager 和 API 不解析 token。

#### Delivery

映射器先校验认领事实，再按以下规则产生 Delivery：

1. claimed marker 不存在或明确为 false，并且 owner、公开 ID、claim lock、quota reservation 引用和
   失败保留事实均不存在：`unclaimed`。旧 `DeliveryReady` 和旧交付截止时间可以留存，但没有当前
   epoch 时不生效。
2. claimed marker 为 true、认领身份完整，并且当前 epoch 的失败保留事实完整：
   `reserved-failed`。如果同一 epoch 还存在匹配的 `DeliveryReady=True`，Observation 无效。
3. claimed marker 为 true、认领身份完整，并且当前 `DeliveryReady=True` 的 Message 能解析并匹配
   当前 claim lock：`ready`。
4. claimed marker 为 true、认领身份完整，但尚无匹配的 ready 事实：`claimed`。
5. 未知的 claimed marker 值，或其他缺失、残留、无法解析或冲突的组合，使 Observation 无效。
   Infra 返回 internal 或 unavailable，Route 拒绝流量。

`DeliveryReady` 是与当前 claim 绑定的 Condition：

- `Type` 为 `DeliveryReady`；
- 成功提交使用 `Status=True` 和稳定的完成 reason；
- `Message` 是 JSON，分别保存 `deliveryEpoch` 和 `diagnostic`；
- 只有 `Status=True` 且 `deliveryEpoch` 等于当前 claim lock 时才产生 `ready`；
- 无法解析、缺失或 epoch 不匹配的 Condition 不允许流量通过，也不准入要求安全状态已证明的操作，
  仍产生隐藏的 `claimed`；
- `ObservedGeneration` 不是 epoch，因为 claim metadata 更新不改变 generation；
- Condition 可以跨 Recycle 留存；新 claim lock 会使旧 Condition 自动失效。

`DeliveryReady` 由 Sandbox CR Infra 独占设置。Sandbox Controller 不设置、不清除、不解释该
Condition。它的 informer 可以观察到该更新，但 Sandbox Controller 的每个 Sandbox watch 都通过
语义过滤器，使仅有 `DeliveryReady` 变化的更新不入队。因此成功第二阶段提交只产生一次 Infra
status 写，不触发 Sandbox Controller reconcile，也不产生由 Controller 发起的额外 APIServer 写。
所有 status writer 使用对象版本前置条件，并保留不归自己所有的 Condition；在途旧 writer 不能
覆盖新的 ready 事实。

四个值的含义是：

| Delivery | 含义 | 可见性 | Route |
|---|---|---|---|
| unclaimed | 没有用户交付 | 隐藏 | 根据池 workload 投影 available/creating/dead |
| claimed | 认领身份已提交，交付进行中或结果未知 | 隐藏 | dead |
| ready | 初始安全交付已完成 | 根据 Release 判断 | 根据当前工作负载能力投影 |
| reserved-failed | 已知失败且按请求策略保留用于诊断 | 隐藏 | dead |

`reserved-failed` 只表示 `reserve-failed-sandbox-for` 场景。失败保留事实与当前 epoch 绑定，并将
绝对到期时间或 `forever` 选择持久化；marker、epoch 和保留期限必须通过同一次条件写提交。该写只
允许从当前 `claimed` 交付发起，Manager 必须先确认对应 quota generation 仍处于 binding 或 active。
随后 Infra 要求 RV 和 epoch 匹配，且不存在匹配的 `DeliveryReady=True` 或已经提交的 cleanup。它与
ready 和 cleanup 按同一 CAS 规则竞争：quota 已关闭或 cleanup 先赢时，保留写不能换用新 RV 救回；
保留写先赢时，普通 terminal 清理必须遵守保留期限。未请求保留的已知失败直接提交 cleanup，
不会经过该值。有限保留到期后由后台清理器提交 cleanup；
`forever` 明确保留到管理员清理，并持续占用 quota。即使 workload 已进入 terminal，保留规则仍然
优先；普通 terminal 清理器不能提前清理它。同一 epoch 的 `reserved-failed` 永远不能转为 `ready`，
重试必须使用新的 epoch。Recycle 最终清除认领身份时，也必须原子清除失败保留事实。

`ready` 只证明初始交付完成，不表示 workload 此后永远可服务。Pause、Resume、升级、Pod 替换或
故障只改变 PauseResume 和 Workload，不把 Delivery 倒退为 claimed。

#### Release

映射器按第一条匹配规则产生 Release。cleanup trigger 是与当前 DeliveryEpoch 绑定的持久化事实；
它一经写入，就不可逆地为该次交付提交释放：

1. DeletionTimestamp、当前 delivery 的 cleanup trigger，或 Phase=Recycling/Terminating：
   `committed`。
2. Phase=Succeeded/Failed：`terminal`。
3. ShutdownTime 存在且本地 `now` 已越过它：`due`。
4. 其他情况：`none`。

`due` 是当前 Observation 按本地时间得出的可逆截止事实，不是不可逆的 release commit。它不改变 owner
可见性、公开 E2B 状态、quota 或 Route；但阻止新的 claim，并在 owner API 中只允许 List、Describe
和 Kill。

截止时间变更以对象版本决定胜负：timeout 更新和 Controller cleanup 都必须带各自观察到的
resourceVersion 与 DeliveryEpoch。更新先提交时，旧 cleanup 冲突；cleanup 先提交时，timeout 更新
冲突。时间到达本身不改变 resourceVersion，因此本提案不承诺严格墙钟截止，也不承诺截止时间前
取得的授权在截止时间后绝对不能赢得 CAS。

`terminal` 表示 workload 已停止但清理尚未提交。它隐藏 Sandbox、拒绝流量并继续保留 quota。除仍在
有效保留期内的 `reserved-failed` 外，后台清理器最终为当前 epoch 提交 cleanup。

`committed` 对同一 delivery 单调。cleanup trigger 持久化后，owner API 隐藏、Route dead、quota
可以异步释放。Recycle 屏障约束的是最终 claim-clear、重新入池和下一次 claim；屏障失败不能让
同一 delivery 恢复服务。

#### PauseResume

PauseResume 使用类型化 desired 和 observed pause facts，不使用整个对象 generation：

1. Delivery=unclaimed、Release=terminal/committed，或 Phase=Succeeded/Failed/Upgrading：`none`。
2. 正在 Resume，或已观察到 paused 但 desired 为 running，或 runtime re-initialization 尚未完成：
   `resuming`。
3. desired 为 paused 但尚未观察到完成：`pausing`。
4. 其他情况：`none`。

Controller upgrade 中的内部唤醒不属于普通 Resume。timeout-only spec 更新不得抹掉进行中的
Pause/Resume。

#### Workload 和有效 revision

Workload freshness 使用实际生效工作负载的内容摘要（effective digest），而不是只 hash
`templateRef` 名称。摘要覆盖：

- 解析后的 PodTemplate；
- VolumeClaimTemplates 和 PersistentContents；
- Runtimes 及所有会改变实际 Pod/runtime 服务能力的 Sandbox 声明输入。

ShutdownTime、PauseTime 等纯策略字段不进入摘要。只有能够证明不会改变安全边界或服务行为的全局
注入配置、feature gate 和外部可变配置才可以排除；其他这类输入必须具有持久化版本，并进入摘要或
单独的服务就绪校验。

当前期望摘要必须与期望输入同步失效，不能只依赖 Controller 上一次异步写入的 status。inline 输入
变化时，权威期望摘要与该次 Sandbox 期望版本原子绑定；`templateRef` 必须指向不可变、内容寻址的
模板版本，或把解析后的模板版本作为 Sandbox 权威期望输入的一部分。引用内容变化但 Sandbox 快照
不变的模型不能产生 `ready`。

Controller 观察到该权威期望版本后，将同一摘要写入 `status.updateRevision`，并把实际 Pod 的
`pod-template-hash` 写入 `status.podInfo.labels["pod-template-hash"]`。Sandbox、SandboxSet 和
Controller 使用同一个不含业务策略的摘要定义。映射器不自行读取可变的 templateRef；它要求权威
期望摘要、Controller 已观察摘要和 Pod 已应用摘要三者相等，而且 Controller 已观察的期望版本对应
当前 Sandbox 期望版本。

对于已经认领的 Sandbox，Sandbox CR 还持久化当前 Pod 的服务就绪事实。该事实绑定 DeliveryEpoch、
`status.podInfo.podUID` 和已应用摘要，并分别证明当前 Pod 的 runtime 初始化、交付 credential、CSI
初始化（如启用）和 TrafficPolicy 数据面保护已经完成。任一绑定不匹配时，旧事实自动失效；Pod
替换、Resume 或升级必须为当前 Pod 重新建立这些事实，不能沿用初始 `DeliveryReady`。

Workload 按第一条匹配规则映射：

1. Phase=Succeeded/Failed：`completed`。
2. Phase=Paused 且 paused fact=True：`paused`。
3. Phase=Running、三份摘要相等、Ready=True、PodUID 和 PodIP 非空，并且 InplaceUpdate 事实明确
   表示当前 Pod 与摘要没有进行中的更新或更新已成功：基础 workload 就绪。Delivery=unclaimed 时
   直接产生 `ready`；已经认领时，还必须有上述匹配当前 epoch 和 Pod 的服务就绪事实，才能产生
   `ready`。
4. Phase=Pending、三份摘要相等，且 `status.podInfo.podUID` 标识当前 Pod：`provisioning`。
5. 其他情况：`unready`。

Ready 缺失、False 或 Unknown，任一摘要或期望版本缺失、不匹配，PodUID 或 PodIP 缺失，
InplaceUpdate 事实缺失、无法归属当前 Pod/摘要或表示失败，已认领 Sandbox 的服务就绪事实不完整，
未知 Phase，或其他不完整状态都不能产生 `ready`。CreationTimestamp 只能在已经证明
`provisioning` 后作为投机候选的时间阈值；时间本身不能证明进展。

#### 合法性不变量

映射器输出必须满足：

- `claimed`、`ready` 和 `reserved-failed` 都具有完整 owner、公开 ID、epoch 和 MutationToken，以及
  与该 epoch 绑定的有效 claim timestamp、固定交付截止时间、quota reservation ID 和 generation；
- `unclaimed` 不具有 owner、公开 ID、claim lock、quota reservation 引用或失败保留事实；
- `reserved-failed` 不能同时具有匹配 epoch 的 `DeliveryReady=True`；
- `Delivery=unclaimed` 和 `Release in {terminal, committed}` 时 PauseResume 为 none；
- `Release=terminal` 对应 Workload=completed；
- `Release=committed` 可以保留任意保守 workload 快照，但 PauseResume 为 none；
- Workload=completed 只与 terminal 或 committed release 共存；
- 非 none 的 PauseResume 不与 provisioning 或 completed 共存；
- Delivery=ready 可以与 paused、unready 或 completed Workload 共存，因为交付完成与当前工作负载能力
  是不同事实。

未知状态取值或无法规范化的组合使 State 校验失败。Infra 返回 internal 或 unavailable；Route dead。

### 3. DeliveryEpoch 和后端隔离校验

当前 claimed Sandbox CR 中的 claim lock 是 DeliveryEpoch 的权威来源。一次交付内 epoch 不旋转；
成功 Recycle 最终清除认领身份时清除它；同一最终转换也清除 quota reservation 引用和失败保留事实。
下一次 claim 必须产生新 epoch。以下 epoch 规则适用于
第一次 claim 写之后的交付操作和结果。未认领池对象没有 DeliveryEpoch；它只能产生不可转发流量的
`available` 或 `creating` Route，其事件以 ObjectKey、UID 和 resourceVersion 排序。

每个后端边界遵守同一协议：

| 阶段 | 契约 |
|---|---|
| 安装 | 新 epoch 的身份与隔离信息已持久化并可验证；安装失败保持不可用 |
| 激活 | 当前 Pod 的 runtime、credential、CSI 和 TrafficPolicy 服务就绪事实全部成立后，以当前 epoch 和 RV CAS 提交 DeliveryReady |
| 使用 | 请求、credential、资源和结果必须匹配当前 epoch；缺失或不匹配时拒绝使用 |
| 撤销 | cleanup 后停止流量和要求安全状态已证明的操作；Recycle 屏障证明旧 epoch 已失效后才清 claim |
| 重启 | 从持久化权威快照恢复；无法恢复当前 epoch 时保持不可用 |

具体边界包括：

- **Sandbox CR 变更：**校验 ObjectKey、UID、RV、owner、公开 ID、claimed marker 和 epoch；冲突后
  不能透明地把原操作重试到新 delivery。
- **Runtime 和 credential：**runtime 安装当前 epoch，只接受匹配的初始化、Browser credential 和
  workload 请求；旧 credential、长连接和迟到的完成结果在 Recycle 隔离屏障内失效。
- **Gateway 请求：**公开 ID 只用于寻址，不是授权凭据。所有发往可 Recycle Sandbox 的流量都必须
  携带绑定当前 epoch 的 credential；Gateway 在转发前同时校验 Route epoch 和 credential epoch。
  未认证流量不能使用本设计的可 Recycle 交付路径。
- **Pod 和 TrafficPolicy：**二者携带相同 epoch；policy CRUD 同时匹配公开 ID 和 epoch；selector
  不匹配、Pod epoch 缺失或 policy 缺失时数据面默认拒绝。
- **Route：**已认领 Route 携带 ObjectKey、UID、RV、公开 ID 和 epoch。权威快照优先于副本增量事件；非当前
  epoch 事件不能更新或删除 Route。未认领事件没有 epoch，只能更新同一 ObjectKey/UID 的池 Route；
  它不能覆盖已认领的公开 ID。多个对象声明同一活动公开 ID 时整体拒绝服务，不能由最后一个事件
  接管。
- **Connect：**Resume 完成后重新取得 Observation，只有 epoch 未变且新 State 仍准入时才连接。

Checkpoint 区分两个 epoch：

- 源 DeliveryEpoch 证明 Snapshot/Checkpoint 由哪一次源交付产生；生产方在开始和完成前都验证源
  epoch；
- Clone 校验来源和 owner，但为目标 Sandbox 创建新的目标 DeliveryEpoch；
- 源 epoch 不与目标 epoch 比较相等；目标 Pod、runtime、Route 和 TrafficPolicy 只使用目标 epoch；
- 与交付绑定的内部 Checkpoint 由 Recycle 屏障隔离；standalone Snapshot 可以在源 Sandbox
  结束后保留。

### 4. Claim 和 Clone

候选必须满足：

| 候选 | 必要事实 |
|---|---|
| 普通候选 | Delivery=unclaimed、Release=none、PauseResume=none、Workload=ready、目标池匹配且未锁定 |
| 投机候选 | Delivery=unclaimed、Release=none、PauseResume=none、Workload=provisioning、目标池匹配、未锁定且投机等待时间已到 |
| 不可选 | 其他任何 Delivery；Release=due/terminal/committed；paused/unready/completed；池不匹配；或已锁定 |

Claim 和 Clone 的运行时顺序是：

1. Manager 校验请求并创建带固定到期时间、reservation ID 和 generation 的持久化配额预留记录。
   reservation ID 与 generation 共同组成“配额预留代次”；关闭后，该代次永久失效。它不同于
   DeliveryEpoch、MutationToken 和流量 access token。claim 绑定与到期回收对同一 quota 记录执行
   CAS，因此只能有一方把它移出 reserved 状态。
2. 赢得 CAS 的 claim 绑定使配额预留代次进入继续占用 quota 的 binding 状态。Infra 的
   第一次 claim 写持久化 owner、公开 ID、claim lock、claimed marker、claim timestamp、reservation
   ID 与 generation，以及由服务端选择的固定绝对交付截止时间。若该写迟到至 generation 已关闭，
   它只能形成隐藏的孤儿写：永远不能通过 ready 准入，随后提交 cleanup，也不能重新激活或
   复用已关闭的 quota generation。
3. Manager 等待当前 Pod、PodUID、期望摘要、已应用摘要和 Ready 条件满足基础 workload 前置，
   然后安装当前 epoch 的 runtime、credential、CSI（如启用）和 TrafficPolicy，并持久化绑定当前
   epoch、PodUID 和摘要的服务就绪事实。
4. Manager 取得新的 Observation，只在 Delivery=claimed、Release=none、Workload=ready、owner、
   公开 ID 和 epoch 仍匹配、对应 quota allocation 仍 active，且没有 cleanup 或失败保留事实时，
   使用该 Observation 的 RV 条件提交 `DeliveryReady=True`。CAS 冲突后必须重新满足完整谓词；不能
   只换成最新 RV 重试。
5. 权威 Route 发布水位包含 ready RV 和对应 running Route 后，Create 或 Clone 才返回成功。任何
   宣称健康的 Manager/Gateway 都必须至少追平该水位；新加入或恢复的副本追平前不进入 readiness。

交付截止时间由服务端固定选择。时间到达后，后台清理器可以把仍无人推进的 claimed 交付视为废弃并
清理。它不等于用户 workload ShutdownTime，也不随请求 heartbeat 续期，也不是严格的激活截止点：
到期本身不改变 resourceVersion；在 cleanup 提交前，仍满足步骤 4 完整谓词的 ready 写可以赢得
CAS。ready 后该时间可以留在对象上并被忽略，避免第三次清理写。

Manager 的 primary 副本通过权威快照查找到期的 claimed 交付。后台清理器与 ready 提交使用同一
RV 和 epoch 竞争：ready 先成功则不再清理；cleanup trigger 先成功则 ready 提交冲突且不能救回。
Sandbox Controller 只执行已经提交的 cleanup，不解释交付截止时间或 DeliveryReady。

失败行为如下：

| 场景 | 结果 |
|---|---|
| quota 绑定前进程崩溃 | 到期回收关闭 reserved generation 并释放 quota |
| quota 绑定后、claim 写前进程崩溃 | quota 收敛器在 binding 截止后关闭 generation；迟到 CR 写保持隐藏并提交 cleanup |
| quota 预留成功但 claim commit 明确失败 | 权威确认 epoch 未持久化后关闭 generation 并释放 quota |
| claim commit 结果未知 | 由 quota 收敛器检查 quota reservation 记录和 Sandbox CR；不能猜测并释放 quota |
| ready 前已知失败且不保留 | 为同一 epoch 提交 cleanup；重试使用新 epoch |
| ready 前已知失败且保留 | CAS 提交与 epoch 绑定的 marker 和绝对到期时间/forever 事实；有限期限到期后 cleanup，forever 由管理员清理 |
| 请求取消 | 使用不受请求取消影响的有界清理；若结果未知则由后台清理器兜底 |
| Manager 在 ready 前崩溃 | 保持隐藏的 claimed 并占用 quota，固定截止时间到期后由后台清理器提交 cleanup |
| ready commit 成功但 Route 发布或响应失败 | 不回滚；返回 unavailable，List/Describe 可发现 ready Sandbox |

本提案不恢复同一 epoch 的部分交付。崩溃或最终失败后的重试使用新的 Sandbox delivery 和 epoch。

Traffic access token 可以只存在于 Create/Clone 的瞬时响应。如果 ready 已提交，但 Route 发布等待
超时、workload 在等待期间失去 ready，或响应丢失，token 不保证可恢复；不自动回滚已提交的交付。
owner 可以通过 List/Describe 找到 Sandbox，再 Kill 并重建。本提案不持久化 token，也不引入幂等
响应存储或 token 重签 API。

### 5. Owner 可见性和公开 API

Manager 推导与调用方无关的可见性：

    ResourceVisible =
        Sandbox exists
        && Delivery == ready
        && Release in {none, due}

API 再执行 owner authorization：

    OwnerVisible = ResourceVisible && Observation.Owner == authenticated caller

List 在 pagination 前过滤 owner 和 OwnerVisible。Describe 与所有单 Sandbox API 使用同一个
Observation；Route 不是存在性或 owner authorization 的权威。单 Sandbox API 总是先校验 owner，
再按下表从上到下应用 State；因此 owner mismatch 不会命中后续 release 行。

| 情况 | 非 Kill owner API | Kill |
|---|---|---|
| NotFound / unclaimed | HTTP 404 | HTTP 204，无操作 |
| claimed / reserved-failed | HTTP 404 | HTTP 204，无操作 |
| ready 但 owner mismatch | HTTP 404 | HTTP 204，无操作 |
| ready + Release=none/due | 应用 State 准入 | 为当前 epoch 提交 release |
| ready + Release=terminal | HTTP 404 | 为当前 epoch 提交 cleanup |
| Release=committed | HTTP 404 | HTTP 204 |
| Observation 无效或后端不可用 | 映射为 internal/unavailable | 不假报资源变更成功 |

`reserved-failed=forever` 只用于管理员诊断；owner API 不暴露它，也不提供清理副作用。

E2B 公开状态保持最小集合：

| OwnerVisible State | E2B 状态 |
|---|---|
| PauseResume=none 且 Workload=ready | running |
| 其他 | paused |

因此 `Delivery=ready, Release=due, Workload=ready` 仍公开为 `running`，但不代表当前可以 Connect。
due 时只准入 List、Describe 和 Kill。

### 6. 操作准入

使用 workload 的操作首先要求 OwnerVisible、有效 MutationToken 和匹配当前 epoch。Release=due 是
独立拒绝条件。

| PauseResume 和 Workload | Pause | Resume | Connect |
|---|---|---|---|
| none + ready | 开始 Pause | 无操作成功 | 连接 |
| none + paused | 无操作成功 | 开始 Resume | Resume 后重新观察并连接 |
| pausing + 任一合法 Workload | 加入并等待 | HTTP 409 | HTTP 400 |
| resuming + 任一合法 Workload | HTTP 409 | 加入并等待 | 等待、重新观察后连接 |
| none + provisioning/unready | HTTP 409 | HTTP 409 | HTTP 500 |

Snapshot、Set timeout、Update network 和 Browser 操作要求 PauseResume=none 且 Workload=ready。
不满足时保持既有公开错误类别：Snapshot 为 HTTP 400，其他三项为 HTTP 500，且不能产生部分变更。

同方向 Pause/Resume 可以加入等待；反方向冲突。MutationToken 冲突后，Manager 必须取得新 Observation，
重新执行 State 准入和 owner authorization，不能把旧授权重试到新 delivery。

### 7. Route

Route 使用与 Infra 相同的 Sandbox CR 映射器，并携带 ObjectKey、UID、resourceVersion 和 PodIP。
已认领 Route 还携带公开 ID 和 DeliveryEpoch；未认领池 Route 没有这两个字段，只能使用内部池键，
不能被 Gateway 按公开地址访问。Route 不携带完整 State 或截止时间。

删除事件或可靠 tombstone 删除 Route。其他对象按第一条匹配规则投影：

| State 和 Route facts | Route.State |
|---|---|
| State 无效 | dead |
| Release=terminal 或 committed | dead |
| Workload=completed | dead |
| Delivery=claimed/reserved-failed | dead |
| Delivery=ready、PauseResume=none、Workload=ready、IP 存在 | running |
| Delivery=ready、PauseResume=pausing 或 resuming | paused |
| Delivery=ready、PauseResume=none、Workload=paused | paused |
| Delivery=ready、Workload=provisioning | creating |
| Delivery=ready 且 Workload=unready | dead |
| Delivery=unclaimed、Workload=ready、IP 存在 | available |
| Delivery=unclaimed、Workload=provisioning | creating |
| 其他 | dead |

表中的投影对 Release=none/due 相同；due 不改变既有 Route。`unclaimed+due` 因候选策略不可 claim，
但仍保持相同 Route 投影。Route `available` 不是候选资格或存在性的权威。

Gateway 只转发 `running`。ready commit 必须进入权威 Route 发布水位后，Create/Clone 才返回。
Gateway 重启后，在取得完整初始快照前不转发流量；副本事件不能覆盖更新的权威 epoch/RV。

### 8. Quota 和后台收敛

Quota 不是 State 维度。配额预留记录是 reserved、binding、active 和 released 状态的权威来源。
claim 绑定与到期回收对同一个配额预留代次执行 CAS；第一次 claim 写把 reservation ID、generation
和 DeliveryEpoch 一起持久化。若 binding 的写入结果未知，quota 收敛器在匹配的 claim 已存在时转为
active；超过 binding 截止时间仍没有 claim 时，关闭 generation 并释放 quota。关闭后才到达的 CR 写
不能重新激活 quota，也不能通过 ready 准入；它保持隐藏并提交 cleanup。该协议在不把 quota 策略
下沉到 Infra 的前提下，同时避免孤儿配额预留和无配额的可见交付。一旦存在匹配的 claim，对应的
binding 或 active generation 就不能独立到期；它只能在某个持久化事实把 Sandbox CR 改为
`Release=committed` 后关闭。因此，并发的 ready 或失败保留 CAS 会因 RV 变化而冲突。

Quota 按下表从上到下判断：

| 条件 | Quota |
|---|---|
| 已绑定 claim 的当前 epoch 为 Release=committed | 可以异步释放，不受 Delivery 值影响 |
| 没有匹配 claim，且（reservation 在到期前仍为 reserved，或 binding 尚未到达自身截止时间） | 保留 |
| 没有匹配 claim，reservation 到期时仍为 reserved，且到期回收赢得 CAS | 关闭 generation 并释放 quota |
| binding 到达自身截止时间 | 结合 Sandbox CR 收敛：有匹配 claim 则转为 active 并保留，否则关闭并释放；迟到 CR 写不能成为 ready 或 reserved-failed |
| 当前 epoch allocation 或 claim 已关联的预留记录存在，且（Delivery=claimed/ready/reserved-failed 或 Release=due/terminal） | 保留 |
| NotFound，且没有未关闭的 reserved、binding 或 active generation | 最终对账为已释放 |

对于与 claim 绑定的当前 epoch allocation，任何能把 Release 映射为 `committed` 的持久化事实都允许
释放 quota；cleanup trigger 是其中一种。未绑定 reservation 则在到期 CAS 关闭配额预留代次后释放。
quota 后端更新可以失败，并由配额对账任务修复。第一次 claim 写结果未知时，quota 收敛器必须检查
quota reservation 记录和 Sandbox CR，再决定激活或关闭 generation；不能因为请求失败就释放。有限
reserved-failed 明确延长 quota 占用；forever retention 明确无限期占用，直到管理员清理。

### 9. 分层职责

| 层 | 负责 | 不负责 |
|---|---|---|
| API | authentication、owner authorization、协议校验、HTTP/E2B 映射 | CR status 解释、Route 存在性、生命周期策略 |
| Manager | 可见性、候选、quota、后台清理、生命周期与能力准入、冲突后编排 | CR Phase/Condition/annotation、HTTP 语义 |
| Infra | Observation、CR 映射、条件后端能力、等待、CAS、epoch 隔离校验 | 调用方认证、HTTP 状态、quota 策略 |
| Controller | 原生 CR/workload 协调、执行 cleanup 和 Recycle barrier | Manager/API 策略、解释 DeliveryReady、依赖 Manager/Infra 实现 |
| Route/Gateway | 共享投影、权威快照、running 流量准入 | Sandbox 存在性、owner authorization、Manager State |

## 实现注意事项

本设计的安全语义只能在以下前置条件全部满足后启用：

- 当前 Recycle 不能证明清除所有旧交付影响，也可能拒绝某些 Sandbox；它尚不满足完整隔离
  屏障。启用条件是：无法证明屏障完成时删除或隔离，而不是重新入池。
- 当前 Manager 和 Gateway 使用进程本地 informer/Route cache，不能保证所有健康副本共享同一
  对外服务快照。启用条件是：具备共同权威发布水位，并让未追平副本退出 readiness。
- 当前 Sandbox Controller 会观察普通 Sandbox status 更新，且 status writer 不能保证多 writer
  optimistic CAS。启用条件是：仅有 DeliveryReady 变化时零入队，并保留其他 writer 拥有的 Condition。
- 当前 ShutdownTime 清理没有同时验证 RV 和 epoch。启用条件是：所有截止时间变更与 cleanup 都
  满足本文的对象版本胜出契约。
- 当前 quota reservation 与 claim 不具备本文的配额预留代次协议。启用条件是：quota 绑定与回收使用
  CAS，已关闭 generation 不能复用，而且 ready 或失败保留提交前存在匹配的 active quota allocation。

新 Manager、Gateway、Controller、quota backend、runtime 和 TrafficPolicy/Pod data plane 不得在
这些前置成立前启用新语义。已认领交付缺失 epoch、DeliveryReady、必需的 workload 摘要或期望
版本，或服务就绪事实时，拒绝流量和相关操作；不回退到 name、UID、公开 ID 或 ownerReference。
本提案不支持 mixed-version 运行，也不定义 legacy backfill 或发布迁移步骤。
