# OpenKruise Agents sandbox-manager 接入 OpenAI Agents API：Webhook-managed self-hosted 初步研究

> 核验日期：2026-09-17。本文是可用于评审与任务拆分的设计，不是已经实现或上线的功能。
>
> 本次实际核验：重新拉取 OpenKruise Agents 源码（`41f676c7adb3cae4a72f8867a4b57ced6b4924cf`）和 OpenAI Cookbook（`9a8e9f07dd8b90e67e6ea11d9c90f8e7dc4bfa35`），阅读官方 hosted、self-hosted、lifecycle、webhooks、files 文档，逐项检查创建、runtime、恢复、回收调用链。未使用真实 OpenAI 凭证、未部署集群、未进行端到端联调。
>
> 下文的 OpenAI 事件和 executor 启动参数来自官方协议；新增目录、接口、CRD、路由、策略名均为设计建议，并非仓库已有功能。

## 0. 结论与首发边界

建议为 **sandbox-manager 新增一个可选的 OpenAI provider 模块**：通过独立验签的 HTTPS webhook 接收 OpenAI 的环境连接请求，持久化为工作记录，后台 reconcile 领取或恢复 OpenKruise Sandbox，准备工作区，然后启动沙箱内的 `codex exec-server`。

- OpenAI 负责 agent harness、模型调用与工具调度。
- OpenKruise 负责计算资源、隔离、工作区和生命周期。
- executor 主动出站连接 OpenAI；webhook 不承载逐条命令、stdout 或文件传输。
- 保持 `environment.type = self_hosted`。这不是给 `openai_hosted` 替换底层 vendor，也不是给请求新增一个未经定义的 `vendor` 字段。
- 完成技术接入不等于自动进入 OpenAI 官方 provider 名录；公开文档提供的是自建 receiver 的接入路径。

**首发建议：固定受信任模板、一个 session 一份沙箱、关闭自动暂停和回池复用、显式续期、仅按已配置的 project/owner/agent 路由。**先验证生命周期正确性，再开放动态模板和节省成本的策略。

## 1. 本次源码核验得到的关键结论

### 1.1 不能直接照搬 Cookbook 的 `envs={CODEX_API_KEY: ...}` 到创建请求

源码证据链：

1. `pkg/servers/e2b/create.go:153–158` 将请求 `EnvVars` 传给 `InitRuntimeOptions.EnvVars`。
2. `pkg/sandbox-manager/infra/sandboxcr/claim.go:854–863` 将 `opts.InitRuntime` JSON 序列化到 Sandbox annotation。
3. `pkg/servers/e2b/create.go:105` 还记录完整的解析后创建请求，结构中包含 `EnvVars`。

因此，通过当前路径将 `CODEX_API_KEY` 放入创建请求，会使它进入 annotation 持久化路径，并存在随请求日志输出的风险。官方 E2B 示例的凭证注入方式不应直接移植。

**设计决定：**Claim 仅携带非敏感初始化信息。executor key 在 Claim 成功后由可信控制面读取 Secret，使用经过鉴权和 TLS 保护的 runtime 操作传给 executor 的启动控制程序。禁止写入普通 metadata、InitRuntime、镜像和日志；绑定对象只存 `credentialRef`。

这并不意味着 agent 永远读不到 executor key。官方明确说明沙箱内代码可以读取该受限 key，所以必须使用专用 environment key，而不能依赖隐藏变量保护应用主密钥。

### 1.2 Go runtime 的 `Process.Run` 不是 E2B SDK 的 background 接口

`pkg/utils/runtime/process.go:81–86` 仅暴露前台 `Run` 和 `Chmod`。`Run` 消费事件流直到退出；第 147 行直接使用 `context.WithTimeout(ctx, timeout)`。

因此：

- 将 `codex exec-server` 直接交给 `Process.Run` 会占住 worker，直到命令结束或 RPC 超时。
- 将 `Timeout` 设为 0 会立即到期，并不是“无限期”。
- 不能将官方 Python E2B 示例中的 `background=True, timeout=0` 按字面搬到这个 Go 封装。

