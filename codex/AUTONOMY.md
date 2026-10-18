# Codex 自主推进适配

适用于同一 Codex harness 的所有使用形态。业务流程读取共享
`advance-project` 及其 coordinator / stage-executor 引用；本文件只定义宿主边界。
从已安装 `advance-project` 的物理路径回到本仓库，使用以下检查：

```sh
python3 <dev-kit-root>/scripts/host_agents.py check --host codex
```

检查只证明磁盘配置与技能入口就绪。实际权限、工具、模型访问、项目级覆盖及
原生角色发现仍以当前会话为准；不得把 `disk_ready` 当作真实派发证据。

| runtime role | 原生角色 | 一级配置 |
| --- | --- | --- |
| design-review / design-revision | project-design-reviewer | gpt-6.1-sol / xhigh |
| implementation / baseline / rebase | project-implementer | gpt-6.1-sol / medium |
| code-review | project-implementation-reviewer | gpt-6.1-sol / xhigh |
| fix | project-fixer | gpt-6.1-sol / medium |

主控直接选择安装在 `~/.codex/agents/` 的原生角色。使用当前工具 schema 实际提供的
角色选择参数；`task_name` 是任务名称，不能替代角色选择。若当前工具没有原生类型选择，
先运行 `host_agents.py role --host codex --name <角色>`，把输出的 `model`、
`model_reasoning_effort` 分别传给实际 spawn 工具的 model / reasoning_effort 参数，
设 `fork_turns: "none"`，并把完整 `developer_instructions` 加入阶段任务。这样完成同一
固定角色的显式派发；记录实际方式与参数，不伪称原生模板选择。只有两种路径均不能
实际执行、角色被覆盖或模型不可用时才报告阻塞。主控不按难度自动升档。
上述任务正文回退仅用于四个阶段角色，不能替代 Astra 子代理要求的持久策略重载。

一级执行者使用干净上下文（工具支持时设 `fork_turns: "none"`），接收最小充分输入，
不继承或复制 main 的动态路由正文。执行者可以自主选择后代模型、effort 和组织方式，
并负责其结果整合与资源收尾；一级固定配置不传播到后代。实际并发容量和工具限制生效，
主控只管理一级任务。`review-implementation` 所需 quality 子代理必须真实运行。
四个阶段模板提供 Luna high/max 的成本偏好，先按共享阶段合同判断委派收益并复用证据；
执行者根据完整任务所需能力判断偏好是否适用。

明确选择 Astra 后代时，使用原生 `astra-delegate` 角色并显式传入所选 model / effort。
该角色的持久 developer instructions 在压缩后重新加载子代理策略；`SubagentStart` 的
一次性上下文不足以覆盖压缩。宿主若不能选择该角色或提供等价持久指令，报告该 Astra
任务的能力缺口，不把普通任务正文或 `PostCompact` hook 当作持久配置。
用户指定其他原生角色时保留该角色；它须自带等价持久重载，或宿主支持合并持久指令。
若两者均无，则报告能力缺口，不替换用户角色。

项目主控身份使用 runtime 已识别的真实 Codex 会话元数据；不要把 worker ID、随机值
或每次命令的新值用作主控身份。需要 `PROJECT_SESSION_ID` 的客户端应从当前真实
会话元数据赋值；App Server 提供 `thread.sessionId`，不从 fork 的 thread ID 推导它。

主控按共享 coordinator 合同捕获 spawn / wait / follow-up 的真实调用与回执，保存
`host=codex`、实际 `tool`、`worker_id` 和原始 `raw`，交给项目 runtime。
`call_id` 仅在真实工具直接暴露时记录，否则省略，由 runtime 的
`coordinator-capture-sha256` 和 `attempt` 关联。不能用本地 ID 冒充宿主 call ID，
也不读取私有 transcripts / logs 补取 ID。
只记录原生回执直接暴露的实际模型/effort；未暴露则标记未验证，不额外检查执行者设置。
配置值与实际型号不能混作同一证据。执行者先等待主控登记，收到 `attempt` 和
`input_binding` 后才执行。恢复先用原生可用工具确认原任务状态，不以超时推断死亡。

继承真实 harness sandbox 和审批模式；原生 Plan 保持只读。技能发现隐藏可通过已授权
文件入口显式加载；本轮授权的阶段技能可按宿主允许的显式入口调用；`disable-model-invocation`
限制自动调用时不能假称自动激活。实际禁用或工具拒绝不能以读文件绕过。不能为减少阶段确认而放宽宿主权限。

## 宿主回执与暂停任务

使用共享的 [回执装配说明](../skills/advance-project/references/host-receipts.md)，通过
`host_agents.py receipt` 保留实际工具 raw 并从完整 accepted dispatch 派生结果绑定。
这个命令只装配主控实际捕获的数据，不运行代理，也不证明宿主签名或模型身份。
原生暂停确认结束后，用当前宿主可用的 follow-up / resume 操作向同一 worker 交付
accepted context 并唤醒任务；单向消息不一定会唤醒 idle worker。保持原 attempt，
正式结果仍要求实际终态及全部后代停止。
