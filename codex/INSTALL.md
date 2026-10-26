# Codex 配置安装与更新

本文定义本目录内容向 Codex 的安装、更新、清理和验证方式。配置与提示词内容以仓库源文件为准。

## Cloud Agent 首次初始化

全新环境可直接运行安装脚本，无需先启动 Agent 阅读安装文档。依赖 Python 3.11+ 和本仓库完整工作副本，无第三方 Python 依赖；脚本不安装 Codex 可执行程序，也不配置登录凭据。

```sh
python3 /absolute/path/to/dev-kit/codex/install.py
```

脚本以自身真实路径定位仓库，安装全局指令、两个 hook 入口、全部共享及原生 skill 链接、原生角色普通文件和 hooks 定义，并生成线程上限与重复技能来源禁用配置。仓库必须在后续 Agent 运行期间保留原路径。

默认安装到当前用户的 `~/.codex` 与 `~/.agents/skills`；`--home <directory>` 可指定初始化目标用户目录。若设置了 `CODEX_HOME`，必须与目标目录的 `.codex` 一致。基础镜像可以预置其他模型、provider、MCP 等配置：脚本保留已有 `config.toml` 字节与权限，追加本 kit 的配置；已有 `[agents]` 或 `skills.config` 时停止，交由 Agent 整合。保留认证文件、`.system` 和无关 skills。

脚本先检查全部目标。任何待安装目标已存在、非空 `AGENTS.override.md`、无效配置或安装父目录软链接都会使它以非零状态退出，不覆盖已有内容。此入口只用于首次初始化；已有 kit 的升级继续使用 Agent 和下文契约。文件系统故障可能留下部分安装，初始化任务应失败并重建临时环境。

成功时输出 JSON `status=disk_ready`，表示安装文件及现有磁盘检查通过，`runtime_verified=false`。可在镜像提供 Codex CLI 时继续运行：

```sh
codex --strict-config doctor --summary --no-color
codex debug prompt-input
```

这两条命令检查配置加载，不调用模型。真实 cloud 环境的技能发现、角色派发及 hook 事件仍需该环境验证。脚本不修改 hook 信任记录；支持交互审核的环境须通过 `/hooks` 信任新增定义，再开启 Agent 会话。cloud 执行器的信任与事件支持由执行器决定，磁盘安装成功不证明 hooks 已执行。

本地回归检查：`python3 -m unittest discover -s codex -p 'test_install.py'`。

## 安装来源

* `AGENTS.md`：安装到 `~/.codex/AGENTS.md` 的全局指令源文件。
* `hooks/session-start.py`、`hooks/subagent-start.py`：安装到 `~/.codex/hooks/` 的入口脚本，依赖 `python3`。
* `hooks/delegation.py`、`prompts/`：由入口脚本通过其真实路径读取的模块和提示词，无需单独复制。
* `hooks.json`：合并到 `~/.codex/hooks.json` 的 hook 定义。
* `skills/`、`agents/*.toml`：分别按下文安装为独立 skill 软链接和原生角色普通文件。

委派行为由 [prompts/](prompts/) 与 [agents/](agents/) 维护，自主项目宿主协议见 [AUTONOMY.md](AUTONOMY.md)。

## 安装

1. 读取仓库根目录的 `AGENTS.md`，并读取维护当日与 AGENTS.md、skills、hooks 和配置加载相关的官方 OpenAI 文档。
2. 解析本仓库的绝对路径，并确保 `~/.codex` 存在。
3. 检查 `~/.codex/AGENTS.override.md`。当该文件存在且非空时，说明它会优先于 `AGENTS.md`，展示两者差异并让用户选择保留、合并或移除。
4. 比较 `~/.codex/AGENTS.md` 与本目录的 `AGENTS.md`。当目标是普通文件且内容已由仓库完整收录时，将目标替换为指向本目录 `AGENTS.md` 的绝对软链接；当目标是软链接时，将链接更新为本目录的绝对路径；当目标包含仓库尚未收录的内容时，先展示差异并取得用户决定。
5. 确保 `~/.codex/hooks/` 存在，将 `session-start.py` 和 `subagent-start.py` 分别安装为本目录对应入口的绝对软链接。保留目录中的无关文件；目标已正确链接时不修改，其他目标先比较并保留未收录内容。共享模块和正文通过脚本真实路径读取，无需另装链接。
6. 读取 `~/.codex/hooks.json` 和本目录的 `hooks.json`，按事件合并 `hooks` 数组。以 `(event, matcher, statusMessage)` 识别仓库 handler：两个 `SessionStart` handler 为 `compact` / `Reloading Agent instructions` 和 `^(startup|resume|clear|fork|compact)$` / `Loading main-agent delegation`；`SubagentStart` 为 `.*` / `Loading Astra subagent delegation`。原位更新已存在的 handler；不存在时追加到相同 matcher 的组，无此组则在事件数组末尾追加。保留其他顶层字段、事件、matcher 和同组无关 handler，不重排原有条目，以保留其索引对应的信任状态。验证完整候选 JSON 后再替换目标文件。
7. 按下文“专属技能元数据与重复发现”安装本目录 `skills/` 的独立绝对软链接和发现配置，保留 `.system` 与其他无关 skills。已正确链接的目标不改；指向本仓库公共同名 skill 的链接改为原生入口。其他链接、普通文件或目录先比较，含未收录内容时取得用户决定后替换。
8. 使用 JSON 解析器验证合并后的 `~/.codex/hooks.json`，验证各个专用 skill 的 frontmatter，以及安装链接、事件匹配和脚本输出。检查 hook 输出是否完整进入已配置的 `additionalContextLimit`；若被截断，报告配置缺口，保留提示词源文件内容。运行 `codex --strict-config doctor --summary --no-color`，区分存量告警与本次新增问题。
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
* 通过安装链接验证入口能加载完整源文件。运行 `python3 -m unittest discover -s codex/hooks -p 'test_*.py'`，检查事件匹配、模型条件选择、主/子输出隔离、错误输入、缺失或空白片段及原生角色加载入口。测试通过不证明真实会话事件或自动压缩已触发。
* `codex --strict-config doctor --summary --no-color` 加载配置且无新增失败；实际信任状态通过 `/hooks` 核实。脚本检查和源码证据不等同于真实模型会话、子代理或自动压缩的端到端验证。