**设计决定：**模板内安装 supervisor，runtime 的 `Process.Run` 只运行短时、幂等的 `executor-control ensure/status/stop` 控制命令。长期运行的 executor 由 supervisor 托管。另一条路线是补齐原生 detached process API，但必须验证 RPC 断开、worker 重启时进程存活的契约。

### 1.3 `DeleteSandbox` 可能是回池，不是真正销毁

`pkg/sandbox-manager/api.go:453–465` 在开启 recycle 且 Sandbox 处于 Running 时调用 `TriggerRecycle`。

因此，删除返回成功不代表 executor 已停止、凭证已清除、工作区已隔离完毕。

**设计决定：**首发 OpenAI 模板关闭 recycle，释放仍通过 Manager，以保留路由和配额处理。开放回池前必须有可验证的流程：停止 executor → 清除凭证和会话绑定 → 清理或隔离工作区及日志 → 清理进程 → 验证干净 → 才允许回池。清理失败必须隔离或销毁。

### 1.4 Claim 的 LockString 不是 session 级幂等键

`infra/sandboxcr/claim.go:181–189` 明确：启用 admission 时，每次尝试使用新的 lockString，以保证配额 acquire/release 对应。

因此，不能简单把 `session_id` 填进 `LockString` 就声称 webhook 实现幂等。资源领取锁和 OpenAI session 绑定需要分开。

### 1.5 恢复必须同时更新生命周期 deadline

`infra.ResumeOptions.Timeout` 支持将 timeout 和 `Paused=false` 原子写入，防止旧 PauseTime 在恢复窗口再次触发暂停；E2B 的 `buildResumeOpts` 已利用该语义。

**设计决定：**原生适配层也复用此行为，而不是只改 `Paused`，然后异步补 TTL。

## 2. 官方协议：以 hosted 为能力基线，不把它当 vendor 接口

### 2.1 控制面与执行面

```text
业务应用 ──create session / input──► OpenAI Agents API
                                      │
                                      │ Signed HTTPS webhook
                                      ▼
                         sandbox-manager OpenAI receiver
                                      │ durable work record
                                      ▼
                           OpenAI provider reconciler
                                      │
                 ┌────────────────────┴───────────────────┐
                 ▼                                        ▼
       SandboxManager Claim/Resume                 Runtime bootstrap
                 │                                        │
                 └────────────► Sandbox ◄──────────────────┘
                                  ├── /workspace
                                  ├── executor supervisor
                                  └── codex exec-server
                                           │ outbound registration / WSS
                                           └──────────────────► OpenAI
```

OpenAI 需要访问 receiver 的公网 HTTPS endpoint；无需访问 Pod、envd 或 sandbox-gateway 的执行入口。Manager 到 runtime 保持内网和现有 TLS/mTLS 路径。

### 2.2 客户端行为

建议沿用官方 Cookbook 的共享客户端协议：

```python
# 示意：已配置能使用 beta Agents API 的 SDK 与真实 agent_id。
session = await client.beta.agents.sessions.create(
    agent_id=agent_id,
    environment={
        "type": "self_hosted",
        "workspace_directory": "/workspace",
    },
)

# 如有每个 session 的私有模板、输入文件等配置，先在我方持久化绑定，
# 再提交首个 input。固定 agent -> template 策略则不要求额外客户端步骤。
async with client.beta.agents.sessions.stream(session.id, input=user_input) as events:
    async for event in events:
        consume(event)
```

如果需要“不改业务客户端”的接入体验，第一版使用控制面预配置的 agent → 模板策略。不要臆造一个 OpenAI API 不接受的 `environment.template` 字段。

### 2.3 Webhook 路由

建议订阅：

- `agent.session.action_required`：只有 `data.required_action.type == environment_connection` 触发连接 reconcile。
- `agent.session.failed`：查询当前 session 仍失败后释放计算资源。

