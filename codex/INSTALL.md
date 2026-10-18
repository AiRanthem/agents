# Codex 配置安装与更新

本目录维护个人 Codex 全局指令、专用 skills 和需要合并到现有配置的 hooks。

## 指令来源与注入范围

* `AGENTS.md` 保存主 Agent 与子 Agent 共用的通用规则。
* `prompts/delegation.md` 维护普通主 Agent 的职责边界；`delegation-subagent.md` 维护子 Agent 在父任务内的职责边界。二者复用 `delegation-task.md`、`delegation-evidence.md`、`delegation-lifecycle.md`，分别维护任务上下文、证据复用和生命周期。`delegation-astra.md` 保留完整五档路由；`delegation-sol.md` 仅维护 Luna high/max 委派范围，普通 Sol 主控保留代码编写与关键判断。用户指定角色和必需独立审查仍适用。
* `hooks/session-start.py` 和 `hooks/subagent-start.py` 通过共享组装器 `hooks/delegation.py`，根据 stdin JSON 的 `model` 选择正文。仅对 `gpt-` 前缀按 `-` 分段匹配完整家族名，支持后续代际与版本后缀。主会话的 Astra 输出主职责、共享片段及完整路由，Sol 输出主职责、共享片段及 Luna 路由，Luna 无委派输出；其他型号、相似名称、缺失字段或家族歧义只输出主职责和共享片段。子会话仅对明确的 Astra 输出子职责、共享片段及完整路由，其他模型均无输出。子职责服从父任务的权限、写入范围和审查门槛，不转移主控职责。
* 脚本只接受各自的事件，异类事件无输出；从脚本软链接的真实路径读取模块与正文，以相应 `hookEventName` 返回 `additionalContext`。输入错误或任一选中片段缺失、为空时返回非零状态，不输出残缺正文；未选中片段无需存在。Hook 是委派指导，失败不作为安全或权限门禁。
* `hooks.json` 在主会话 `startup`、`resume`、`clear`、`fork`、`compact` 时调用主入口；`SubagentStart` 的 `.*` matcher 匹配所有 agent type，由子入口判断模型。另一个 `compact` handler 始终保留指令重读提醒，包括 Luna 主会话。

