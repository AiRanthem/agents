# Codex 配置安装与更新

本文定义本目录内容向 Codex 的安装、更新、清理和验证方式。配置与提示词内容以仓库源文件为准。

## Cloud Agent 首次初始化

全新环境可直接运行安装脚本，无需先启动 Agent 阅读安装文档。依赖 Python 3.11+ 和本仓库完整工作副本，无第三方 Python 依赖；脚本不安装 Codex 可执行程序，也不配置登录凭据。

```sh
python3 /absolute/path/to/dev-kit/codex/install.py
```

脚本以自身真实路径定位仓库，安装全局指令、会话启动 hook、全部共享及原生 skill 链接和 hooks 定义，并生成线程上限与重复技能来源禁用配置。仓库必须在后续 Agent 运行期间保留原路径。

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
* `hooks/session-start.py`：安装到 `~/.codex/hooks/` 的会话启动脚本，依赖 `python3`，通过自身真实路径读取 `prompts/` 中的提示词。
* `hooks.json`：合并到 `~/.codex/hooks.json` 的 hook 定义。
* `skills/` 下的每个宿主技能安装为独立的目录软链接。

主代理启动 hook 按模型选择简短指引及文件路径，Luna 跳过此注入。主代理在开始或恢复委派时，再从所列路径读取适用的[委派细则](prompts/)。

## 安装