不以 `agent.session.in_progress` 启动环境，它来得太晚。`function_call` 要的是函数结果，不是沙箱。SSE 的对应事件名是 `agent.session.requires_action`，不要和 webhook 事件名混用。

```json
{
  "id": "evt_example",
  "type": "agent.session.action_required",
  "data": {
    "id": "sess_example",
    "required_action": {"type": "environment_connection"}
  }
}
```

这个 action webhook **没有** `connect.remote_url`；worker 查询 session 后使用 `session.environment.id` 和 `session.environment.remote_url`。URL 原样复用，不自行拼接。

接收过程：读取受限大小的原始 body → 根据 endpoint 的配置选签名 secret → 验签和时间校验 → 解析事件 → 持久化待处理记录 → 返回 2xx。成功忽略的无关事件可返回 2xx；签名无效拒绝；持久化失败返回可重试错误。

不要将 OpenAI webhook 挂在需要 E2B `X-API-Key` 的中间件下面。路径中的 provider ID 只是选配置，不是身份认证依据。

### 2.4 何时算成功

- Receiver 返回 2xx：仅代表投递已被可靠接收。
- Sandbox Ready：仅代表基础设施准备好。
- 启动控制命令成功：仅代表 supervisor 接受或确认了进程。
- OpenAI environment connected：才代表 Agent 可以使用执行环境。

不通过 webhook response 返回 sandbox URL 来完成连接，也不提交一个伪造 tool result 来清除 required action。executor 连上后由 OpenAI 清除 action，并在等待期限内继续原输入。

官方连接等待上限为五分钟。队列、Claim、挂载、setup、连接共用这段预算，迟到连接不会重放已超时的输入。

## 3. 原生模块边界与具体变更位置

建议的模块划分：

```text
pkg/servers/openai/                  # 新增，OpenAI HTTP 协议
    webhook.go                      # raw-body 验签、字段解析、落盘
    config.go                       # endpoint / secret / routing

pkg/integrations/openai/             # 新增，provider 业务
    reconciler.go                   # 查询 OpenAI 当前状态、推进工作
    binding_store.go                # 持久化契约
    policy.go                       # project/owner/agent -> 租户/模板/凭证
    executor.go                     # Ensure / Status / Stop
    cleanup.go                      # closing、失败与孤儿回收

pkg/sandbox-manager/                 # 保持协议无关
    必要时抽取共享 provisioning 服务和受控 runtime 能力

examples/openai_executor/            # 新增，固定版本模板与监督程序
config/sandbox-manager/              # 扩展，feature flag / ingress / RBAC / Secret refs
```

| 已有位置 | 当前行为 | 建议变更或复用 |
|---|---|---|
| `cmd/sandbox-manager/main.go:404–437` | 创建并运行 E2B Controller | 增加可选 OpenAI 组件的装配与生命周期；避免再创建一套 Manager |
| `pkg/servers/e2b/core.go:130–166` | 内部创建 Manager、cache、quota | 抽出共享依赖的装配，或提供通用的组件注入接口；不将 OpenAI 逻辑塞入 E2B 路由 |
| `pkg/servers/e2b/create.go:137–218` | 组装 Claim、runtime init、CSI、quota、network | 提取可共享的业务能力；不能只复制一个 Claim 调用而漏掉授权和网络策略 |
| `pkg/sandbox-manager/api.go` | Claim/Get/Pause/Resume/Delete | 作为 provider 的资源管理入口 |
| `pkg/utils/runtime/process.go` | 有限时前台命令 | 调用短时 supervisor 控制命令；不得用于等待长期 executor |
| `pkg/utils/runtime/client.go` | runtime transport/auth 封装 | 复用 transport 决策，不在 provider 里硬编码 Pod IP:49999 或降级 TLS |
| `pkg/sandbox-manager/leader.go` 与 `core.go` | Primary 状态与变更通知 | 第一版用现有 primary 驱动 reconcile；任意副本可验签落盘 |
| `config/sandbox-manager/*` | 部署、Service、Ingress、RBAC | 仅暴露 webhook 必需路径，限制 Secret 和 binding 权限 |

