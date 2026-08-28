---
title: Sandbox 查询、运行状态与 E2B 可见性边界
authors:
  - "@AiRanthem"
reviewers: []
creation-date: 2026-08-26
last-updated: 2026-08-28
status: implementable
---

# Sandbox 查询、运行状态与 E2B 可见性边界

## 摘要

本提案把 Sandbox-ID 请求时需要回答的问题拆成三个互不替代的事实：点查与 owner 回答“对象是否
存在、属于谁”，`GetVisibility()` 回答“当前用户交付是否仍可见”，`GetOperationalState()` 回答
“底层 Sandbox 现在处于哪种运行或转换状态”。Manager 点查不再接受 state；E2B API 只有在完成
owner 授权并确认 `Visible=true` 后，才投影公开 state 或判断当前操作能否执行。

每次用户交付仍以 `agents.kruise.io/lock` 作为 epoch，并以匹配的
`agents.kruise.io/delivered-lock` 作为持久化完成标记。Create 的第一次写入保持交付不可见，并用
`ShutdownTime` 限制交付时间；全部后处理成功后，Manager 通过 Infra 条件 Patch 原子提交交付和
最终生命周期时间。Create、Resume 和 Connect 都受统一的 10 分钟服务端请求上限约束。

`GetOperationalState()` 返回协议中立的类型值：`Provisioning`、`Serving`、`Pausing`、`Paused`、
`Resuming`、`Upgrading`、`Recycling`、`Terminating`、`Completed`、`Unavailable` 或 `Unknown`。
它不是存在性、可见性、配额、池候选或 Route 的完整读取面。`Unavailable` 表示已经识别当前运行
阶段，但已知不能正常服务；`Unknown` 表示当前观测无法被可靠解释。

E2B 只公开 `running` 和 `paused`：可见且 `Serving` 的 Sandbox 映射为 `running`，其他所有可见
OperationalState 统一映射为 `paused`。Pause、Resume、Connect 等操作使用明确的状态机；Manager
负责协议中立的操作策略，Infra 在底层操作提交前对同一 delivery 作权威重验。一次 Getter
观测不是操作锁。

Route state、Route Store 及 deletion fence 保持现有独立协议，不与 OperationalState 相互转换。
迁移计划按消费者职责拆分：API 和 Manager 退出聚合 `GetState()`、原始 Phase 与 Sandbox CR 业务
事实，quota、pool、wait 和 recycle 分别使用自己的中立合同。迁移终态不要求
`GetSandboxState` 从仓库彻底消失，但它不能再进入 API、Manager 或中立 `infra.Sandbox` 边界。

## 背景

现有领取和克隆流程在等待 Ready、初始化 runtime、处理凭证、执行 CSI mount 和创建 E2B
TrafficPolicy 之前，就已经持久化 owner、Sandbox ID 和 lock。只凭 claimed 或 lock 判断公开存在，
会让一次尚未完成、最终可能失败的交付提前出现在 List、Describe 或其他 Sandbox-ID 操作中。

另一方面，Manager 点查目前还会按调用方传入的 state 集合筛选对象。对象已经存在且属于当前用户，
但因 Ready 波动、到期或状态转换不符合某个 endpoint 的集合时，筛选失败可能被映射成 `404`。
Sandbox route 缓存也不能作为对象存在性的依据：route 缺失可能只是运行状态或投影结果，不能证明
informer 中没有对应的已领取 Sandbox。

这些问题需要不同的事实：

1. 查询回答指定 Sandbox ID 对应的已领取对象是否存在，以及它属于谁。
2. delivery 提交回答该 epoch 是否已经完整交付。
3. Visible 回答该交付现在是否仍处于 E2B 操作范围。
4. OperationalState 回答底层当前运行状况。
5. endpoint 策略与 Infra capability 共同回答当前操作是否能够执行并安全提交。

`pkg/utils.GetSandboxState` 是聚合兼容状态，不是持久化存在性或稳定的操作合同。它会因删除、
ShutdownTime 到期、终态 Phase 或 Running 但未 Ready 等不同原因返回 `dead`，也会把多个转换阶段
压缩为 `paused`。因此，本提案既不把 `dead` 等同于对象不存在，也不再让聚合 state 决定
not-found 或操作能力。

新的 OperationalState 只标准化底层运行事实。它有意不携带 owner、Visible reason、Pod IP、
Route 凭证、配额占用、池身份、generation 或条件 reason。这些事实由各自的查询、快照或 capability
负责，避免再次形成一个同时回答所有问题的聚合状态。