## 原生角色安装

宿主配置 helper `codex/host.py` 需要 Python 3.11 或更高版本（使用标准库 `tomllib`）；按当前工作区规定选择满足此要求的解释器。

原生文件遵循
[OpenAI Subagents 的独立 TOML 格式](https://learn.chatgpt.com/docs/agent-configuration/subagents#custom-agents)：
校验必填的 `name`、`description`、`developer_instructions`，其余字段按源文件完整保留。

安装时发现本目录 `agents/*.toml`，逐个解析 TOML 并校验 name 与文件名一致；将每个
`~/.codex/agents/<name>.toml` 安装为与仓库内容一致的普通文件。保留同目录无关文件。
现存目标为指向本仓库对应源文件的软链接时，以同内容普通文件替换该链接；内容一致的
普通文件不改。已有目标不同且包含仓库未收录内容时，先展示准确差异并取得用户决定。
清理时只移除可确认由本仓库管理且源文件已删除的目标；无法确认归属的普通文件保留并报告。

`host.py check` 检查四个自主阶段角色，要求普通 TOML 文件并校验完整内容；
`astra-delegate.toml` 也须按上述流程安装并单独核对内容。共享 skill 使用独立软链接。

与共享 skills 安装配合，确认 `advance-project` 和四阶段所需共享技能均可读。运行：

```sh
python3 <dev-kit-root>/codex/host.py check
python3 <dev-kit-root>/codex/host.py role --name project-implementer
```

第一条应返回 `disk_ready=true`；第二条返回的原生角色完整配置与正文应与源文件一致。

使用临时 `CODEX_HOME`、候选 TOML / 链接运行 `codex --strict-config doctor` 与
`codex debug prompt-input`，确认无新增配置错误；`prompt-input` 不输出完整工具或原生角色定义。
正式安装后开启新会话核对原生角色发现和真实工具选择能力。磁盘和临时目录检查只证明
安装内容与配置加载就绪，实际派发尚未执行时应单独标为未验证。

## 共享入口与官方依据

执行本目录安装后，再执行 [共享技能安装](../skills/INSTALL.md)。项目命令使用
`python3 <dev-kit-root>/codex/project.py --root <project> COMMAND`；返回续接命令含准确身份的环境参数，原样执行，不依赖上一条 shell 的环境。
自主推进先加载 [AUTONOMY.md](AUTONOMY.md)，再进入共享技能。

- [Custom instructions with AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [Build skills](https://learn.chatgpt.com/docs/build-skills)
- [Prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)

## 专属技能元数据与重复发现

`skills/<name>/SKILL.md` 是轻量原生入口，完整读取公共 skill；`agents/openai.yaml`
只在本目录中提供界面和调用策略。保持四个显式技能的 `allow_implicit_invocation: false`
及其他既有策略，不把公共来源作为第二个可隐式调用的同名技能。

运行 `python3 <dev-kit-root>/codex/skill_entries.py` 取得精确安装清单：将 `source`
按前述保留数据规则链接到 `target`，并把每项 `config` 按 `path` 合并进用户
`~/.codex/config.toml` 的 `[[skills.config]]`，保留无关条目。原生入口的路径不得禁用；
公共物理路径和用户级链接路径均禁用发现，但仍允许原生入口完整读取公共文件。
不要删除公共 `~/.agents/skills` 链接，其他宿主仍使用它。
运行 `python3 <dev-kit-root>/codex/skill_entries.py --check` 核对原生入口链接与重复来源
禁用配置；该检查只报告事实，不修改配置，`runtime_verified=false` 不代表真实调用通过。

官方 [Build skills](https://learn.chatgpt.com/docs/build-skills) 说明同名技能不会合并，
`agents/openai.yaml` 控制界面与调用策略，`[[skills.config]]` 可禁用特定来源。
用临时 `CODEX_HOME` 安装候选链接及配置并运行 `codex debug prompt-input`，确认
每个允许隐式调用的同名技能只出现一次且来源在本目录，四个显式技能不进入自动
发现候选，元数据和调用策略与源文件一致；再执行正式合并。
新会话才加载目录与调用策略变更，配置解析通过不等于真实技能或阶段已执行。