`infra.Sandbox` 与 `*v1alpha1.Sandbox` 并非同一接口；现有 runtime client 绑定具体 Sandbox CR。建议通过共享 provisioning/runtime 边界解析这一差异，避免 OpenAI handler 到处强转 `sandboxcr.Sandbox`。该适配层本身不应该知道 K8s Pod exec 或拼装底层 envd URL。

新增能力使用 feature flag，默认关闭。OpenAI 队列限流、并发和错误应独立于 E2B 请求，防止 webhook 积压拖垮原有 sandbox-manager。

## 4. 持久化与高可用：明确不把内存队列当可靠存储

### 4.1 推荐第一版：一个 session 一份 Binding 工作记录

对以 K8s 为主的部署，建议新增 `OpenAIEnvironmentBinding` CRD 作为持久化记录，内存 workqueue 只用来加速调度。这样第一版不必额外依赖消息队列；若你们已统一使用事务数据库，也可实现相同 Store 接口。

CRD 方案需要按实际 session 数和 webhook QPS 压测 etcd/API server。若规模不合适，切到持久化数据库与 outbox，而不是把热事件无上限塞进 annotations。

概念字段（拟议，不是可直接 apply 的既有 CRD）：

```yaml
spec:
  providerRef: configured-provider
  projectRef: configured-project
  ownerRef: configured-service-account
  sessionID: sess_example
  desiredLifecycle: Active       # 或 Closing，关闭标记不可被旧事件逆转
  requestedRevision: 12         # CAS 更新的 reconcile 请求代数
status:
  observedRevision: 11
  environmentID: env_example
  sandboxRef:
    namespace: tenant-a
    name: sandbox-resource
    uid: resource-uid
    deliveryID: delivered-sandbox-id
  allocationOperationID: opaque-operation-id
  executorGeneration: 2
  phase: Connecting
  nextRetryAt: timestamp
  workspaceRef: durable-workspace-ref
  lastErrorCode: safe-error-code
```

凭证引用可在 provider policy 中配置，不把 key 填入 status。session ID、environment ID、sandbox delivery ID 是三个不同的标识。

### 4.2 不能丢事件，也不能无限重复领沙箱

- Receiver 只有在 `requestedRevision` 的持久化写入成功后才返回 2xx。
- Worker 只将自己观察到的 revision 标记完成；处理期间出现新 revision，必须继续 reconcile，不能简单删除 job。
- 重复 event 可以合并为相同 session 的 reconcile；event 去重是优化，不是替代幂等。
- 进程重启和 primary 切换后扫描 `requestedRevision > observedRevision`、未完成 phase 和到期重试项。
- Losing primary 时取消本轮上下文，不再发起新的有副作用操作。不能把一次 `IsPrimary()` 检查当作永久持有锁。

### 4.3 Claim 成功但绑定尚未写回的崩溃窗口

使用 Claim 的 `Modifier`，在领取写入中记录受保护的 binding UID 和 allocation operation ID，且将这些字段纳入回收清理规则。

恢复时先用 API 的权威读取按操作标识查找资源，不能只依赖可能滞后的 informer cache；找到后核对 owner、Sandbox UID 和 delivery ID，再补写绑定。查不清时不要立即再次 Claim。

现有 Claim 接口不是跨资源事务，租约也不能天然阻止已在飞行中的旧请求。故障下不应承诺“物理上绝对零重复分配”。第一版应保证只有绑定的获胜实例可以进入 executor 激活流程，未绑定资源被隔离并补偿回收；启动前重新验证绑定和 generation。

若线上要求严格的零重复领取或严格的单 executor fence，需要下沉实现中性的幂等 Claim/激活仲裁，使副作用端验证操作所有权，而不是只在 OpenAI worker 层加 Redis 锁或固定 LockString。这个要求应列为实现与故障注入测试的明确门槛。

## 5. 生命周期 reconcile 与 executor 的实际启动方式

### 5.1 状态机