[上游 E2B OpenAPI](https://github.com/e2b-dev/E2B/blob/f0facc5dbcf93067326745e1597b05311c0174ea/spec/openapi.yml)
只允许 `running` 和 `paused` 作为公开 Sandbox state，并为 Create、Resume 和 Connect 声明了
`504 Backend timeout`。本提案只使用每个 endpoint 已声明的 response，不扩展上游合同。

本提案区分两类授权拒绝。**无权**表示调用方对动作本身没有权限，例如 team-scoped API key 请求
admin-only 动作；只要该判断不读取目标对象，并对任意 Sandbox ID 都给出相同结果，它不会额外透露
对象存在性，可以使用 `401`。**越权**表示调用方本可执行该动作，但目标属于其他用户；若它与实际
不存在返回不同响应，就会确认该 ID 存在。所有 Sandbox-ID owner mismatch 因此固定使用 `404`。
同 owner 对象的 Visible 或操作准入失败不属于这两类：调用方已经有权知道自己的对象存在，按
endpoint 的既有 response 表达即可。

### 范围

- 将 Manager 的 Sandbox 点查收窄为 informer 中的 claimed 身份、namespace、Sandbox ID 和 owner
  查询，不再接收或读取预期 state。
- 为 Claim 和 Clone 共用的 Create 交付增加 epoch 匹配的持久化完成标记。
- 为 `infra.Sandbox` 增加协议中立的 Visible 观测，并将其作为所有 Sandbox-ID endpoint 的共同
  前提。
- 为 `infra.Sandbox` 增加 typed OperationalState 观测，由 Infra 将底层事实统一投影为稳定状态。
- 统一 List、Describe 和其他 Sandbox-ID endpoint 的动作权限、查询、所有权、Visible、
  OperationalState 与操作判断顺序，并以是否披露对象存在性作为 `401` 与 `404` 的边界。
- 定义 Pause、Resume、Connect、Network、Set timeout、Snapshot、Browser 和 traffic-token refresh
  的状态准入，以及操作提交前的权威重验边界。
- 为 E2B 业务请求设定一个集中定义的 10 分钟服务端硬上限，并在上游合同允许时映射为 `504`。
- 保留 Controller 的 ShutdownTime 删除与 recycle 清理职责，但不让 Manager 的删除成功依赖
  Controller 已经完成 recycle。
- 原生 E2B 路径和定制前缀路径遵循相同合同。
- 定义从聚合 `GetState()` 迁移到职责专用合同的策略和最终边界。

### 非目标

- 改变 Route state 的值、投影规则、Store 顺序、deletion fence 或流量转发协议。
- 让 OperationalState 承担 owner、Visible、配额、池候选、Route、endpoint 地址或完整诊断读取面。
- 要求 Sandbox Controller 或其他独立 Controller 依赖 sandbox-manager Infra；Controller 继续直接
  维护自己拥有的 CR 状态机。
- 增加 `DeliveryDeadline` CR 字段；临时 delivery 截止时间复用 `ShutdownTime`。
- 重新定义 gateway route、代理流量准入或 Controller 对 workload 健康度的判断。
- 为 informer 延迟、时钟偏差或跨副本一致性增加协调协议。本提案以每个副本当前 informer 观测为准，
  接受跨副本的短暂不一致。
- 使用 APIReader List 或用 route Store 代替 informer Sandbox 查询。
- 改变 Infra 点查已有的 route polling hint 或 APIReader Get freshness fallback；它们不能成为
  Sandbox 存在性或 owner 的权威，但是否保留其内部刷新机制不属于本提案。
- 自动删除或回收处于 `Succeeded`、`Failed` 的 Sandbox。
- 设计旧 delivery 数据迁移、lock-only 兼容兜底或另一种 Infra 后端。
- 改变现有歧义 Sandbox ID 失败即隐藏的查询行为。
- 对 cache 作与本提案状态迁移无关的全面重构；只迁出当前由 cache 解释的 Sandbox 业务状态判断。

## 设计终态

### 职责边界

| 决策 | 责任方 | 合同 |
|---|---|---|
| 认证请求 | E2B API | 验证调用方身份，不以 route 是否存在推断 Sandbox 是否存在 |
| 验证动作权限 | E2B API | 在 endpoint 需要时作与目标对象无关的权限判断；拒绝时使用 `401` |
| 查询已领取 Sandbox | Infra | 从 informer 匹配 namespace 和公开 Sandbox ID，区分不存在、歧义和内部失败 |
| 验证所有权 | Manager | 使用 Sandbox owner metadata；不读取 state 或 Visible；API 将 mismatch 隐藏为 `404` |
| 持久化 delivery | Manager 与 Infra capability | 以 lock epoch 和条件 Patch 提交完整交付 |
| 计算 Visible | Infra Sandbox | 从协议中立的持久化事实返回布尔值和稳定 reason |
| 计算 OperationalState | Infra Sandbox | 将底层运行事实投影为 typed 状态，不泄漏 Sandbox CR 模型 |
| 编排生命周期操作 | Manager | 使用 OperationalState 表达协议中立策略，把底层原子读写交给 Infra |
| 映射 HTTP 与 E2B state | E2B API | 先应用 Visible，再按 OperationalState 作公开投影和 endpoint 专用准入 |
| 提交底层操作 | Infra capability | 在最新观测上重验 delivery 身份和运行状态，再执行、join 或拒绝操作 |
| 维护 Route 协议 | Sandbox Route | 保持现有 Route state、Store 顺序与 deletion fence，不消费 OperationalState |
| 处理超时与 recycle | Sandbox Controller | 删除到期 Sandbox，完成 recycle 并清除上一 delivery 的数据 |

```mermaid
flowchart LR
    Request[E2B Sandbox-ID 请求] --> Auth[认证]
    Auth --> Permission[动作权限（如有）]
    Permission --> Lookup[Informer claimed 查询]
    Lookup --> Owner[所有权授权]
    Owner --> Visible[Visible 门槛]
    Visible --> Operational[OperationalState]
    Operational --> Projection[E2B state 投影]
    Operational --> Admission[操作准入]
    Admission --> Capability[Infra 权威重验与提交]
    Projection --> Result[公开响应]
    Capability --> Result
```

Sandbox-ID 认证中间件只认证调用方，不再通过本地 Route Store 预判 Sandbox 是否存在或验证 owner；
所有 Sandbox-ID handler 都由共同的 claimed lookup 与 owner 检查承接该职责。Route Store 可以继续
服务 gateway 和路由投影，但 route 缺失、`dead` route 或尚未同步的 route 都不能抢先把一个
Sandbox-ID 请求判为 not-found。

### Manager 点查合同

`SandboxManager.GetSandbox` 接收 context、请求用户和协议中立的查询选项。成功结果只表示：

> informer 中存在与 namespace 和 Sandbox ID 匹配的已领取 Sandbox，并且它属于请求用户。

它不表示 Sandbox 已完成交付、仍然 Visible、健康、Ready 或允许当前操作。点查遵循以下规则：

1. 空用户在查询前被拒绝。
2. Infra 只选择 claimed 且匹配 namespace 与 Sandbox ID 的对象。
3. 明确不存在映射为 Manager not-found；歧义 ID 对外同样隐藏为 not-found，但保留内部 cause；
   其他查询失败映射为 internal error。
4. Manager 在查询成功后验证 owner；不匹配返回内部 not-allowed，E2B API 将其与实际不存在映射为
   相同 `404`。
5. Manager 不读取、不记录、不筛选 OperationalState、聚合 `GetState()` 或 Visible reason，直接返回
   `infra.Sandbox`。

认证和点查不能依赖本地 Route Store 的 owner 映射。E2B 在取得已授权 Sandbox 后才读取 Visible 和
其他内部诊断，因此其他用户无法通过错误差异探测对象。动作权限检查若存在，必须只依赖调用方、
endpoint 和不读取 Sandbox 的请求事实；一旦需要解析目标对象，就属于 owner 或操作准入，不能用
前置 `401` 绕过隐藏规则。

### Delivery epoch 与提交标记

每次 Claim 或 Clone delivery 使用一个非空 lock string。该值已经唯一标识一次配额与领取尝试，本
提案直接把它作为 delivery epoch，不再生成第二套 epoch。

| 持久化事实 | 含义 |
|---|---|
| `agents.kruise.io/lock` | 当前 delivery epoch |
| `agents.kruise.io/delivered-lock` | 已完成交付的 epoch；必须与 lock 完全相等 |
| `agents.kruise.io/cleanup=true` | 当前 delivery 已提交清理，不可逆地结束 Visible |
| `Spec.ShutdownTime` | delivery 期间的硬截止时间，交付后则是正常生命周期截止时间 |
| `Spec.PauseTime` | 只在交付完成时提交的正常 auto-pause 截止时间 |

`delivered-lock` 是系统拥有的 annotation，不能由 E2B metadata 输入设置。仅有 claimed、owner、
Sandbox ID 或 lock 都不表示 delivery 已完成。

#### 第一次持久化写：领取但不交付

Claim 的 Update/Create 和 Clone 的 Create 在同一次持久化写中：

- 写入本次 lock epoch、owner、claimed 身份和 Sandbox ID；
- 删除来自上一 delivery 的 `delivered-lock` 和 `cleanup`；
- 将 `PauseTime` 置空；
- 将本次 API 请求的绝对截止时间写入 `ShutdownTime`；
- 保持 `Visible=false`。

同一 epoch 的内部重试不得把该临时 `ShutdownTime` 向后延长。只有开始新的 delivery、生成新的
lock epoch 时，才能建立新的 10 分钟截止时间。

#### 后处理与最终交付

Create 的 delivery 完成条件包括成功返回前所需的全部工作：等待 Sandbox Ready、runtime 初始化、
交付所需的凭证与 token 处理、CSI mount、安全规则和网络配置，以及需要时创建 TrafficPolicy。任一
步骤失败，都不能写入 `delivered-lock` 或返回成功。

全部后处理完成后，E2B API 调用 Manager 的 delivery-commit use case；Manager 再通过协议中立的
Infra capability 对同一 Sandbox 执行带 resourceVersion 乐观锁的条件 Patch。TrafficPolicy 仍是
Create 成功前的 API 层后处理，不下移到 Manager 或 Infra；API 也不直接写 Sandbox CR。该提交要求
对象仍是同一 epoch、没有开始删除或 cleanup，并在一次原子写中：

- 写入 `delivered-lock = lock`；
- 把临时 `ShutdownTime` 替换为从实际交付时刻计算的最终生命周期值；
- 写入对应的最终 `PauseTime`；
- 对 never-timeout delivery 清除临时 `ShutdownTime`，并按请求保持最终 deadline 为空。

Create 只在该 Patch 成功后返回 `201`。最终 Patch 不得忽略 resourceVersion 后覆盖 Controller 或
其他并发写入；冲突、对象删除、epoch 改变或 context 到期都表示本次 delivery 未提交。临时
deadline 导致的删除或请求到期按下文返回 `504`；无法分类为该超时的条件冲突或持久化失败使用
Create 已声明的 `500`，不得返回 `201` 或 `404`。

Create 失败后为排障保留的 reserved-failed Sandbox 不具有特殊的存在性语义。它没有成功提交本次
delivery，因 Phase 或缺少匹配 marker 得到 `Visible=false`；reserved-failed label 本身不得再触发
`404`。

#### Controller 删除优先

临时 `ShutdownTime` 到期后，Controller 可以直接删除尚未交付的 Sandbox，不需要识别额外的
DeliveryDeadline。若 Controller 在最终 Patch 前成功删除对象，Patch 必须失败，Create 以 Manager
`ErrorTimeout` 返回 `504`，公开 message 为：

> sandbox creation timed out; the sandbox was deleted before it became available

API 不把该失败伪装成 `404`，也不返回一个未提交的 Sandbox。Controller 对 `Succeeded` 和
`Failed` Phase 保持现有行为：它们可以不因 ShutdownTime 自动删除，但始终 `Visible=false`。

### 统一 API 请求上限

E2B API 层使用一个集中定义的 `MaxAPIRequestDuration = 10m` 作为业务请求的服务端硬上限。每个
请求在入口建立一个绝对 deadline；已有更早 deadline 时使用更早值，内部步骤不得逐段重新获得完整
10 分钟。

- Create 使用该 deadline 作为 delivery timeout 和第一次写入的临时 `ShutdownTime`。
- Resume 与 Connect 从请求 context 继承同一上限，Manager 和 Infra 不依赖 API 常量。
- 已有更短的操作级 timeout 继续生效。
- 客户端扩展指定的更长阶段 timeout 以及用于表示服务端不设阶段上限的内部值，都不能把整个请求
  延长到 10 分钟以后。
- health、Prometheus metrics 和进程 shutdown 不属于该业务请求上限。

Create、Resume 和 Connect 的硬超时映射为其 OpenAPI 已声明的 `504`。其他 endpoint 若未声明
`504`，硬超时映射为已声明的 `500`，不增加新的 response code。

### Visible 合同

`infra.Sandbox.GetVisibility()` 返回 `(visible bool, reason string)`。它只读取当前
`infra.Sandbox` 已携带的单次 Sandbox 观测和当前时间，不执行 Kubernetes 读写。点查内部如何取得
或刷新该观测保持现状；Visible 不发起第二次读取。调用方按照下列优先级取得唯一 reason：

| 优先级 | 条件 | Visible | reason |
|---:|---|---:|---|
| 1 | `DeletionTimestamp` 已设置 | false | `DeletionStarted` |
| 2 | `agents.kruise.io/cleanup` 精确等于 `"true"` | false | `CleanupCommitted` |
| 3 | 当前时间已越过非空 `ShutdownTime` | false | `ShutdownTimeReached` |
| 4 | Phase 为 `Succeeded` | false | `ResourceSucceeded` |
| 5 | Phase 为 `Failed` | false | `ResourceFailed` |
| 6 | Phase 为 `Terminating` | false | `ResourceTerminating` |
| 7 | lock 缺失或为空 | false | `DeliveryEpochMissing` |
| 8 | delivered-lock 缺失或为空 | false | `DeliveryNotCommitted` |
| 9 | delivered-lock 与 lock 不相等 | false | `DeliveryEpochMismatch` |
| 10 | 以上条件均不成立 | true | `Delivered` |

`cleanup-enabled` 不参与计算；它只表示 Controller 是否支持 recycle。任何受信任内部写入一旦提交
`cleanup=true`，当前 delivery 就立即且不可逆地结束 Visible，无论 Controller 是否启用、开始或
完成 recycle。其他 cleanup 值不结束 Visible。

Ready、`PauseTime` 和其他 Phase 不参与 Visible。Visible reason 只用于授权后的结构化日志和内部
审计，不进入公开 response，也不得记录 lock 或 delivered-lock 的实际值。每个 Sandbox-ID endpoint
在所有权授权后记录一次结果；List 逐对象过滤时不产生逐对象日志。

### OperationalState 合同

`infra.Sandbox.GetOperationalState()` 返回一个 `OperationalState` 类型值。它只解释当前
`infra.Sandbox` 已携带的单次底层观测，不执行 Kubernetes 读写，也不返回 backend reason。状态名称
描述“现在发生了什么”，不编码 E2B state、HTTP status 或某个操作是否允许。

| OperationalState | 含义 |
|---|---|
| `Provisioning` | 底层资源尚未进入可服务的运行阶段 |
| `Serving` | Sandbox 已满足正常对外服务所需的运行、Ready、地址和 runtime 初始化条件 |
| `Pausing` | Pause 已成为目标，但底层尚未稳定暂停 |
| `Paused` | 底层已稳定暂停 |
| `Resuming` | Resume 已成为目标，但底层尚未恢复到 `Serving` |
| `Upgrading` | 正在执行 recreate、in-place 或其他已识别的升级过程 |
| `Recycling` | 正在清理上一 delivery，并准备返回池中 |
| `Terminating` | 持久化删除已经开始，或底层已进入终止阶段 |
| `Completed` | 底层已明确成功结束或失败结束，不会继续提供当前服务 |
| `Unavailable` | 当前阶段能够被识别，但已知至少一个服务前提不满足 |
| `Unknown` | 当前观测不属于任何已支持组合，无法可靠判断底层正在做什么 |

`Unavailable` 与 `Unknown` 不合并。前者确认这是一个已识别的运行态观测，例如 Running 但未 Ready、
缺少 endpoint 或 runtime 初始化未完成；后者表示出现了新 Phase、矛盾事实或当前映射不认识的组合。
两者都对操作失败即关闭，但区分后可以让上层判断“暂时不可服务”和“状态解释能力不足”。

Sandbox CR Infra 按以下顺序应用第一条匹配规则，保证每次观测只产生一个结果：

| 优先级 | Sandbox CR 观测 | OperationalState |
|---:|---|---|
| 1 | `DeletionTimestamp` 已设置，或 Phase 为 `Terminating` | `Terminating` |
| 2 | Phase 为 `Succeeded` 或 `Failed` | `Completed` |
| 3 | Phase 为 `Recycling` | `Recycling` |
| 4 | Phase 为 `Upgrading`，或 in-place update 明确处于进行中 | `Upgrading` |
| 5 | Phase 为空或为 `Pending` | `Provisioning` |
| 6 | Phase 为 `Paused`，但 Paused condition 尚未为 `True` | `Pausing` |
| 7 | Phase 为 `Paused`、Paused condition 为 `True`，且 `Spec.Paused=true` | `Paused` |
| 8 | Phase 为 `Paused`、Paused condition 为 `True`，且 `Spec.Paused=false`；或 Phase 为 `Resuming` | `Resuming` |
| 9 | Phase 为 `Running`，且 `Spec.Paused=true` | `Pausing` |
| 10 | Phase 为 `Running`、`Spec.Paused=false`，且已识别为 resume 后 runtime 初始化仍在等待 | `Resuming` |
| 11 | Phase 为 `Running`、`Spec.Paused=false`，Ready 为 `True`、endpoint 非空，并且所需 runtime 初始化不存在或已成功 | `Serving` |
| 12 | 其他 Phase 为 `Running` 的观测 | `Unavailable` |
| 13 | 其他未支持或相互矛盾的观测 | `Unknown` |

“resume 后 runtime 初始化仍在等待”要求存在本次 resume 已完成的明确事实，同时
`RuntimeInitialized=False` 且 reason 为已识别的 Pending。`RuntimeInitialized` 缺失只对不发布该
条件的 backend 或历史对象视为中性；一旦 backend 发布该条件，只有 `True` 才满足 `Serving`。

OperationalState 是观测，不是操作锁。Manager 可以用它选择操作策略或提前拒绝明显冲突，但真正
改变底层状态的 Infra capability 必须在提交前重新确认：对象仍是同一 UID 和 delivery epoch、
Visible 仍未结束，并且最新运行状态仍允许该动作。同一动作已经进行时加入现有等待；已经到达目标
状态时幂等成功；相反动作或不允许的状态返回 typed conflict。等待过程也必须绑定 UID 和 delivery
epoch，不能只用 namespace/name 识别对象。

### E2B 查询、state 与操作

所有 Sandbox-ID endpoint 使用相同的判断顺序：

1. 认证调用方；
2. endpoint 如有动作级权限，先作与 Sandbox 存在性无关的检查；
3. 从 informer-backed Infra 点查 claimed Sandbox；
4. 验证 owner；
5. 要求 `Visible=true`；
6. 读取同一次 Sandbox 观测的 OperationalState；
7. 进行 E2B state 投影，或执行 endpoint 专用准入和底层 capability。

Visible 与 OperationalState 互不替代。Visible 决定当前 delivery 是否仍在 E2B 操作范围，
OperationalState 描述底层运行状况，endpoint 策略决定当前动作是否允许，Infra capability 则保证
动作提交时仍然安全。

不读取 Sandbox 的语法校验可以在点查前完成，因为其响应不随 ID 是否存在而变化。动作权限拒绝也
必须满足该条件；否则必须先完成 lookup 和 owner 隐藏，再读取 Visible 或操作事实。

#### List 与 Describe

List 和 Describe 共用一个简单、完整的公开投影：

| 前提 | OperationalState | E2B state |
|---|---|---|
| `Visible=true` | `Serving` | `running` |
| `Visible=true` | 其他任意 OperationalState | `paused` |

这里的 E2B `paused` 是兼容值，表示 Sandbox 当前不能正常对外服务；它不保证底层字面上已经暂停。
因此，`Pausing`、`Resuming`、`Upgrading`、`Unavailable` 和 `Unknown` 等状态都不会泄漏给客户端，
也不会被错误报告为 `running`。

Describe 对 owner 匹配且 `Visible=true` 的对象总能得到上述投影，不再因 OperationalState 返回
not-found 或“不支持的 state”。List 先排除 `Visible=false` 的对象，再计算公开 state，然后执行
state 和 metadata 过滤，最后分页。page limit 和 next token 因而只描述客户端实际可见的结果集。

#### 操作准入矩阵

下表定义 owner 已匹配且 `Visible=true` 之后的额外条件。拒绝码只使用相应 endpoint 已声明的
response：

| Endpoint | Visible 后的 OperationalState 合同 | 条件不满足 |
|---|---|---:|
| Describe | 不增加操作门槛；使用公共 E2B state 投影 | — |
| Delete | 不增加 OperationalState 门槛 | — |
| Pause | `Serving` 开始 Pause；`Pausing` 加入等待；`Paused` 幂等成功 | `409` |
| Resume | `Paused` 开始 Resume；`Resuming` 加入等待；`Serving` 幂等成功 | `409` |
| Connect | `Serving` 直接连接并返回 `200`；`Paused` 开始 Resume，`Resuming` 加入等待，恢复到 `Serving` 后返回 `201` | `409` |
| Network | 允许 `Serving`、`Pausing`、`Paused`、`Resuming`、`Upgrading` | `409` |
| Set timeout | 仅允许 `Serving` | `401` |
| Snapshot | 仅允许 `Serving` | `400` |
| Browser | 仅允许 `Serving` | `401` |
| traffic-token refresh | 允许 `Serving`、`Pausing`、`Paused`、`Resuming`、`Upgrading`，且 Sandbox 要求 traffic auth | `409` |

除 Describe 和 Delete 外，未在某行列出的状态一律拒绝。特别是 `Provisioning`、`Recycling`、
`Terminating`、`Completed`、`Unavailable` 和 `Unknown` 不能执行表中的状态受限操作。它们仍可能在
`Visible=true` 时被 List 或 Describe 兼容投影为 `paused`，但“可读取”不等于“可操作”。

traffic-token 在初次授权后、实际签发前保留一次新的 Infra Sandbox 校验，以防 recycle/reclaim
竞态。该校验再次按 owner、Visible、OperationalState、`RequireTrafficAuth` 和 delivery 身份的顺序
执行：owner 已变化返回隐藏 `404`，同 owner 但 Visible 已结束返回 `401`，state 或 capability 冲突
返回 `409`。这里的 route 是从该次 Sandbox 观测投影出的 capability，不是本地 Route Store 的
存在性或 owner 权威。

Pause、Resume 和 Connect 只操作已经 Visible 的当前 delivery，不建立新的 epoch，也不修改 lock
或 delivered-lock。Manager 的状态机决定开始、join、幂等或冲突；Infra 对最新 backend 观测作
相同方向的权威校验，防止一次过期 Getter 观测直接驱动写入。

#### Delete 与 recycle

Delete 也要求 `Visible=true`，但不设置 OperationalState 门槛。Manager 先调用协议中立的 recycle
尝试 capability；该 capability 在最新 backend 观测上判断当前 Sandbox 是否支持并能够进入 recycle。
成功写入 `cleanup=true` 即表示删除请求已被接受，并立即结束当前 delivery 的 Visible；Manager
不等待 Controller 完成 recycle，也不以其完成作为释放 API 响应的条件。

若 recycle trigger 写入失败，现有 Kill fallback 仍可执行。Kill 成功发起持久化删除后，
`DeletionTimestamp` 使 Visible 结束；对象从 informer 消失后，后续查询才成为实际 not-found。

第一次成功提交 `cleanup=true` 或成功发起持久化删除的 Delete 返回 `204`。此后只要同 owner 对象
仍能被点查，但已经因 cleanup 或 `DeletionTimestamp` 得到 `Visible=false`，重试 Delete 返回
`401`；旧 Sandbox ID 从点查结果消失后返回 `404`。其他 owner 从始至终返回同样的隐藏 `404`。
因此，`204` 只确认本次删除已被接受，不把之后的不可见或实际不存在继续折叠成幂等成功。

Controller 成功 recycle 时清除上一 delivery 的 lock、delivered-lock、owner、Sandbox ID、
claim-scoped metadata、`PauseTime`、`ShutdownTime` 和 TrafficPolicy，然后才把 CR 返回池中。
这些清理防止下一次 Claim 继承旧 epoch，但 Manager 的删除语义不依赖清理是否完成。下一次交付
必须使用新的 lock，并重新完成 delivery commit。claimed 身份和旧 Sandbox ID 被清除后，即使可
复用 CR 仍在 informer 中，旧 delivery 的后续查询也属于实际不存在。

### HTTP 错误与信息披露

`401` 与 `404` 不按“是否发生授权失败”机械划分，而按响应是否会额外确认目标对象存在来划分。
所有原生和定制 Sandbox-ID endpoint 使用以下公共分类：

| 条件 | HTTP status | 公开语义 |
|---|---:|---|
| API key 无效或缺失 | 401 | 认证失败 |
| 调用方对动作本身无权，且判断与任何 Sandbox 是否存在无关 | 401 | 明确拒绝该动作，不透露对象事实 |
| claimed 点查没有匹配的 Sandbox | 404 | 实际不存在 |
| 多个 claimed Sandbox 匹配同一 ID | 404 | 失败即隐藏歧义，不选择任一对象 |
| Sandbox 存在但 owner 不匹配，即对象级越权 | 404 | 与不存在使用相同响应，避免确认该 ID 存在 |
| Sandbox 属于当前用户但 `Visible=false` | 401 | 当前 delivery 不允许操作；不是 not-found |
| Visible 但 Pause、Resume、Connect、Network 或 traffic-token 准入冲突 | 409 | endpoint 已声明的冲突 |
| Visible 但 Snapshot 的 OperationalState 不允许 | 400 | endpoint 已声明的 bad request |
| Visible 但 Set timeout、Browser 或其他无 400/409 的操作不允许 | 401 | endpoint 已声明的拒绝 |
| claimed 点查无法确定或内部失败 | 500 | 服务端失败，不降级为 404 |
| Create 最终 delivery commit 因非超时冲突或持久化失败 | 500 | Create 已声明的服务端失败 |
| Create、Resume 或 Connect 达到服务端硬上限 | 504 | Backend timeout |
| 其他 endpoint 达到服务端硬上限 | 500 | 该 endpoint 已声明的服务端错误 |

原则上，对象级越权只有在响应对存在和不存在完全相同时才可使用 `401`；本提案的 Sandbox-ID 请求
无法满足该条件，因此 owner mismatch 固定为 `404`。除“实际不存在”“歧义 ID 失败即隐藏”和
“隐藏其他 owner”外，任何 OperationalState、Ready、Visible、route、cleanup、到期或 delivery
失败都不得产生 `404`。这三种 `404` 使用相同 status、公开 message 和 response shape，且不附加
Sandbox resource context 或 metadata；动作级无权的 `401` message 也不包含 Sandbox 事实。当前
owner 的 Visible reason、OperationalState 和歧义 cause 只写入内部日志。

### 不变量

- Create 在 delivery commit 成功前绝不返回成功，List 和 Sandbox-ID endpoint 也不返回该 delivery。
- `delivered-lock == lock` 只证明当前 epoch 已交付；上一 epoch 的 marker 不能使新 delivery
  Visible。
- `cleanup=true`、ShutdownTime 到期、删除开始和三个明确终态都会结束 Visible。
- 一个 informer 中仍存在且属于当前用户的 Sandbox，不会仅因 OperationalState 或 Visible 失败返回
  not-found。
- 动作级无权只有在判断不读取目标 Sandbox、因而不泄漏其存在性时才返回 `401`；owner mismatch
  始终与不存在返回相同 `404`。
- 所有操作先满足 Visible，再执行 OperationalState 与 capability 准入。
- Manager 点查不接受 E2B state，也不读取 OperationalState、聚合 `GetState()` 或 Sandbox CR 状态。
- List 与 Describe 只公开 `running` 和 `paused`：`Serving` 为 `running`，其他可见状态为 `paused`，
  并在分页前过滤。
- OperationalState Getter 只返回一次观测；改变底层状态的 capability 必须重新确认 UID、delivery
  epoch、Visible 和最新运行状态。
- `Unavailable` 表示已识别但不能服务，`Unknown` 表示无法可靠解释；二者都不能放行受限操作。
- Route state 与 OperationalState 是两个独立协议，不能相互推导或替代。
- 最终 delivery Patch 不能覆盖 Controller 赢得的删除或更新。
- 单个请求最多获得一次 10 分钟预算；内部重试不会重置该预算。
- 读取和公开投影使用点查返回的一次 Sandbox 观测；Visible 与 OperationalState Getter 都不另行
  读取。操作 capability 的权威重验不改变这一读取合同。不同副本仍可以在短时间内给出不同结果。

### 兼容性边界

缺少 delivered-lock 的 lock-only Sandbox 按 `DeliveryNotCommitted` 处理，不提供推测性交付兜底。
这是一条失败即隐藏的安全边界：本提案不根据 creation time、OperationalState 或 Ready 猜测旧对象是否
已经完成交付，也不定义历史对象迁移。

正常生命周期的 timeout 从 delivery commit 的实际时刻开始计算，而不是从首次领取写入开始；因此
交付后可用时长保持请求值，Sandbox 从首次领取到最终结束的总时长可能增加。任何更长的客户端阶段
timeout 都仍受单个 10 分钟 API 硬上限约束。

E2B 的 `paused` 保持上游兼容值，但含义扩展为“当前不能正常提供服务”。客户端不能据此判断底层
究竟处于 Paused、Pausing、Resuming、Upgrading、Unavailable 还是 Unknown；需要执行动作时必须以
对应 endpoint 的响应为准。

Route 继续使用自己的 state 和 deletion fence。为了保持现有 gateway、peer 和 Controller 合同，
Route 投影或 Controller 自有逻辑可以继续使用其现有 Sandbox CR 映射；这些兼容读取不会重新进入
`infra.Sandbox` 的中立业务接口，也不能被 API 或 Manager 当作存在性、Visible 或操作权威。

上游 [JavaScript SDK](https://github.com/e2b-dev/E2B/blob/f0facc5dbcf93067326745e1597b05311c0174ea/packages/js-sdk/src/api/index.ts#L24-L29)
和 [Python SDK](https://github.com/e2b-dev/E2B/blob/f0facc5dbcf93067326745e1597b05311c0174ea/packages/python-sdk/e2b/api/__init__.py#L151-L155)
都会把 `401` 分类为 authentication exception。由于本提案不扩展 endpoint response 集合，同 owner
的 Visible 拒绝、动作级无权以及没有 `400`/`409` 可用的操作拒绝仍复用 `401`；SDK 的异常类型
可能不够精确，这是已接受的兼容性代价，公开 message 也不得以泄漏对象事实来弥补该限制。

## 迁移策略与终态

迁移计划以责任边界为单位，为不同消费者选择职责专用合同，而不把聚合 `GetSandboxState` 的映射
全局改造成 OperationalState。Route、Controller、quota、pool 和 E2B 对它提出的是不同问题；统一
改变共享映射会把一次边界重构变成多个协议同时变更。

### 迁移计划

| 领域 | 迁移方向 |
|---|---|
| 中立运行状态 | `GetOperationalState()` 由 Sandbox CR Infra 统一投影；旧聚合状态在过渡期只服务尚未迁移的兼容消费者，不再承载新的业务判断 |
| 点查与公开读取 | Manager 点查退出 state 过滤；E2B 以 Visible 和 OperationalState 完成统一的 List/Describe 投影 |
| 生命周期操作 | Manager 使用 OperationalState 表达 Pause、Resume 等协议中立策略；Infra capability 在最新观测上重验并提交操作 |
| endpoint 操作 | Connect、Network、Set timeout、Snapshot、Browser 和 traffic-token refresh 使用各自明确的状态集合，不再复用 lookup state 集合 |
| wait | cache 只提供通用等待、事件与 double-check 机制；Sandbox CR adapter 注入 pause、resume 和 delivery-ready 判断 |
| quota | cache 只提供 owner 范围的原始枚举；Sandbox CR Infra 负责 quota live 过滤和中立 quota snapshot，不能用 `Serving` 推断配额占用 |
| pool 与 claim count | pool 候选由 Sandbox CR Infra 根据 pool 身份、revision、claim、endpoint 和创建时间判断；claim count 由拥有该合同的 Controller 判断，不使用 OperationalState |
| Delete 与 recycle | Manager 不再读取原始 Phase；一个协议中立的 recycle 尝试 capability 在最新观测上决定是否接受，未接受或失败时再走持久化删除 |
| Route 与 Controller | 保留现有 Route state、deletion fence 和 Controller 自有 CR 状态机；它们不迁移到 Manager Infra Getter |

旧接口只在替代合同已经覆盖其业务消费者后退出。迁移期间不得在 API 或 Manager 重新解析 Phase、
Condition、Ready、Pod IP 或其他 Sandbox CR 字段作为临时兜底，也不得把 Route state 反向转换成
OperationalState。

### 迁移终态

| 层或组件 | 最终边界 |
|---|---|
| E2B API | 不读取 Sandbox CR；使用 Manager 点查、`GetVisibility()`、`GetOperationalState()` 和中立 capability，负责公开 state 与 HTTP 映射 |
| Manager | 点查只回答 claimed 身份与 owner；生命周期策略只消费中立观测，不依赖聚合 `GetState()`、原始 Phase 或 backend reason |
| Infra Sandbox 接口 | 保留 `GetVisibility()`、`GetOperationalState()` 和必要的具体 capability；不再暴露聚合 `GetState()`、原始 `Phase()` 或需要调用方先查询再决定的 recycle eligibility |
| Sandbox CR Infra | 独占 CR 到 OperationalState 的映射，并在 mutation 前绑定 UID、delivery epoch 和最新状态；不同业务事实转换为各自的中立 snapshot 或 capability |
| cache | 在本提案涉及的范围内只提供 informer 读取、索引、事件、wait 和 health 机制，不直接解释 Sandbox 业务状态 |
| quota、pool、wait、claim count | 各自保留独立合同；OperationalState 可以作为局部输入，但不能替代其 identity、generation、resource、endpoint 或 desired-state 事实 |
| Sandbox Route | 继续使用现有 Route state 协议、Store 顺序和 deletion fence，不生产或消费 OperationalState |
| Sandbox 及其他 Controller | 继续作为 CR 状态生产者和各自 reconciliation 合同的 owner，不依赖 sandbox-manager Infra |

迁移完成的判断不是仓库中彻底消失 `GetSandboxState`，而是它不再出现在 API、Manager 或
`infra.Sandbox` 的中立业务边界。Route 或 Controller 为维持自身协议而保留的映射必须留在对应责任
范围内，不能再次成为跨层共享的操作判断。

## 备选方案

### 继续使用聚合 GetState 或增加 Healthy Getter

聚合 `GetState()` 同时压缩存在性、到期、Ready 和转换事实，无法可靠支持操作状态机。单一
`Healthy` 布尔值又会把 Ready 波动、状态转换和 E2B 公开策略混在一起，既不能解释为什么不可用，
也不能区分 join、幂等和冲突。本提案采用 typed OperationalState，并让 Visible 与业务专用事实
继续独立。

### 让 Route state 成为共同运行状态

Route state 服务路由发布、peer 同步、resourceVersion 顺序和 deletion fence，生产者与生命周期也
不同于 Sandbox-ID API。让 API 或 Manager 依赖 Route 会重新混合存在性、流量与运行状态，并扩大
本提案明确排除的 Route 变更。因此 Route 保持独立协议。

### 在第一次 lock 写入时直接标记已交付

这会让 Ready、runtime、凭证、CSI 或 TrafficPolicy 后处理失败的 Sandbox 提前可见，无法满足
Create 成功与公开交付一致的合同。

### 增加 DeliveryDeadline 字段

单独字段会扩大 CRD 合同，而 `ShutdownTime` 已能为不可见 delivery 提供 Controller 删除上限，
最终 Patch 又会把它替换成正常生命周期 deadline。

### 等待 Controller 完成 recycle 才结束 Visible

这会把 API 删除成功依赖异步 Controller 收敛。以 `cleanup=true` 作为不可逆提交点可以立即结束
当前 delivery，同时仍允许 Controller 在后台完成资源清理。

### 在 Manager 点查中继续筛选 state

这会继续把存在性与操作准入混合，并使属于当前用户的现有对象因 state 不匹配产生 not-found。

## 风险

- 带 resourceVersion 的最终 delivery Patch 可能在后处理已经完成后仍因并发写冲突而失败。这是
  Controller 与并发生命周期写优先于 Create 成功的刻意取舍。
- `Succeeded`、`Failed` Sandbox 可以持久存在且对 E2B 不可见，并可能继续占用现有资源或配额；
  本提案不增加 janitor，也不保证 ShutdownTime 删除这些终态对象。
- Visible 依赖本地时间与 informer 观测。时钟偏差和副本缓存进度可能导致短暂差异，本提案明确接受。
- 新增 marker 失败即隐藏；没有 delivered-lock 的历史或部分写入对象不会自动恢复为 Visible。
- E2B 把所有可见的非 `Serving` 状态统一公开为 `paused`。这满足上游枚举，但客户端无法仅凭读取
  结果区分稳定暂停、转换、升级、不可服务或未知状态。
- OperationalState 是一次观测，可能在调用方作出判断后变化。若 Infra capability 未在 mutation 前
  绑定同一 UID、delivery epoch 并重验最新状态，仍可能对错误对象或错误阶段执行操作。
- 新 backend Phase 或新的条件组合会得到 `Unknown`。读取仍兼容投影为 `paused`，受限操作则失败即
  关闭；这可能暂时降低可操作性，但不会把未知状态误放行为可服务。
- Gateway route 仍有自己的投影与同步生命周期。Sandbox-ID API 不再以 route 缺失判定不存在，但
  本提案不保证 API Visible、E2B `running/paused` 与 Route 流量可达性在每个瞬间完全相同。
