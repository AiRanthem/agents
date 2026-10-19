# Cursor 自主推进适配

适用于同一 Cursor harness 的所有使用形态。业务流程读取共享 `advance-project`
及其 coordinator / stage-executor 引用；本文件只定义宿主边界。
从已安装 skill 的物理路径找到本仓库并运行：

```sh
python3 <dev-kit-root>/scripts/host_agents.py check --host cursor
```

`disk_ready` 只检查磁盘模板与技能入口，不证明当前会话工具、模型访问或权限可用。
四个原生角色固定使用 Grok 4.7 的非 fast 变体；两类审查为 xhigh，实现和修复为 high。
本机默认检查 `~/.cursor/agents/` 的仓库链接。云端项目角色通过 `check --host cursor
--agents-dir <project>/.cursor/agents --skills-dir <cloud-skills>` 检查实际环境中的定义与技能。
显式目录中的角色可为内容一致的普通文件，技能可为完整副本；检查全部技能文件，忽略
`__pycache__`。原生注入使用 `--roles-file <loaded-roles.json>` 替代 `--agents-dir`：JSON
对象以四个原生角色名为键，各值包含完整 `name`、`description`、`model`、
`developer_instructions`，以及实际配置来源 `source`；配置字段可从 `role` 命令取得。
主控须按真实宿主配置填写来源并核对实际生效定义；该文件是待核对输入，不能证明宿主已加载。
显式来源会替代用户级角色检查，不能用用户级有效定义掩盖项目遮蔽。缺失或内容不匹配时报告 `missing` 并阻塞自主推进，
不能使用普通模式 Composer 路由、`inherit` 或猜测的型号补足。

| runtime role | 原生角色 | 固定 model |
| --- | --- | --- |
| design-review / design-revision | project-design-reviewer | grok-4.7[effort=xhigh,fast=false] |
| implementation / baseline / rebase | project-implementer | grok-4.7[effort=high,fast=false] |
| code-review | project-implementation-reviewer | grok-4.7[effort=xhigh,fast=false] |
| fix | project-fixer | grok-4.7[effort=high,fast=false] |

主控直接通过当前会话真实暴露的 Task / Agent 工具选择这些原生角色，确认实际发现来源
是已安装定义，未被项目级同名定义遮蔽；自然语言提及、`/name` 本身不是派发成功证据。
若工具没有原生角色选择但支持明确模型参数与干净上下文，可运行 `host_agents.py role
--host cursor --name <角色>`，将完整 `model`（包含 effort / fast 参数）和完整角色正文
传给实际工具，使用等价显式派发；不得只传名字后声称模板生效。
Cursor 用原生 `model: "ID[effort=VALUE,fast=false]"` 明确 effort 和标准速度。
官方说明账户、管理员或旧版 Max 设置可能令 Cursor 回退到兼容模型；若真实工具回执
或任务卡暴露的型号不同，按固定配置未满足处理，不能静默接受回退。若未暴露运行型号，
如实记录未验证，不另查执行者设置或账户。主控不按难度改变一级角色配置。

Cursor 允许主控 → 一级阶段执行者 → 后代（例如 quality reviewer）两跳；后代不能再派
更深一层，且当前模式必须保留 Task 工具。一级执行者组织后代并收尾。读多取证，以及
要求已定、结果可直接核对的有界执行，选择 `composer` 子代理并省略 Task 的 `model`，
使该文件中的 `composer-2.5[fast=false]` 生效。可并行的同类任务一并
派出，这些后代只返回证据或已定稿修改。合同判断、独立结论和后果性修改留在一级角色；
必须自行下结论的后代，包括必需的 quality 子代理和独立审查视角，由一级角色为其选择模型。
`composer` 子代理不可用时，报告该能力缺失并由一级角色完成该任务。为该派发设置 Task `model`，
包括 `inherit`、fast slug 或其他型号，不满足该要求。普通主会话的 `composer` 派发不替代这些一级角色。
必需的 quality 子代理无法启动时该审查阻塞，主控不能代审或伪造通过。主控只管理一级
任务，不逐个指定后代档位。

主控从当前真实会话元数据获取稳定身份并传给 runtime 的 `PROJECT_SESSION_ID`。
Cursor hook 的 `conversation_id` 在多轮间稳定；`sessionStart.session_id` 与其相同。
不能使用逐轮变化的 `generation_id`、worker ID 或随机值替代。无需为此新装 hook；
若当前会话完全不暴露身份，报告缺失能力并阻塞项目状态写入。

按共享 coordinator 合同捕获真实 spawn / completion / resume 回执，保存 `host=cursor`、
实际 `tool`、`worker_id` 和原始 `raw`。`call_id` 仅在真实工具直接暴露时记录，否则省略，
由 runtime 的 `coordinator-capture-sha256` 和 `attempt` 关联。不能用本地 ID 冒充宿主
call ID，也不读取私有 transcripts / logs 补取 ID。
后台任务返回的 agent ID 可用于恢复；等待与完成必须来自当前工具实际返回，不能从摘要
推断。一级执行者在主控登记并交付 `attempt`、`input_binding` 后才开始工作。

继承当前权限；原生 Plan 保持只读。文件可读不表示实际禁用的技能获准调用；发现隐藏
与实际禁用分别处理；本轮授权阶段按宿主允许的显式入口加载，不假称
`disable-model-invocation` 技能自动激活，实际禁用与工具政策仍生效。共享 skill、原生角色
及本仓库适配必须在实际执行环境可读；云端不具备本机文件时先按安装合同配置环境，
不从本机链接推断云端已安装。

## 宿主回执与暂停任务

使用共享的 [回执装配说明](../skills/advance-project/references/host-receipts.md)，通过
`host_agents.py receipt` 保留实际工具 raw 并从完整 accepted dispatch 派生结果绑定。
这个命令只装配主控实际捕获的数据，不运行代理，也不证明宿主签名或模型身份。
原生暂停确认结束后，用当前宿主可用的 follow-up / resume 操作向同一 worker 交付
accepted context 并唤醒任务；单向消息不一定会唤醒 idle worker。保持原 attempt，
正式结果仍要求实际终态及全部后代停止。