```text
Requested -> Allocating -> Preparing -> Connecting -> Connected
                               |             |
                               +------> RetryWait / Error

Connected -> Pausing -> Paused -> Resuming -> Connecting

任意非终态 -> Closing -> Released
```

这些是我方 Binding 状态，不是声称 OpenAI 存在同名 API 状态。首发不启用自动 Pausing。

每轮以 OpenAI 当前 session 状态为准：

1. 使用配置好的 project/owner credential 查询 session。
2. 核对 agent filter、环境类型和资源所有权。
3. 若仍 failed，执行清理；若 action 已解决，不再重新创建。
4. 若仍需要 environment_connection，取消待关闭计时，并确保绑定沙箱可用。
5. 准备工作区、网络与依赖；setup 成功后才启动 executor。
6. 观察 OpenAI environment 的连接状态；进程存在本身不是 connected。

查 session 的 401/403/429/5xx 不能当作删除，不应据此杀掉运行资源。确定的删除也需与我方 closing/创建窗口协调。保留一个统一的业务删除入口：先阻止新输入并持久化 Closing，再分别删除 OpenAI session 和释放计算；定期 reconciliation 兜底漏删，失败独立重试。

### 5.2 模板及 bootstrap

镜像预装固定版本 Codex CLI、shell/Python/Node 工具和 supervisor。构建期验证 `codex exec-server --help`，发布时固定镜像 digest 和依赖版本。预热池不含 tenant key、session ID 或已连接 executor。

领取后先完成文件、挂载、权限和 setup；再通过短时 runtime 命令调用类似：

```text
/usr/local/bin/executor-control ensure --environment-id <id> --remote <returned-url>
```

这是拟议的镜像内控制程序，不是 Codex 已有命令。受限 key 通过进程环境或专用受控通道传入，不出现在 argv、配置 annotation、stdout 或 stderr。运行时服务的日志与审计也需要脱敏。

supervisor 在工作容器内托管真正的进程：

```bash
cd /workspace
# CODEX_API_KEY 已通过受控路径注入。
exec codex exec-server \
  --remote "$REMOTE_URL" \
  --environment-id "$ENVIRONMENT_ID"
```

`ensure` 必须幂等，检查真实进程而不是只信 PID 文件；进程与 environment/generation 必须匹配。RPC 断开、worker 重启不应杀死 executor。进程退出按受控重试策略恢复；永久鉴权错误不能无限重启刷日志。

不要未经验证就把 executor 单独塞到不共享工具环境的 sidecar：它实际执行 shell，需要正确的 rootfs、工作目录、工具和权限。文件卷相同不等于执行环境相同。

### 5.3 时间预算

官方五分钟是总连接等待上限，不是每一个阶段都有五分钟：

```text
webhook delivery + queue + claim/resume + storage/setup + executor connection < 5 min
```

Receiver 不做长工作。缓存固定依赖、预热镜像；Claim、setup、注册都设置有限 deadline。阶段耗时与总耗时单独观测。重试受总预算和 session 最新状态约束，而不是机械套用 Cookbook 的五次重试。

永久配置错误记录在 Binding 和运维告警中，由业务层观察失败；当前设计不假设存在未核验的“vendor 回调失败”API。

## 6. 线上安全、恢复与回收

### 6.1 凭证和租户

至少分开：webhook signing secret、session-read credential、executor environment key、runtime 访问凭证。

- executor key 按当前 self-hosted 文档从 Agents 环境页创建，只允许环境连接用途；匹配 session 的 organization、project、user/service-account owner。
- Cookbook 共享 README 仍描述了 `List models → Read` 的示例权限设置，和当前产品文档不完全一致。实现时以当前 self-hosted 认证文档和实际控制台可用的 environment-key 能力为准，并在预发验证权限；不能随意回退为宽权限应用 key。
- 不把模板名、namespace、credentialRef 直接由未校验 webhook 字段决定；签名只证明事件来自 OpenAI，还需验证它属于该 provider 管理的 session。
- controller 的 Kubernetes ServiceAccount 只可访问受管 namespaces 与指定 Secrets；沙箱不挂载 controller token，不默认使用高权限宿主机访问。
- agent 可以读取 executor key 是既定威胁模型；不要在沙箱中放业务应用主 key。
- checkpoint 可能包含内存中的 key。快照需要按敏感数据处理，恢复时核对并刷新凭证；销毁和保留期限也要管理。

