# Qoder 配置安装与更新

本目录维护用户级全局指令、hooks、状态栏和 Qoder 专属技能。按[共享技能安装契约](../skills/INSTALL.md)安装公共技能。Qoder 直接读取 `~/.agents/skills` 中的公共入口，宿主技能通过 `~/.qoder/skills/<name>` 的独立绝对软链接加载。

## 安装与更新

1. 读取仓库 `AGENTS.md`，并核对本次涉及的官方[技能](https://docs.qoder.com/cli/Skills.md)、[设置](https://docs.qoder.com/cli/settings.md)、[记忆](https://docs.qoder.com/cli/memory.md)和 [Hooks](https://docs.qoder.com/cli/hooks.md) 文档。仅请求验证时只读检查。
2. 解析仓库的物理路径，将 `qoder/AGENTS.md` 安装为 `~/.qoder/AGENTS.md` 的绝对软链接，作为跨项目生效的用户级全局指令。普通文件逐字匹配本仓库当前或已知安装版本时可替换成链接；目标包含本地改动或归属不明时先展示差异并取得用户决定。`~/.qoder/rules/` 中的用户自有规则不由本仓库管理，保持原样。
3. 逐个安装 `qoder/skills/<name>/` 到 `~/.qoder/skills/`，使用指向对应源码的绝对软链接，校验每个技能 frontmatter 的名称与目录一致。
4. 将 `statusline.sh` 和 `statusline-fmt-check.sh` 分别链接到 `~/.qoder/` 的同名位置，确认本仓库的两个脚本可执行。仅替换可证实归本仓库管理的目标；普通文件可与已知安装版本逐字比对。外部链接、本地改动或归属不明的目标由用户决定，其他条目可以继续安装。
5. 核实状态栏脚本归属后，将 `settings-statusline.json` 作为 `~/.qoder/settings.json` 的 `statusLine` 值。该键空缺时可添加，匹配已知仓库版本时可更新。遇到用户自定义配置先展示差异并取得决定。保留其他所有键并验证完整 JSON。
6. 读取 `~/.qoder/settings.json` 和本目录 `settings-hooks.json`，按事件合并 `hooks` 数组。以 `(事件, matcher, statusMessage)` 识别仓库 handler：`SessionStart` / `compact` / `Reloading Agent instructions`，它在上下文压缩完成后提醒 Agent 重读指令链。原位更新已存在的 handler；不存在时追加到相同 matcher 的组，无此组则在事件数组末尾追加。保留其他顶层键、事件、matcher 和同组无关 handler，不重排原有条目。验证完整候选 JSON 后再替换目标文件。
7. 仓库更新后补齐新增链接。对已移除的源码，只清理可确认由本仓库安装的旧链接和文件，包括 `~/.qoder/rules/` 中指向本仓库已删除规则文件的软链接，以及 `~/.qoder/agents/` 中与其已知安装版本逐字一致的退役角色文件。保留名称相同但有本地改动或归属不明的条目，以及用户自有的规则文件。检查 `settings.json` 是否还为退役角色配置了 `agents.overrides`；删除个人覆盖需要针对相应条目的用户授权，并保留其余设置。重新开启会话以加载更新的全局指令和技能；hooks 和状态栏软链接直接使用新版本。

## 验证

* `~/.qoder/AGENTS.md` 是指向本目录 `AGENTS.md` 的绝对软链接，正文可通过该路径完整读取。在 Qoder CLI 中用 `/memory` 确认它作为用户级指令被加载。
* 将 `<dev-kit-root>` 替换为安装入口已定位的 dev-kit 源目录，运行 `python3 <dev-kit-root>/qoder/host.py check` 检查技能链接与可读性。再用 Qoder CLI 的 `qodercli skills list` 核实实际发现的名称和来源。
* 回读 `settings.json`，确认无关 hooks 及其顺序未变，且 `SessionStart` 含仓库的 `compact` handler。直接执行该 handler 的 `command`，stdout 应是提醒正文；Qoder 把 `SessionStart` 的纯文本 stdout 注入上下文。真实压缩事件要在新会话中触发手动或自动压缩后核实。
* 回读 `settings.json` 并核对状态栏字段，保留用户选择的配置。已安装的两个受管状态栏脚本应可执行且指向仓库源文件。
* 仅在两个脚本归属均已确认时，将它们放入临时 HOME 的 `.qoder/`，以清理过凭据变量的环境和合成输入做渲染检查。例如以 `env -i HOME="$fixture_home" PATH="$PATH" bash "$script"` 接收 `{"model":{"display_name":"Qwen3.8-Max"},"context_window":{"context_window_size":400000,"used_percentage":25}}`，首段应包含该模型名。在同一隔离环境运行格式自检，输出应包含 `ALL MATCH`。如果用户保留外部脚本，报告渲染未验证。
* 合成 transcript 中最后一条 `runtime-config` 提供会话的 effort；缺少该记录或关闭 reasoning 时不显示 effort。缺少 payload 和使用量记录中的上下文窗口时，回退到 `runtime-config` 的 `contextWindow`。
