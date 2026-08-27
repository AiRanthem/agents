---
title: Sandbox 查询与 E2B 可见性边界
authors:
  - "@AiRanthem"
reviewers: []
creation-date: 2026-08-26
last-updated: 2026-08-26
status: provisional
---

# Sandbox 查询与 E2B 可见性边界

## 摘要

本提案将已领取 Sandbox 的查询与 E2B 生命周期可见性分开。
`SandboxManager.GetSandbox` 根据 namespace 和 Sandbox ID 找到已领取的 Sandbox，确认它属于请求
用户，然后返回现有的 `infra.Sandbox` 句柄。它不再接收预期 state 字符串，也不再读取
`infra.Sandbox.GetState()`。

查询和所有权授权完成后，所有协议可见性均由 E2B 负责。List 和 Describe 使用同一套 E2B 公开
投影：可见 Sandbox 只能报告为 `running` 或 `paused`，List state 条件匹配投影后的公开状态，所有
可见性过滤都在分页之前完成。Running Phase 但尚未 Ready 的已领取 Sandbox 仍公开为 `running`；
creating、已到期、正在终止、已删除、已完成和不支持的观测均隐藏。因此，对同一次观测，List 中的
Sandbox 与 Describe 具有相同的可见性和公开状态。

其他 endpoint 保持现有对外行为，继续应用各自的操作专用 state 规则。这是一次渐进式边界调整：
`GetState()` 和 `metav1.Object` 继续保留在 `infra.Sandbox` 上，不增加正交的生命周期 Getter，也不
重新设计更广泛的状态模型。

## 背景

当前 Manager 点查同时回答两个无关问题：

1. namespace 和 Sandbox ID 指定的已领取 Sandbox 是否存在，并且是否属于请求用户？
2. 它的聚合 state 是否被当前 E2B endpoint 接受？

第一个问题是后端中立的身份与授权问题。第二个问题是协议策略：Describe、Connect、Delete、
Snapshot 等 E2B 操作对“可见”或“可用”的含义并不相同。把 E2B state 集合传给 Manager，会让通用
查询合同依赖 API 专用状态名称，还会把 state 不匹配伪装成查询失败。

List 还存在另一处不一致。它先按原始聚合 state 过滤，再把 Sandbox 转换成 E2B 响应；Describe
则先应用可见性规则，再把 Running 但未 Ready 的 Sandbox 从内部 `dead` 映射为公开 `running`。
因此，同一个 Sandbox 可能被 Describe 返回，却从无 state 条件的 List 或 `state=running` 结果中
消失。