### 6.2 网络：不能把 hosted disabled 的语义直接复制成全 Pod 断网

executor 需要出站：

- `https://api.openai.com`
- `wss://codex-cloud-environments.chatgpt.com`

宿主集群必须允许这些链路和长连接。业务访问可另加限制，但在同 Pod 网络身份下，单靠 Pod NetworkPolicy 无法区分 executor 控制流量与 agent 发起的相同目标流量；若需要更强的“业务断网”语义，需要额外的出口代理或可区分执行身份的隔离方案。不能宣称加两条白名单就完全等价于 hosted `network.disabled`。

创建链路的网络策略部分位于 E2B 层，直接调用 Manager Claim 并不自动复制该层所有策略。建议模板以 fail-closed 的基础网络隔离启动，确认业务策略生效后才执行用户 setup/启动 executor。

### 6.3 出站 WebSocket 绕过 gateway，续期不能看入站流量

OpenAI 任务可能完全没有 sandbox-gateway 入站访问。因此：

- Gateway 空闲不等于 agent 空闲。
- 不能把网关按访问续期当作 OpenAI 工作的保活机制。
- 不能依靠 gateway wake-on-ingress 唤醒已暂停沙箱；连接 required action 是恢复触发器。

首发保持 Active session 的显式租约续期，同时设业务最大生命周期和配额，避免无限泄漏。OpenAI 查询短时失败不直接杀任务；容错窗口和硬上限应明确配置。

未来自动暂停必须与业务输入入口协调：新输入先撤销暂停意图；关闭前重查状态；仅收到 `agent.session.idle` 不足以安全暂停。不能协调新输入时保持运行。

### 6.4 恢复不是重放

- executor 网络闪断可以自重连。
- 进程退出后可由 supervisor 重启，但不保证被杀命令继续。
- 暂停/恢复能保存哪些文件或内存，取决于实际后端，需要实测。
- 替换沙箱需要 PVC/快照/外部存储恢复，相同 environment ID 不恢复文件。
- 首发遇到旧工作区丢失建议 fail closed 并提示业务恢复，不悄悄创建空目录让 agent 继续。
- 中途断连不必然触发新的 webhook；下一次 input 才可能触发连接请求。不能靠 webhook 代替进程健康监控。
- 输入等待超时后检查实际 outcome，再决定重试；原请求仍在等待时不要重复提交。

## 7. 对照 hosted 文档的能力映射

| Hosted 能力 | OpenKruise 方案 | 兼容边界 |
|---|---|---|
| packages | 版本化镜像，少量启动准备 | 不宣称 self_hosted 接受同样的 packages 字段 |
| setup_commands | 可信 bootstrap 配置；完成后连接 executor | setup 必须幂等，恢复时不重复破坏工作区 |
| input files | Files API 或 session 专属挂载/对象存储下载 | 下载 OpenAI Files 时所需应用权限留在控制面 |
| env | 区分用户变量与平台变量；敏感变量走运行时注入 | 禁止当前 InitRuntime annotation 路径承载 executor key |
| templates | agent/policy 映射到 SandboxSet/SandboxTemplate | OpenAI environment_template_id 仅适用于 hosted |
| network | 模板基础隔离、TrafficPolicy/出口治理 | 控制面必须可达，不能直接宣称 disabled 完全等价 |
| /workspace 跨 turn 保留 | 同实例或明确的持久化工作区 | 新实例不自动继承文件 |
| /workspace/outputs artifacts | 我方收集器 → 私有对象存储 → 我方下载接口 | self_hosted 不自动发布 OpenAI Artifacts API |
| keepalive / expiry | 我方运行租约与 hard lifetime | hosted 一小时规则不是 vendor 回调契约 |
| 删除 | Closing + OpenAI delete + Manager release + GC | 删除 session 没有删除 webhook，也不会释放计算 |

