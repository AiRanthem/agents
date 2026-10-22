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
9. 读取 `~/.qoder/settings.json` 的 `agents.overrides`。收录角色的 `model`、`effort` 与现有显式 `maxTurns` 以角色 frontmatter 为唯一事实来源；override 优先级更高，因此本步只核对不写入。运行 `python3 <dev-kit-root>/qoder/host.py check` 核对其报告中的身份 handler 和 override 缺口；`modelConfig.model`（与模板相同的裸模型 ID 也匹配）、`runConfig.maxTurns` 或其他已支持的模型配置覆盖与模板冲突时，展示准确差异并取得用户决定，不静默改写。`enabled: false` 或实际工具限制使所需角色不可用时报告能力缺口，保留这些设置；不因 override 列出 Agent 就额外拒绝配置。保留其他字段和未收录角色的整个条目。当前项目、local 与 `--settings` 可能覆盖用户设置，按实际运行来源另行核对；磁盘 helper 的覆盖范围以其报告为准。
10. 清理 `~/.qoder` 顶层：删除解析目标位于本目录、但文件名不属于本目录当前收录 status line 文件的软链接；删除文件名匹配 `statusline*.sh`、不属于本目录当前收录名称、且内容已由本目录 `statusline.sh` 或 `statusline-fmt-check.sh` 完整收录的普通文件。无法确认内容归属时展示差异并取得用户决定。保留其余无关文件和软链接。
11. 运行 `qoder --list-models`，确认固定模型 ID `qmodel_38max`（Qwen3.8-Max）与 `dfmodel`（DeepSeek-Flash）当前可选择；对照[官方模型文档](https://docs.qoder.com/cli/model.md)和当前参数面板确认二者分别支持 `xhigh` 与 `max` effort。显示名变化不构成自行换型授权；不支持时报告具体缺口，不换用其他模型或档位。

## 更新

仓库更新后重新执行安装流程。hook 与 status line 软链接直接使用仓库版本；角色是普通文件，仓库更新后须按安装流程重新复制为与仓库一致的内容；settings.json 中的身份 handler 与 `statusLine` 键在内容变化后重新合并，`agents.overrides` 只核对不写入。新增角色补装；移除角色只清理可确认由本仓库管理且源文件已删除的目标。`statusLine` 不需重启即生效；已打开的会话需要 `/agents reload` 或新会话才能加载角色变化，包含 frontmatter `maxTurns` 的变化。

## 验证

确认以下结果：

* `~/.qoder/agents` 中每个本目录收录的角色都是与仓库内容一致的普通文件，frontmatter 可解析且 `name` 与文件名一致。
* `~/.qoder/agents` 中没有指向本仓库 `qoder/agents/` 的遗留软链接；无关条目未被改动。
* `~/.qoder/hooks/session-identity.py` 链接目标是本目录的 `hooks/session-identity.py`。
* `~/.qoder/settings.json` 可被 JSON 解析，保留全部无关配置，且 `hooks.SessionStart` 包含身份 handler。
* `echo '{"hook_event_name":"SessionStart","session_id":"probe"}' | python3 ~/.qoder/hooks/session-identity.py` 输出的 JSON 中 `hookSpecificOutput.hookEventName` 为 `SessionStart`，`additionalContext` 指明 `PROJECT_SESSION_ID` 与 `probe`；stdin 非法 JSON、非对象或缺失有效 `session_id` 时非零退出且无输出。
* `~/.qoder/statusline.sh` 与 `~/.qoder/statusline-fmt-check.sh` 的软链接目标分别是本目录的对应文件，且本目录两个脚本可执行。
* `~/.qoder/settings.json` 的 `statusLine` 等于本目录 `settings-statusline.json`。
* 本目录收录角色的有效 override 不与 frontmatter 的固定模型、effort 或 `maxTurns` 冲突，所需角色未被禁用；核对结果保留来源与具体差异，未收录角色和无关字段未被改动。
* `~/.qoder` 顶层没有文件名匹配 `statusline*.sh`、且不属于本目录当前收录名称的普通文件或软链接。
* `echo '{"model":{"display_name":"Qwen3.8-Max"},"context_window":{"context_window_size":400000,"used_percentage":25}}' | bash ~/.qoder/statusline.sh` 标准输出非空，且首段包含 `Qwen3.8-Max`。
* 给定含 `transcript_path` 的 payload，status line 显示的 effort 与 context window 等于该 transcript 中最后一条 `runtime-config` 记录的 `reasoningEffort` 与 `contextWindow`，而非 `~/.qoder/settings.json` 的 `.model.preferences`；该记录 `generation.reasoning.enabled` 为 `false`、记录不存在或 `transcript_path` 缺失时不显示 effort。
* `bash ~/.qoder/statusline-fmt-check.sh` 输出包含 `ALL MATCH`。
* `python3 <dev-kit-root>/qoder/host.py check` 返回 `disk_ready=true`。仅据报告确认磁盘模板、技能入口、身份 handler 和 override 校验，不宣称真实派发通过。
* `qoder agents list` 发现四个原生角色且未标记 shadowed；`qoder skills list` 中共享技能的 Location 位于 `~/.agents/skills`。阶段会话未列出 skill 时，仍可用文件工具完整读取其已授权物理安装入口；实际禁用或拒绝不能绕过。
* 新主控会话收到 SessionStart 注入的准确 `PROJECT_SESSION_ID`，每条项目命令在同一命令导出它并使用本目录 `project.py` 入口；恢复/压缩后仍使用该会话身份。身份仅从本宿主 hook 提供的变量读取；该值不是执行者标签或型号证据。
* 新会话中四个角色实际按表中各阶段派发，使用干净隔离上下文；报告真实工具能力、贡献标签、指定报告和执行结果。当前子代理未暴露 Agent/follow-up 时直接完成阶段，单代理审查无需 quality 后代。真实回执未暴露型号则标记未验证；模板、列表、磁盘或身份检查均不能证明运行型号。

## 自主推进阶段角色

Qoder 专用 helper 为 `qoder/host.py`；按工作区规定选择 Python 3.11 或更高版本。
身份 hook 与 override 校验由本目录维护。

所有 Qoder 使用形态共用 `agents/*.md` 和[自主推进适配](AUTONOMY.md)。原生文件遵循
[官方 Subagent 格式](https://docs.qoder.com/cli/subagent.md)：Markdown + YAML
frontmatter，必填 `name`、`description`；四个角色固定 `model`（`"[显示名](模型 ID)"`
形式）、`effort`，并保留现有显式高值 `maxTurns`：实现角色为 `9999999`，其余为 `999999`。
这些仍是有限正整数，frontmatter 不接受 `unlimited`；不另设统一新上限。模板不写
`permissionMode`、`isolation`、`tools`，继承实际权限，不要求后台运行。

两类审查固定 Qwen3.8-Max / xhigh，实现与修复固定 DeepSeek-Flash / max；2026-10-19
按本机模型选择持久化、既有角色与参数面板解析模型 ID 为 `qmodel_38max` 与 `dfmodel`。
官方 Subagent 文档确认字段格式与 effort 档位；各型号当前可用档位仍须核对模型文档与
参数面板。不支持固定配置时报告具体缺口，不自行换型或降档。

角色按 AUTONOMY 的映射加载完整已授权 skill：design-review 用 `review-design`，
design-revision 用 `explore-design`；implementation 用 `implement-design`。
未列出 skill 或未暴露 Skill 工具不等于被禁用，可通过文件工具解析物理安装路径并
读取完整 `SKILL.md` 与适用阶段引用；实际拒绝、禁用与原生 Plan 仍然约束执行。

当前观察到的子代理工具集不含 Agent 或 follow-up 输入工具；一级阶段用干净隔离
上下文直接完成，不 fork 作者/主控历史，不模拟续接或后代。官方仅在 Agent 实际可用时
承诺后代派发，不据本次观察宣称所有 Qoder 运行时都禁止它。推进 code-review 选择
`review-implementation` 的 single-agent 模式，由一名合格独立审查者承担正确性、
可维护性、安全、验证和风险边界判断；没有强制 quality 后代。关键边界资格或必要
证据缺口仍阻止 Pass，其他场景遵循共享 skill 的模式边界。

安装后运行：

```sh
python3 <dev-kit-root>/qoder/host.py check
python3 <dev-kit-root>/qoder/host.py role --name project-implementer
```

`check` 应返回 `disk_ready=true`，并保留具体检查来源；`role` 返回可直接交给 Headless /
SDK `--agents` 的完整注入 JSON，以角色名为键，保留模板的 `description`、`effort`、
`maxTurns`；将 Markdown `model` 转为裸 ID（`qmodel_38max` / `dfmodel`），并将
`developer_instructions` 正文映射为官方字段 `prompt`。JSON 注入不解析 Markdown 模型链接。
项目命令使用 `<dev-kit-root>/qoder/project.py --root <project> COMMAND`；身份来自 SessionStart
hook 并在同一命令导出 `PROJECT_SESSION_ID`，不能用其他宿主变量代替。返回的项目恢复
命令保留本目录入口，不改变已有项目 schema 或历史身份，也不能证明执行者或模型身份。

主控提供的 contributor-session 标签必须对应真实贡献执行，记录累积作者和独立
审查者，不用于存活锁定；宿主未暴露 worker ID 时无需补取。新标签不能洗掉先前
实质作者归属。新会话仍须验证实际发现、派发、报告与身份注入；配置不是运行型号
证据，仅比较工具直接暴露的型号，未暴露则标记未验证，已暴露不匹配时不静默接受。
本次模板维护不自动更新 `~/.qoder/agents` 或 settings；按上方更新流程复制角色，
核对 hook / override，并 `/agents reload` 或重开会话后才能验证实际加载。
