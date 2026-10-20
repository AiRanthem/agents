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

推进 agent 直接向原生阶段角色交付完整当前合同、源代码位置、基线与允许输出路径，
并自行维护真实任务 ID、等待、结果整合和后代资源收尾。项目状态只保存内容绑定的
成果、实际作者及独立审查证据，不登记执行者或以其存活状态锁住工作项。跨宿主接管
从当前可访问成果继续；原宿主任务不可查询时，不要求恢复旧任务或用户证明其停止。
实际代码写入协调与必要隔离由推进 agent 负责。只报告工具直接暴露的型号与执行事实，
未暴露则标记未验证，不读取私有会话日志补取身份或伪造回执。

继承真实 harness sandbox 和审批模式；原生 Plan 保持只读。技能发现隐藏可通过已授权
文件入口显式加载；本轮授权的阶段技能可按宿主允许的显式入口调用；`disable-model-invocation`
限制自动调用时不能假称自动激活。实际禁用或工具拒绝不能以读文件绕过。不能为减少阶段确认而放宽宿主权限。