输出收集按 `session_id + turn_id + path` 版本化，拷贝时限制大小、校验路径与符号链接，避免跨工作区读取。业务消费 session stream 的 turn 完成事件，再触发收集；`idle` 不等于任务成功，`turn.completed` 也不等于每条工具都成功。

## 8. 任务拆分、验收和发布

### PR 1：协议与生命周期骨架

- 新增 OpenAI receiver、验签与结构校验。
- Binding Store/CRD、revision 合并、持久化后 ACK。
- provider policy 和最小权限凭证引用。
- primary 驱动 worker、重启扫描、旧事件/无关 agent 过滤。
- Mock OpenAI 与 mock provisioning 的协议单测。

### PR 2：原生资源与 executor 接入

- 抽取共享 provisioning 装配，复用 Manager 而不是同进程 HTTP 自调用。
- Claim metadata 找回、owner/quota/network/timeout 处理。
- 固定版本镜像、supervisor、短时 Ensure/Status/Stop。
- 不经 InitRuntime 注入 executor key，日志脱敏。
- OpenAI 模板默认不自动暂停、不回池。

### PR 3：生产可靠性

- Closing 与孤儿扫描、TTL 续期、资源找回。
- 长任务、滚动重启、故障注入、审计。
- Files 输出收集与工作区恢复（按首发业务要求决定是否作为上线前置项）。
- 容量与限流、重试耗尽告警、分阶段启动指标。

### 上线验收矩阵

| 场景 | 必须验证的结果 |
|---|---|
| 首次输入 | webhook 创建，executor 连通，原输入执行，应用不再次提交 |
| action 是 function_call | 不领取沙箱 |
| 其他 agent/project | 不领取、不泄露资源信息 |
| 签名错误、body 重序列化、过期投递 | 按验签规则拒绝；不触发 Claim |
| 持久化不可用 | 不返回成功 ACK；旧运行沙箱不因接收失败而被杀 |
| 重复/并发 webhook | 幂等处理，不出现两份可用 executor |
| Claim 成功后 worker 崩溃 | 找回同次 allocation，不盲目再次分配 |
| processing 期间新事件 | revision 不丢失，不能被旧 worker 完成操作覆盖 |
| primary 切换与旧请求在飞行 | 验证绑定仲裁、激活校验及孤儿补偿 |
| runtime RPC 断开、Manager 重启 | executor 继续存在；能重新查询和控制 |
| TTL 到期前的长任务 | 显式续期覆盖无 gateway 入站流量的任务 |
| 恢复 paused Sandbox | deadline 原子更新；文件符合后端持久化承诺 |
| OpenAI read 401/429/5xx | 不误判删除，不立即销毁工作区 |
| 删除 session | 即使没有 webhook，也能最终释放 Sandbox |
| credentials 检查 | annotation、普通日志、镜像无 executor key |
| 回池验证（后续） | 无残留进程/key/文件/绑定后才交付下一租户 |
| 总启动超时 | 五分钟等待失败后不自动重复提交原 input |

发布从预发单一 project/owner/agent 开始，feature flag 默认关闭。扩大流量前观察：验签失败率、持久化失败、队列年龄、Claim/Resume/Setup/Connect 耗时、重试耗尽、孤儿资源和续期失败。高基数 session/sandbox ID 放结构化日志与 trace，不直接作为 Prometheus label。

回滚时先关闭新建入口/新 session 路由，保留对已运行沙箱的续期与清理能力，或将其交给明确的接管组件。直接关掉整个 provider worker 可能让存量沙箱过期，不能作为无损回滚方案。

## 9. 上线前需要你们确认的四个事实