[上游 E2B OpenAPI schema](https://github.com/e2b-dev/E2B/blob/main/spec/openapi.yml)只定义
`running` 和 `paused` 两种公开 Sandbox 状态。内部 `dead` 等状态不能作为合法兜底。特别是，
ShutdownTime 已经过期的 Sandbox 必须隐藏，不能携带内部状态返回。

### 范围

- 从 `SandboxManager.GetSandbox` 移除预期 state 输入和聚合 state 读取。
- 保持 claimed 查询、namespace 与 Sandbox ID 匹配、所有权授权、查询错误分类和调用方提供查询
  deadline 的现有合同。
- 把每个 E2B 调用方现有的 state 准入移到 E2B 层，不改变该 endpoint 的对外行为。
- 让 List 和 Describe 共用一套失败即隐藏的公开可见性与状态投影。
- 要求 E2B List 使用的 Sandbox 选择结果只包含匹配 namespace 和 owner 的已领取 Sandbox。
- 保持先认证、再验证所有权、最后判断 state 的顺序。

### 非目标

- 改变 `pkg/utils.GetSandboxState`、它的优先级、状态值或 reason 字符串。
- 移除 `infra.Sandbox.GetState()`，或用正交的 readiness、pause、deadline、release 或 delivery
  Getter 取代它。
- 重新定义 Delete、Pause、Resume、Connect、Browser、Network、Set timeout、Snapshot 或
  traffic-token 行为。
- 改变 SandboxSet 或 SandboxClaim 行为，包括其中对 Manager 和 state 的使用。
- 从 `infra.Sandbox` 移除 `metav1.Object`，或禁止上层通过该接口读取 Sandbox 语意。
- 设计另一套 Infra 实现、迁移行为、陈旧数据兼容或完整的跨后端状态模型。
- 改变 Sandbox ID 分配或现有的歧义 ID 查询行为。

## 设计终态

### 职责边界

查询、公开发现和操作准入是相互独立的决策：

| 决策 | 责任方 | 合同 |
|---|---|---|
| 找到已领取 Sandbox | Infra | 匹配 namespace 和公开 Sandbox ID；区分不存在、歧义和无法确定的失败 |
| 验证所有权 | Manager | 将请求用户与 `infra.Sandbox` 暴露的 owner metadata 比较 |
| 隐藏后端诊断交付 | E2B | 完成不会泄露所有权的查询后，reserved-failed Sandbox 仍不可发现 |
| 投影公开可见性与状态 | E2B List 和 Describe | 只返回 E2B 可见的 `running` 或 `paused` Sandbox |
| 准入操作 | 对应 E2B endpoint 与 Infra capability | 应用 endpoint 兼容规则，再由操作执行权威校验 |

```mermaid
flowchart LR
    Request[E2B 请求] --> Manager[Manager GetSandbox]
    Manager --> Infra[Infra claimed 查询]
    Infra --> Owner[Manager 所有权授权]
    Owner --> Policy[E2B endpoint 策略]
    Policy --> Response[公开响应或操作]
```

E2B model、HTTP status 和协议 state 集合都不进入 Manager 或 Infra。E2B 继续接收现有的中立
`infra.Sandbox` 句柄，可以通过该接口读取 Sandbox 语意，但不能转换为或直接读取具体 Sandbox CR。

### Manager 点查合同

`SandboxManager.GetSandbox` 接收 context、请求用户和中立的 Infra 查询选项，不再接收预期 state
参数。它的成功结果只表示：

> 与请求 namespace 和 Sandbox ID 匹配的已领取 Sandbox 存在，并且属于请求用户。

它不表示 Sandbox 仍然 live、健康、Ready、公开可见或可执行某项操作。

查询保留以下规则：

1. 空用户在查询前被拒绝。
2. Infra 只找到与 namespace 和 Sandbox ID 匹配的已领取 Sandbox。
3. 明确不存在继续映射为 Manager not-found。ID 歧义继续作为不透明的 not-found，同时保留诊断
   cause。其他 Infra 失败继续映射为 internal error。
4. Manager 只在查询成功后验证 owner metadata；不匹配继续返回 not-allowed。
5. Manager 不读取、不记录、不筛选聚合 state 或 reason，直接返回 Sandbox。

Infra 查询可能在 context 有效期间等待缓存收敛，因此调用方仍需提供 deadline。移除 state 校验
不会削弱查询身份或所有权授权。

### E2B 查询与操作策略

Manager 返回属于请求用户的 Sandbox 后，E2B 应用 reserved-failed 隐藏和当前 endpoint 自己的
state 规则。state 不匹配不再由 Manager 产生 health error；除下文明确规定的 List 和 Describe
变化外，其他 endpoint 现有的 E2B status 类别、消息和信息披露边界保持不变。

下表说明每个消费者为何需要生命周期信息。这些规则只描述本次增量中的 endpoint 合同，不定义新的
全局 `claimed`、`live` 或 `visible` 概念。

| 消费者 | 所需生命周期信息 | 本提案合同 |
|---|---|---|
| Describe | 公开可发现性与公开状态 | 使用 List/Describe 共享投影 |
| List | 公开可发现性、公开状态和 metadata 条件 | 在过滤和分页前使用共享投影 |
| Delete | 幂等清理准入 | 保持现有清理专用规则；不复用公开发现规则 |
| Pause | 现有 API 兼容校验，随后执行权威 Pause 准入 | 保持现有对外行为；`Sandbox.Pause` 仍是权威判断 |
| Resume | 现有 running-or-paused 查询兼容，随后执行权威 Resume 准入 | 保持现有对外行为；`Sandbox.Resume` 仍是权威判断 |
| Connect | 区分已经 running 与 paused/resuming，并拒绝现有 non-live 场景 | 保持现有响应与 Resume 行为 |
| Browser | 现有 live 查询兼容与实际 runtime 请求 | 保持现有行为 |
| Network update | 现有 live 查询兼容与控制面变更 | 保持现有行为 |
| Set timeout | 现有 running-only deadline 变更 | 保持现有行为 |
| Create Snapshot | 现有 running-only Checkpoint 准入 | 保持现有行为 |
| Traffic-token refresh | Route 所有权、traffic-auth 开关和现有 running-or-paused 准入 | 只适配无 state 的 GetSandbox 签名；保留 Manager 内的独立校验 |

公开发现不能成为所有操作共用的准入条件。例如 Delete 是幂等清理 API，而 Connect 必须在返回已
running Sandbox 与恢复 paused Sandbox 之间作出选择。Describe 可见性变化不能隐式改变这些操作。

### List 与 Describe 共享投影

List 和 Describe 计算同一套 E2B 投影，结果要么是公开状态，要么是“不可见”。该投影失败即隐藏：

| `infra.Sandbox.GetState()` 返回的聚合观测 | E2B 投影 |
|---|---|
| `running` | 可见，公开为 `running` |
| `paused` | 可见，公开为 `paused` |
| `dead`，reason 为 `RunningResourceClaimedButNotReady` | 可见，公开为 `running` |
| `creating` | 不可见 |
| `dead`，reason 为 `ShutdownTimeReached` | 不可见 |
| `dead`，reason 为 `ResourceSucceeded`、`ResourceFailed`、`ResourceTerminating` 或 `ResourceDeleted` | 不可见 |
| 其他聚合 state 或不支持的 `dead` reason | 不可见 |

失败即隐藏可以防止新增内部 state 或 reason 在明确公开语意之前泄露到 E2B 响应。唯一的特殊映射是
现有的 Running 但未 Ready 场景：后端 Phase 仍表示同一次用户交付，Describe 已经把它公开为
`running`。

投影结果同时包含可见性和公开状态。同一次请求内，过滤与响应转换复用该结果，而不是分别计算
可见性与状态。这样，ShutdownTime 等时间边界不会先通过可见性校验，随后又在同一个响应中产生
非法 `dead`。当 Sandbox 并发变化时，本提案不承诺不同请求之间使用同一快照。

#### Describe

Describe 先完成 claimed、namespace、Sandbox ID 和 owner 安全查询。reserved-failed 或不可见结果
返回 not found；可见结果严格使用共享投影产生的公开状态。

因此，即使到期 Sandbox CR 仍存在并保留 claimed 身份，Describe 也返回 not found。Describe 永远
不会返回 `dead`、`creating`、`available` 或其他内部状态。

#### List

E2B List 使用的选择结果在合同上只包含匹配请求 namespace 和 owner 的已领取 Sandbox。claimed 是
Infra 提供的选择不变量，不由 E2B 解释具体 label，也不需要增加 `IsClaimed()` Getter。

对于每个选择出的 Sandbox，List：

1. 隐藏 reserved-failed 和不可见结果；
2. 用投影后的 E2B 状态匹配请求中的 `state`；
3. 应用现有 metadata 条件；
4. 对剩余结果分页。

未提供 state 条件时，两种公开状态都可返回。`state=running` 包含 Running 但未 Ready 的 Sandbox，
因为其公开投影是 `running`；`state=paused` 只包含投影为 `paused` 的结果。List 不接受内部状态名称。

可见性、公开 state 过滤和 metadata 过滤全部先于分页。因此，page limit 与 next token 描述的是
公开可见且匹配条件的结果集，而不是原始后端对象。

对于同一个已领取、owner 匹配、ID 唯一并且观测相同的 Sandbox：

- 当且仅当它在应用 metadata 条件和分页前符合无 state 条件 List 时，Describe 才成功。
- Describe 返回的 state 与 List 返回的 state 相同。
- 使用该返回 state 过滤 List 时会包含它。

### Infra 接口范围

本次增量不需要增加 `infra.Sandbox` Getter：

- claimed 状态由点查与 List 选择合同保证，`IsClaimed()` 会重复查询语意。
- 现有 `GetState()` 提供 E2B 兼容与共享公开投影暂时需要的聚合观测。
- Pause 与 Resume 已经以操作 capability 形式存在，其实现执行权威校验。
- 现有 timeout、route、request、checkpoint、network 和 metadata 方法已经提供其他 endpoint 所需
  信息。
- `metav1.Object` 继续嵌入，可以继续通过 `infra.Sandbox` 暴露 metadata。

`IsVisible()` 或 `IsLive()` Getter 会把 E2B 策略编码进协议中立的 Infra 接口。当后续提案移除另一个
`GetState()` 消费者时，`IsReady()` 或结构化 pause 状态可能有用；但本次从 Manager 移除 state
过滤并统一 List/Describe 不需要它们。

### 不变量与失败行为

- Manager 点查成功只表示 claimed 身份与所有权，不表示生命周期准入。
- Manager 不接受 E2B state 名称，`GetSandbox` 永远不调用 `GetState()`。
- 认证先于所有权授权；所有权授权先于任何依赖 state 的 E2B 判断或诊断信息披露。
- List 和 Describe 只返回 `running` 或 `paused`。
- List 和 Describe 共用一套失败即隐藏的投影，包括 Running-but-not-Ready 特例和到期隐藏。
- List 在分页前过滤投影后的公开状态。
- 其他 endpoint 不继承 List/Describe 可见性，保持现有公开行为。
- 上层只通过 `infra.Sandbox` 读取 Sandbox 语意，不直接依赖具体 Sandbox CR。
- Infra 选择继续使用 informer；本设计不引入 APIReader List。

## 备选方案

### 在 Manager 中保留预期 state

这会继续混合职责，并让后端中立查询依赖 E2B state 词汇。

### 把当前 state 集合复制成新的全局 E2B 可见性规则

同一规则无法同时表达公开发现、幂等清理、runtime 访问、Resume 行为和 Checkpoint 准入，只会在另一
层继续保留原有混淆。

### 继续按原始聚合 state 过滤 List

这会让 Running 但未 Ready 的 Sandbox 可被 Describe 查询，却无法出现在 `state=running` List 中；
响应转换也可能与过滤结果不一致。

### 现在增加正交生命周期 Getter

readiness、pause 转换、到期、release 和 workload capability 是更大状态重构中的有用维度。在另一个
当前消费者真正需要它们之前就增加这些 Getter，会扩大本次增量，并产生尚无跨实现需求的接口合同。

### 把 E2B 可见性放进 Infra

这会要求 Infra 理解 E2B 公开状态和发现策略，破坏后端中立边界。

## 风险

- 后续 Manager 调用方可能把查询成功误解为 live Sandbox。查询结果已经明确限制为 claimed 身份与
  所有权；每个 use case 必须自行负责后续准入。
- 新增内部状态可能暂时从 List 和 Describe 隐藏。这是刻意的失败即隐藏行为，直到其 E2B 投影得到
  明确定义。
- 迁移现有 endpoint 校验时可能意外改变 status 或消息优先级。除明确规定的 List 和 Describe 变化
  外，当前对外行为属于规范合同。
- List 与 Describe 在两个并发请求中仍可能因观测到不同后端版本或时间而不同。保证只适用于相同
  观测，不跨时间成立。
- `GetState()` 仍是 E2B 中的聚合兼容依赖。本提案只收窄一个边界，不宣称完成更广泛的状态拆解。
