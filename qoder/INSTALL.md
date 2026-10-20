# Qoder 配置安装与更新

本目录维护 Qoder 的自主阶段角色、会话身份 hook、CLI status line 和[自主推进适配](AUTONOMY.md)。
共享 skills 按 [`skills/INSTALL.md`](../skills/INSTALL.md) 安装为 `~/.agents/skills/<name>`
的独立软链接；Qoder 在用户级直接发现这些链接（`qoder skills list` 的 Location 可
核实），本目录不在 `~/.qoder/skills` 重复安装。本目录不维护主代理规则或 subagent
委派路由。

## 安装

1. 读取仓库根目录的 `AGENTS.md`，并读取维护当日与 Qoder Subagents、Skills、Hooks、Status Bar 和模型选择相关的官方文档（[Subagent](https://docs.qoder.com/cli/subagent.md)、[Skills](https://docs.qoder.com/cli/Skills.md)、[Hooks](https://docs.qoder.com/cli/hooks.md)、[Settings](https://docs.qoder.com/cli/settings.md)、[Model](https://docs.qoder.com/cli/model.md)）。
2. 解析本仓库的绝对路径，并确保 `~/.qoder/agents` 与 `~/.qoder/hooks` 存在。
3. 使用 `find qoder/agents -maxdepth 1 -name '*.md'` 发现本目录收录的角色模板，并校验每个文件 frontmatter 的 `name` 与文件名一致、`model` 与 `effort` 非空、`maxTurns` 为正整数。将每个 `~/.qoder/agents/<name>.md` 安装为与仓库内容一致的普通文件：Qoder 的 agent 发现不跟随软链接（2026-10-19 本机实测），角色不得安装为链接。现存目标为指向本仓库对应源文件的软链接时，以同内容普通文件替换该链接；内容一致的普通文件不改。已有目标不同且包含仓库未收录内容时，先展示准确差异并取得用户决定。保留 `~/.qoder/agents` 中仓库未收录的其他条目（如个人 agents）。
4. 清理时只移除可确认由本仓库管理且源文件已删除的目标；无法确认归属的普通文件保留并报告。移除指向本仓库 `qoder/agents/` 的遗留角色软链接。保留其余无关文件和软链接。
5. 将 `hooks/session-identity.py` 安装为 `~/.qoder/hooks/session-identity.py` 的绝对软链接，保留目录中无关文件；目标已正确链接时不修改，其他目标先比较并保留未收录内容。确认仓库脚本可执行。
6. 读取 `~/.qoder/settings.json`，在 `hooks.SessionStart` 数组合并一个 handler：`{"hooks": [{"type": "command", "command": "python3 ~/.qoder/hooks/session-identity.py", "timeout": 10}]}`。以 command 包含 `session-identity.py` 识别本仓库 handler：已存在则原位更新，不存在则追加到 `SessionStart` 数组末尾。保留其他顶层键、其他事件、同组无关 handler 及其顺序。写入前用 JSON 解析器验证完整结果。
7. 将 `statusline.sh` 与 `statusline-fmt-check.sh` 安装为 `~/.qoder/statusline.sh` 与 `~/.qoder/statusline-fmt-check.sh` 的绝对软链接，保留 `~/.qoder` 中的无关文件。目标已正确链接时不修改；目标是内容已由本目录完整收录的普通文件时替换为软链接；目标包含仓库尚未收录的内容时，先展示准确差异并取得用户决定。确认本目录两个脚本可执行。
8. 读取 `~/.qoder/settings.json` 与本目录的 `settings-statusline.json`，将后者作为 `statusLine` 键写入目标并覆盖同名键。以 `statusLine.command` 引用 `~/.qoder/statusline.sh` 识别本仓库的 status line：不存在时写入 `statusLine`，存在时更新为 `settings-statusline.json` 的完整内容。保留目标中仓库未列出的其他键。写入前用 JSON 解析器验证完整结果。
9. 读取 `~/.qoder/settings.json` 的 `agents.overrides`。收录角色的 `model`、`effort` 与 `maxTurns` 以角色 frontmatter 为唯一事实来源；override 优先级高于 frontmatter，因此本步只核对不写入。对每个收录角色，其 override 的 `modelConfig.model` 或 `runConfig.maxTurns` 与 frontmatter 声明不一致时，展示准确差异并取得用户决定，不静默改写。保留 `enabled`、其他 override 字段，以及仓库未收录角色（如个人 agents）的整个条目。
10. 清理 `~/.qoder` 顶层：删除解析目标位于本目录、但文件名不属于本目录当前收录 status line 文件的软链接；删除文件名匹配 `statusline*.sh`、不属于本目录当前收录名称、且内容已由本目录 `statusline.sh` 或 `statusline-fmt-check.sh` 完整收录的普通文件。无法确认内容归属时展示差异并取得用户决定。保留其余无关文件和软链接。
11. 运行 `qoder --list-models`，确认 `Qwen3.8-Max` 与 `DeepSeek-Flash` 当前仍可选择；对照[官方模型文档](https://docs.qoder.com/cli/model.md)确认二者仍分别支持 `xhigh` 与 `max` effort。不支持时报告具体缺口，不换用其他模型或档位。

## 更新

仓库更新后重新执行安装流程。hook 与 status line 软链接直接使用仓库版本；角色是普通文件，仓库更新后须按安装流程重新复制为与仓库一致的内容；settings.json 中的身份 handler 与 `statusLine` 键在内容变化后重新合并，`agents.overrides` 只核对不写入。新增角色补装；移除角色只清理可确认由本仓库管理且源文件已删除的目标。`statusLine` 不需重启即生效；已打开的会话需要 `/agents reload` 或新会话才能加载角色变化，包含 frontmatter `maxTurns` 的变化。

## 验证

确认以下结果：

* `~/.qoder/agents` 中每个本目录收录的角色都是与仓库内容一致的普通文件，frontmatter 可解析且 `name` 与文件名一致。
* `~/.qoder/agents` 中没有指向本仓库 `qoder/agents/` 的遗留软链接；无关条目未被改动。
* `~/.qoder/hooks/session-identity.py` 链接目标是本目录的 `hooks/session-identity.py`。
* `~/.qoder/settings.json` 可被 JSON 解析，保留全部无关配置，且 `hooks.SessionStart` 包含身份 handler。
* `echo '{"hook_event_name":"SessionStart","session_id":"probe"}' | python3 ~/.qoder/hooks/session-identity.py` 输出的 JSON 含 `additionalContext` 且包含 `probe`；stdin 非法 JSON 或缺失 `session_id` 时非零退出且无输出。
* `~/.qoder/statusline.sh` 与 `~/.qoder/statusline-fmt-check.sh` 的软链接目标分别是本目录的对应文件，且本目录两个脚本可执行。
* `~/.qoder/settings.json` 的 `statusLine` 等于本目录 `settings-statusline.json`。
* `~/.qoder/settings.json` 的 `agents.overrides` 中，本目录收录角色的 `modelConfig.model` 与 `runConfig.maxTurns` 等于该角色 frontmatter 声明；未收录角色的条目未被改动。
* `~/.qoder` 顶层没有文件名匹配 `statusline*.sh`、且不属于本目录当前收录名称的普通文件或软链接。
* `echo '{"model":{"display_name":"Qwen3.8-Max"},"context_window":{"context_window_size":400000,"used_percentage":25}}' | bash ~/.qoder/statusline.sh` 标准输出非空，且首段包含 `Qwen3.8-Max`。
* 给定含 `transcript_path` 的 payload，status line 显示的 effort 与 context window 等于该 transcript 中最后一条 `runtime-config` 记录的 `reasoningEffort` 与 `contextWindow`，而非 `~/.qoder/settings.json` 的 `.model.preferences`；该记录 `generation.reasoning.enabled` 为 `false`、记录不存在或 `transcript_path` 缺失时不显示 effort。
* `bash ~/.qoder/statusline-fmt-check.sh` 输出包含 `ALL MATCH`。
* `python3 <dev-kit-root>/scripts/host_agents.py check --host qoder` 返回 `disk_ready=true`。
* `qoder agents list` 发现四个原生角色且未标记 shadowed；`qoder skills list` 中共享技能的 Location 位于 `~/.agents/skills`。
* 新会话中四个角色实际可派发、身份注入生效。磁盘与列表检查不等同于真实派发或运行型号证据。

## 自主推进阶段角色

宿主配置 helper `scripts/host_agents.py` 需要 Python 3.11 或更高版本（使用标准库 `tomllib`）；按当前工作区规定选择满足此要求的解释器。

所有 Qoder 使用形态共用 `agents/*.md` 和[自主推进适配](AUTONOMY.md)。原生文件遵循
[官方 Subagent 格式](https://docs.qoder.com/cli/subagent.md)：Markdown + YAML
frontmatter，必填 `name`、`description`；四个自主阶段角色同时固定 `model`（`"[显示名](模型 ID)"`
形式）、`effort` 和 `maxTurns`。`maxTurns` 是正整数，取值大到不构成单次派发的实际轮次上限；
frontmatter 不接受 `unlimited`。模板不写 `permissionMode`、`isolation`、`tools` 或后代委派规则。

本轮经用户确认，两类审查固定 Qwen3.8-Max / xhigh，实现与修复固定 DeepSeek-Flash / max；
2026-10-19 按本机 `qoder --list-models`、`/model` 持久化和既有角色文件解析模型 ID 为
`qmodel_38max` 与 `dfmodel`。官方确认 `effort` 支持 `xhigh` 与 `max` 档位；各模型可用
档位以官方模型文档为准。若当前环境不支持指定模型或档位，报告具体能力缺失，不降档。

安装后运行：

```sh
python3 <dev-kit-root>/scripts/host_agents.py check --host qoder
python3 <dev-kit-root>/scripts/host_agents.py role --host qoder --name project-implementer
```

第一条应返回 `disk_ready=true`；第二条返回原生角色完整配置与正文，供 Headless / SDK
的 `--agents` 注入等显式派发使用。该检查只验证文件与技能入口，不能代替真实发现和
工具调用。新会话确认四原生角色已加载、无同名遮蔽，并核对执行者保留 Agent 工具，
使 `review-implementation` 必需的 quality 子代理可以真实运行；无法启动时报告阻塞。
配置文件不是实际型号证据；只比较真实工具回执或任务卡直接提供的信息，未暴露则标记
未验证，发现不匹配不得静默接受。