1. 读取仓库根目录的 `AGENTS.md`，并读取维护当日与 AGENTS.md、skills、hooks 和配置加载相关的官方 OpenAI 文档。
2. 解析本仓库的绝对路径，并确保 `~/.codex` 存在。按[共享安装的目标归属规则](../skills/INSTALL.md#安装)处理现有链接及失效链接。
3. 检查 `~/.codex/AGENTS.override.md`。当该文件存在且非空时，说明它会优先于 `AGENTS.md`，展示两者差异并让用户选择保留、合并或移除。
4. 将 `~/.codex/AGENTS.md` 安装为指向本目录 `AGENTS.md` 的绝对软链接。普通文件逐字匹配本仓库当前或已知安装版本时可替换成链接。目标包含本地改动或归属不明时先展示差异并取得用户决定。
5. 确保 `~/.codex/hooks/` 存在，将 `session-start.py` 安装为本目录对应入口的绝对软链接。普通文件逐字匹配本仓库当前或已知安装版本时可替换。目标包含本地改动或归属不明时先展示差异并取得用户决定。提示词通过入口脚本的真实路径读取。
6. 读取 `~/.codex/hooks.json` 和本目录的 `hooks.json`，按事件合并 `hooks` 数组。以 `(event, matcher, statusMessage)` 识别仓库 handler：两个 `SessionStart` handler 为 `compact` / `Reloading Agent instructions` 和 `^(startup|resume|clear|fork|compact)$` / `Loading main-agent delegation`。原位更新已存在的 handler；不存在时追加到相同 matcher 的组，无此组则在事件数组末尾追加。保留其他顶层字段、事件、matcher 和同组无关 handler，不重排原有条目，以保留其索引对应的信任状态。验证完整候选 JSON 后再替换目标文件。
7. 按[共享技能安装](../skills/INSTALL.md)同步用户级共享链接，再按下文“专属技能与发现配置”安装本目录的宿主技能。保留 `.system`、外部同名链接和本地定制。需要替换归属不明的内容时，先展示差异并取得用户决定，继续处理其他条目。
8. 使用 JSON 解析器验证合并后的 `~/.codex/hooks.json`，验证各个专用 skill 的 frontmatter，以及安装链接、事件匹配和脚本输出。检查 hook 输出是否完整进入已配置的 `additionalContextLimit`；若被截断，报告配置缺口，保留提示词源文件内容。运行 `codex --strict-config doctor --summary --no-color`，区分存量告警与本次新增问题。
9. 在 Codex 中打开 `/hooks`，审核并信任新增或发生变化的 hook 定义，再开启新会话加载配置。未信任的 hook 会被跳过；JSON 或 doctor 检查成功不代表 hook 已获信任。参见 [官方审核与信任说明](https://learn.chatgpt.com/docs/hooks#review-and-trust-hooks)。

## 更新

仓库更新后重新执行安装流程。`AGENTS.md`、hook 脚本和技能链接直接使用仓库版本。普通技能随共享安装更新，专属入口按下文核对。hooks 定义重新合并并在变化后重新审核信任。提示词正文在下一次匹配的会话边界重新读取。

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
* 已安装的会话启动脚本链接指向本目录，能从仓库读取选中的提示词。
* `~/.codex/hooks.json` 保留原有无关 hooks 及其顺序，并包含仓库定义的两个 `SessionStart` handler。
* 通过安装链接验证入口能加载完整源文件。运行 `python3 -m unittest discover -s codex/hooks -p 'test_*.py'`，检查事件匹配、模型选择、错误输入及缺失或空白的提示词。测试通过不证明真实会话事件或自动压缩已触发。
* `codex --strict-config doctor --summary --no-color` 加载配置且无新增失败；实际信任状态通过 `/hooks` 核实。脚本检查和源码证据不等同于真实模型会话、子代理或自动压缩的端到端验证。

## 共享入口与官方依据

共享 [install](../skills/install/SKILL.md#source-and-selection) 在目标宿主为 Codex 时选择本文。公共技能源位于仓库 `skills/<name>/`。

- [Custom instructions with AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [Build skills](https://learn.chatgpt.com/docs/build-skills)
- [Prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)

## 专属技能与发现配置

Codex 从 `~/.agents/skills/<name>` 直接发现公共技能。`adapt-agent-routing` 另有一个安装到 `~/.codex/skills/` 的宿主实现，负责路由评估、历史回放和宿主验证。

运行 `python3 <dev-kit-root>/codex/skill_entries.py` 取得安装清单，将每项 `source` 以独立绝对软链接安装至 `target`。共享链接就位后重新读取清单，按 `path` 合并各项 `config` 到 `~/.codex/config.toml` 的 `[[skills.config]]`。只有同名宿主实现替代公共入口时才排除重复发现。用户级共享路径须确认为本仓库的同名链接后才禁用发现。如果同名路径由其他来源占用，保留该路径及已有配置，报告冲突并继续处理其他技能。

### 清理旧安装

* 对照已安装版本和当前清单，清理退役的 hook、入口链接和角色。仅移除与已知版本逐项匹配的 handler、能确认指向本检出的链接及与已知安装版本逐字节相同的角色文件。核对受影响的 handler 索引和信任记录，保留其他 hook 的启用与信任状态。归属不明或有本地改动的条目由用户决定。

* 核对旧安装版本和当前目标。对已转为共享直读或退役的入口，只移除可证明原来指向本仓库对应 `codex/skills/<name>` 的用户级原生软链接。失效链接须能确认其原目标；保留指向其他检出或外部来源的链接、普通目录、文件及归属不明的条目。
* 恢复已转为共享直读的入口，并清理退役来源的配置。根据本机安装证据核实配置归属，只移除与旧清单逐项匹配、仅含 `path` 与 `enabled = false` 的受管条目。核对仓库公共物理路径和用户级共享别名。共享别名若已由其他来源接替，保留其配置。用户自设禁用、含额外字段或归属不明的条目保留并报告。
* 运行 `python3 <dev-kit-root>/codex/skill_entries.py --check` 核对磁盘上的入口、链接和发现配置。结果中的差异用于定位检查；删除前仍须核对归属。

官方 [Build skills](https://learn.chatgpt.com/docs/build-skills) 说明同名技能不会合并，
`agents/openai.yaml` 控制界面与调用策略，`[[skills.config]]` 可禁用特定来源。
用临时 `CODEX_HOME` 安装候选链接及配置并运行 `codex debug prompt-input`，确认
公共技能各自只出现一次，`adapt-agent-routing` 来自本目录。验证候选后再执行正式合并。在新进程的技能列表中核对各名称对应的启用来源。将技能发现与真实调用、角色派发分别报告。
