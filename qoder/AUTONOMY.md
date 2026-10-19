# Qoder 自主推进适配

适用于同一 Qoder harness 的所有使用形态。业务流程读取共享 `advance-project`
及其 coordinator / stage-executor 引用；本文件只定义宿主边界。
从已安装 skill 的物理路径找到本仓库并运行：

```sh
python3 <dev-kit-root>/scripts/host_agents.py check --host qoder
```

`disk_ready` 只检查磁盘模板与技能入口，不证明当前会话工具、模型访问或权限可用。
四个原生角色固定具体型号：两类审查 Qwen3.8-Max / xhigh，实现和修复 DeepSeek-Flash / max。
原生 `model` 字段使用 `"[显示名](模型 ID)"` 形式；ID 于 2026-10-19 按本机 `/model`
持久化（`qmodel_38max`）、既有角色文件与模型参数面板（`dfmodel`）解析固定，effort
支持范围以[官方模型文档](https://docs.qoder.com/cli/model.md)为准。升级型号是一次明确
配置维护，不在运行时动态改用新的型号。当前环境不支持指定模型或 effort 档位时，
报告具体能力缺失，不降档。

| runtime role | 原生角色 | 固定 model / effort |
| --- | --- | --- |
| design-review / design-revision | project-design-reviewer | Qwen3.8-Max / xhigh |
| implementation / baseline / rebase | project-implementer | DeepSeek-Flash / max |
| code-review | project-implementation-reviewer | Qwen3.8-Max / xhigh |
| fix | project-fixer | DeepSeek-Flash / max |

主控直接通过当前会话真实暴露的 Agent 工具以 `subagent_type` 参数选择这些原生角色，
并用 `qoder agents list` 或 `/agents` 面板确认角色来自用户级安装、未被项目级、插件或
`--agents` 注入的同名定义遮蔽；自然语言提及或 `@name` 本身不是派发成功证据。Qoder
交互式 Agent 工具不接受 model / effort 参数：角色模型只随已安装定义生效。角色未被
发现或被遮蔽时，修复安装或报告阻塞，不用普通派发代替并声称模板生效。Headless 与
SDK 形态可用 `--agents` JSON 注入实现等价显式派发：运行 `host_agents.py role
--host qoder --name <角色>` 取得完整 `model`、`effort` 和 `developer_instructions`
写入注入定义；记录实际方式，不伪称原生角色选择。主控不按难度改变一级角色配置。

Qoder 的 Agent 工具是一次性派发，没有对运行中 worker 的原生暂停唤醒操作。主控以
后台形态（`run_in_background`）启动角色，在启动 prompt 中预先指定绝对派发文件路径、
阶段目录身份和等待要求；启动返回的真实结果即 spawn 回执，其 agent / task 身份就是
真实 `worker_id`。登记 dispatch 获得 ready 响应后，主控把完整响应工件写入预指定的
派发文件路径；该写入就是 Qoder 中向同一 worker 交付 accepted context 的等价操作。
执行者在任何阶段工作前等待该文件出现（可用有界阻塞检查），核对其 attempt、role、
`input_binding` 与获批合同和启动指派一致后才开始工作；文件缺失或绑定不符时报告
阻塞，不猜测上下文。等待与完成必须来自当前工具实际返回的终态通知或任务状态，
不能从摘要推断；`TaskStop` 只用于停止，不产生结果。

角色文件与 settings.json 的模型配置不是实际型号证据。只比较真实工具回执或任务卡
直接提供的信息；未暴露运行型号时如实记录未验证，不另查执行者设置或账户。暴露的
型号与固定配置不符时，按固定配置未满足处理，不静默接受回退。

Qoder 子代理在 Agent 工具对其保持可用时可继续派发子代理。`review-implementation`
必需的独立 quality 子代理和高风险独立视角必须真实运行并保留证据；无法启动时该审查
阻塞，主控不能代审或伪造通过。本适配不维护 subagent 委派路由规则，也不为后代设置
统一模型：除共享合同点名的任务外，一级执行者在实际宿主能力内选择后代模型、effort、
内部组织和收尾。主控只管理一级任务。

主控使用 SessionStart 身份 hook（`qoder/hooks/session-identity.py`）注入
`additionalContext` 的稳定身份，运行 project.py 的命令在同一命令内导出
`PROJECT_SESSION_ID=<session_id>`。Qoder hook 输入的 `session_id` 在多轮、恢复与
压缩间稳定；不能使用逐轮变化的值、worker ID 或随机值替代。hook 未安装、未生效或
当前会话不暴露身份时，报告缺失能力并阻塞项目状态写入。

继承当前权限模式；模板不写 `permissionMode`，不设置宽松权限或自动 worktree 隔离。
子代理不能自行收紧已继承的宽松权限，实际拒绝仍然生效。原生 Plan 保持只读。文件
可读不表示实际禁用的技能获准调用；`disable-model-invocation` 技能需要被允许的显式
调用。共享 skill、原生角色及本仓库适配必须在实际执行环境可读；Qoder 在用户级通过
`~/.agents/skills` 发现共享 skills，无需 `~/.qoder/skills` 重复链接。

## 宿主回执与收尾

使用共享的 [回执装配说明](../skills/advance-project/references/host-receipts.md)，通过
`host_agents.py receipt --host qoder` 保留实际工具 raw 并从完整 accepted dispatch
派生结果绑定；`tool` 记录实际调用的工具名（Agent 启动、终态通知或任务状态查询）。
这个命令只装配主控实际捕获的数据，不运行代理，也不证明宿主签名或模型身份。
accepted context 经派发文件交付后，正式结果仍要求实际终态及全部后代停止。