1. 实际部署的 OpenKruise 版本、runtime 镜像、隔离运行时和暂停/快照后端是否与核验源码一致。
2. 是否由单一 OpenAI service account 统一创建 session，还是多项目、多 owner；这决定凭证与路由维度。
3. 是否要求跨实例保留工作区、是否首发就必须自动暂停、是否要求严格的零重复物理分配。
4. 峰值新建/重连 QPS、并发 session 和最长 turn；据此决定 CRD Store 是否合适、预热池规模和租约策略。

这些信息影响实现参数和存储选择，但不改变核心接入协议。

## 10. 可核验来源

### OpenAI 官方文档

- [Hosted 能力基线](https://developers.openai.com/api/docs/guides/agents-api/environments/openai-hosted)
- [Self-hosted：连接方式、认证、executor 参数](https://developers.openai.com/api/docs/guides/agents-api/environments/self-hosted)
- [Lifecycle：webhook-managed、五分钟等待、清理与竞态](https://developers.openai.com/api/docs/guides/agents-api/environments/lifecycle)
- [Webhooks：事件名、payload、验签与 required actions](https://developers.openai.com/api/docs/guides/agents-api/sessions/webhooks)
- [Files：self-hosted 不发布 OpenAI artifacts](https://developers.openai.com/api/docs/guides/agents-api/environments/files)

### 官方 Cookbook，固定 commit

- [E2B handler.py](https://github.com/openai/openai-cookbook/blob/9a8e9f07dd8b90e67e6ea11d9c90f8e7dc4bfa35/examples/agents_api/sandboxes/webhook_managed/e2b/handler.py)：单进程 SQLite 队列、按 agent 过滤、find/create/connect、flock、后台命令。
- [共享 client.py](https://github.com/openai/openai-cookbook/blob/9a8e9f07dd8b90e67e6ea11d9c90f8e7dc4bfa35/examples/agents_api/sandboxes/webhook_managed/client.py)：客户端只使用 Agents API。
- [共享 README](https://github.com/openai/openai-cookbook/blob/9a8e9f07dd8b90e67e6ea11d9c90f8e7dc4bfa35/examples/agents_api/sandboxes/webhook_managed/README.md)：示例限制和部署前提。

### OpenKruise 源码，固定 commit

- [程序装配](https://github.com/openkruise/agents/blob/41f676c7adb3cae4a72f8867a4b57ced6b4924cf/cmd/sandbox-manager/main.go#L404-L437)
- [E2B Controller 创建 Manager](https://github.com/openkruise/agents/blob/41f676c7adb3cae4a72f8867a4b57ced6b4924cf/pkg/servers/e2b/core.go#L130-L166)
- [创建请求、EnvVars、Claim 与网络策略](https://github.com/openkruise/agents/blob/41f676c7adb3cae4a72f8867a4b57ced6b4924cf/pkg/servers/e2b/create.go#L83-L218)
- [InitRuntime 写入 annotation](https://github.com/openkruise/agents/blob/41f676c7adb3cae4a72f8867a4b57ced6b4924cf/pkg/sandbox-manager/infra/sandboxcr/claim.go#L854-L863)
- [Claim 锁与 admission 语义](https://github.com/openkruise/agents/blob/41f676c7adb3cae4a72f8867a4b57ced6b4924cf/pkg/sandbox-manager/infra/sandboxcr/claim.go#L181-L189)
- [runtime 前台命令与 timeout](https://github.com/openkruise/agents/blob/41f676c7adb3cae4a72f8867a4b57ced6b4924cf/pkg/utils/runtime/process.go#L75-L173)
- [恢复时原子更新 timeout](https://github.com/openkruise/agents/blob/41f676c7adb3cae4a72f8867a4b57ced6b4924cf/pkg/servers/e2b/pause_resume.go#L249-L337)
- [DeleteSandbox 的 recycle 分支](https://github.com/openkruise/agents/blob/41f676c7adb3cae4a72f8867a4b57ced6b4924cf/pkg/sandbox-manager/api.go#L442-L481)
- [Primary 选举和生命周期](https://github.com/openkruise/agents/blob/41f676c7adb3cae4a72f8867a4b57ced6b4924cf/pkg/sandbox-manager/leader.go)