依赖 `python3`。模型字段和子代理输出依据 [官方 hook 输入文档](https://learn.chatgpt.com/docs/hooks#common-input-fields) 及 [SubagentStart 文档](https://learn.chatgpt.com/docs/hooks#subagentstart)：使用事件提供的当前模型 slug，不从默认配置或历史 transcript 推测。子代理启动走 `SubagentStart`，其恢复或压缩不触发主会话的 `SessionStart`。完整历史 fork 会继承主上下文，因此要求 `fork_turns: "none"`，由父 Agent 提供最小充分任务上下文；子代理入口只注入适用于其任务的规则。Astra 委派必须选择原生 `astra-delegate` 角色并显式传入所选 model / effort；该角色不固定型号或档位，其持久 `developer_instructions` 要求启动和每次压缩后通过已安装入口重新读取完整子策略及原始 AGENTS。`SubagentStart.additionalContext` 会随压缩移除，`PostCompact` 不能注入策略正文，不用二者替代持久重载指令。宿主无法选择该角色或提供等价持久指令时，报告该 Astra 任务的能力缺口。升级 Codex 时重新检查事件与继承边界。

模型判断只在匹配的会话边界运行。在会话内切换模型不会重新触发 `SessionStart`，也不会撤回已有委派上下文；需要立即按新模型应用注入范围时，开启新会话。

## 安装

1. 读取仓库根目录的 `AGENTS.md`，并读取维护当日与 AGENTS.md、skills、hooks 和配置加载相关的官方 OpenAI 文档。
2. 解析本仓库的绝对路径，并确保 `~/.codex` 存在。
3. 检查 `~/.codex/AGENTS.override.md`。当该文件存在且非空时，说明它会优先于 `AGENTS.md`，展示两者差异并让用户选择保留、合并或移除。
4. 比较 `~/.codex/AGENTS.md` 与本目录的 `AGENTS.md`。当目标是普通文件且内容已由仓库完整收录时，将目标替换为指向本目录 `AGENTS.md` 的绝对软链接；当目标是软链接时，将链接更新为本目录的绝对路径；当目标包含仓库尚未收录的内容时，先展示差异并取得用户决定。
5. 确保 `~/.codex/hooks/` 存在，将 `session-start.py` 和 `subagent-start.py` 分别安装为本目录对应入口的绝对软链接。保留目录中的无关文件；目标已正确链接时不修改，其他目标先比较并保留未收录内容。共享模块和正文通过脚本真实路径读取，无需另装链接。
6. 读取 `~/.codex/hooks.json` 和本目录的 `hooks.json`，按事件合并 `hooks` 数组。以 `(event, matcher, statusMessage)` 识别仓库 handler：两个 `SessionStart` handler 为 `compact` / `Reloading Agent instructions` 和 `^(startup|resume|clear|fork|compact)$` / `Loading main-agent delegation`；`SubagentStart` 为 `.*` / `Loading Astra subagent delegation`。原位更新已存在的 handler；不存在时追加到相同 matcher 的组，无此组则在事件数组末尾追加。保留其他顶层字段、事件、matcher 和同组无关 handler，不重排原有条目，以保留其索引对应的信任状态。验证完整候选 JSON 后再替换目标文件。
7. 将本目录 `skills/` 中的各个 skill 以独立绝对软链接安装到 `~/.codex/skills/<name>`，保留 `.system` 和其他无关 skills。目标已正确链接时不做修改；目标是其他链接或普通文件、目录时，先检查差异，保留未收录内容并取得用户决定后再替换。
8. 使用 JSON 解析器验证合并后的 `~/.codex/hooks.json`，验证各个专用 skill 的 frontmatter，以及安装链接、事件匹配和脚本输出。委派正文应完整进入默认 2500 token 的上下文限额，超限时先精简或明确调整 `additionalContextLimit`，避免策略变成文件预览。运行 `codex --strict-config doctor --summary --no-color`，区分存量告警与本次新增问题。
9. 在 Codex 中打开 `/hooks`，审核并信任新增或发生变化的 hook 定义，再开启新会话加载配置。未信任的 hook 会被跳过；JSON 或 doctor 检查成功不代表 hook 已获信任。参见 [官方审核与信任说明](https://learn.chatgpt.com/docs/hooks#review-and-trust-hooks)。

## 更新

仓库更新后重新执行安装流程。`AGENTS.md`、hook 脚本和专用 skill 软链接会直接使用仓库版本；新增 skill 需要补链。删除 skill 时，仅清理目标位于本目录 `skills/` 内的对应失效链接。hooks 定义需要重新合并并在内容变化后重新审核信任。提示词正文在下一次匹配的会话边界重新读取，当前会话中已有的指令不会因磁盘修改自动消失。

## 子代理线程上限

在 `~/.codex/config.toml` 的现有 `[agents]` 段中合并以下配置，保留其他字段；若存在旧别名 `max_threads`，移除该别名以避免重复配置：

```toml
[agents]
max_concurrent_threads_per_session = 20
```

该值限制同时打开的子代理线程数，不含主线程。以 [OpenAI 配置参考](https://learn.chatgpt.com/docs/config-file/config-reference#configtoml) 为准。更新后验证 TOML 并运行 `codex --strict-config doctor --summary --no-color`；重新启动本地 Codex 会话加载配置。此设置不保证改变托管会话的并发限制。

## 验证

确认以下结果：

* `~/.codex/AGENTS.md` 的软链接目标是本目录的 `AGENTS.md`。
* `~/.codex/AGENTS.override.md` 的处理结果符合用户选择。
* `~/.codex/skills` 中不存在指向本目录已删除 skill 的失效链接。
* 两个已安装 hook 入口链接均指向本目录，能够读取共享模块和选中正文。
* `~/.codex/hooks.json` 保留原有无关 hooks 及其顺序，并包含两个 `SessionStart` 和一个 `SubagentStart` handler。
* 主入口覆盖五个来源和 Astra/Sol/Luna 路由；子入口仅注入 Astra。通过安装链接验证后续代际完整段、相似名称、缺失或歧义型号、异类事件及主/子职责隔离。使用临时副本验证选中片段缺失或空白时报错、未选中片段互不依赖。Luna 主会话在 `compact` 时仍收到独立的指令重读提醒。可运行 `python3 -m unittest discover -s codex/hooks -p 'test_*.py'`，包含持久角色通过安装入口加载完整策略的检查；这不证明实际会话事件或自动压缩已触发。
* 共享 `AGENTS.md` 不包含委派正文或加载指令；主职责仅进入普通主会话，子职责仅进入 Astra 子代理。自主阶段的 Luna 偏好由四个原生角色模板提供，Astra 后代通过 `astra-delegate` 的持久指令在启动和压缩后读取共享规则与完整路由；父任务授权和阶段边界始终适用。
* `codex --strict-config doctor --summary --no-color` 加载配置且无新增失败；实际信任状态通过 `/hooks` 核实。脚本检查和源码证据不等同于真实模型会话、子代理或自动压缩的端到端验证。

## 自主推进阶段角色

宿主配置 helper `scripts/host_agents.py` 需要 Python 3.11 或更高版本（使用标准库 `tomllib`）；按当前工作区规定选择满足此要求的解释器。

所有 Codex 使用形态共用 `agents/*.toml` 和 [自主推进适配](AUTONOMY.md)。原生文件遵循
[OpenAI Subagents 的独立 TOML 格式](https://learn.chatgpt.com/docs/agent-configuration/subagents#custom-agents)：
必填 `name`、`description`、`developer_instructions`；四个自主阶段角色同时固定 `model` 和
`model_reasoning_effort`；普通 `astra-delegate` 只提供持久策略加载指令，model / effort
由父派发显式指定。角色不写父会话的 sandbox、审批或 provider 设置。

安装时发现本目录 `agents/*.toml`，逐个解析 TOML 并校验 name 与文件名一致；将每个
`~/.codex/agents/<name>.toml` 安装为与仓库内容一致的普通文件。保留同目录无关文件。
现存目标为指向本仓库对应源文件的软链接时，以同内容普通文件替换该链接；内容一致的
普通文件不改。已有目标不同且包含仓库未收录内容时，先展示准确差异并取得用户决定。
清理时只移除可确认由本仓库管理且源文件已删除的目标；无法确认归属的普通文件保留并报告。

`host_agents.py check` 检查四个自主阶段角色，要求普通 TOML 文件并校验完整内容；普通
`astra-delegate.toml` 也须按上述流程安装并在新会话核对原生发现，未发现时不能只靠 hook
派发 Astra 子代理。共享 skill
使用独立软链接。磁盘检查之后，仍需通过实际派发确认原生角色可用。

与共享 skills 安装配合，确认 `advance-project` 和四阶段所需共享技能均可读。运行：

```sh
python3 <dev-kit-root>/scripts/host_agents.py check --host codex
python3 <dev-kit-root>/scripts/host_agents.py role --host codex --name project-implementer
```

第一条返回 `disk_ready=true`；第二条返回原生角色完整配置与正文，供仅支持显式 model /
effort 的委派工具使用。四个模板固定 Sol 6.1：两类审查 xhigh，实现与修复 medium。
主控 hook 的动态档位路由只适用于普通主会话，自主主控按角色选固定配置，后代由阶段
执行者自行选择。阶段模板为值得委派且边界明确的任务提供 Luna high/max 偏好，并明确
派发时设置模型与 effort；执行者根据完整任务所需能力判断偏好是否适用。原有普通
路由的模型规则与 Luna 注入边界继续适用。

使用临时 `CODEX_HOME`、候选 TOML / 链接运行 `codex --strict-config doctor` 与
`codex debug prompt-input`，确认无新增配置错误；`prompt-input` 不输出完整工具 / custom agent 定义，角色发现需由真实
会话核对，不能从此命令推断。不要把临时目录验证
当作真实会话派发。正式安装后开启新会话核对原生角色发现和真实工具选择能力。
当工具不支持 native 角色选择但支持明确模型、effort 和干净上下文时，可由 `role`
命令读取完整正文，以实际显式派发实现同一角色；记录实际方式，不伪称原生类型调用。
模板不限制执行者后代的模型和档位，也不为规避确认改变权限。

上述任务正文回退仅用于四个自主阶段角色，不能代替 Astra 子代理的持久策略重载。
用户指定其他原生角色时保留它，只有该角色自带等价重载或宿主支持真正持久的指令注入
才能满足 Astra 重载；否则报告能力缺口，不用 task 正文模拟双角色配置。

会话身份与权限以 [OpenAI App Server](https://learn.chatgpt.com/docs/app-server#start-or-resume-a-thread)
和 [Subagents 权限说明](https://learn.chatgpt.com/docs/agent-configuration/subagents#approvals-and-sandbox-controls)
为准；当前会话未暴露的运行型号标为未验证，不从配置推断它实际运行。
