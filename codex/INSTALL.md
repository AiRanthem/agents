# Codex 配置安装与更新

本目录维护个人 Codex 全局指令、专用 skills 和需要合并到现有配置的 hooks。

## 指令来源与注入范围

* `AGENTS.md` 保存主 Agent 与子 Agent 共用的通用规则。
* `prompts/delegation.md` 是主 Agent 委派策略的唯一正文，Astra 和 Sol 主控共用；模型档位只在这里维护。
* `hooks/session-start.py` 从自身软链接的真实路径读取上述正文，按官方 `SessionStart` JSON 格式输出 `additionalContext`，不按模型分支、不拼入共享 `AGENTS.md`。输入不是 `SessionStart` 时不输出上下文；输入错误或正文缺失、为空时返回非零状态并报告错误。
* `hooks.json` 在 `startup`、`resume`、`clear`、`fork`、`compact` 时注入委派策略；另一个 `compact` handler 保留重新读取全局和仓库指令的提醒。

依赖 `python3` 和 Codex 0.159.2 的事件语义：用户派出的子 Agent 启动走 `SubagentStart`，恢复或压缩不触发 `SessionStart`。完整历史 fork 会继承主 hook 上下文，因此委派策略要求 `fork_turns: "none"`，由主 Agent 提供最小充分任务上下文；本配置不添加 `SubagentStart` 委派 hook。依据 [官方 hooks 文档](https://learn.chatgpt.com/docs/hooks#sessionstart) 和 [对应版本的 hook 分派源码](https://github.com/openai/codex/blob/ff6aec96948b70d94983af2641a6b67c94faeff5/codex-rs/core/src/hook_runtime.rs#L128)，后者还明确支持主会话的 `fork` 来源。升级 Codex 时重新检查此边界及 [历史继承源码](https://github.com/openai/codex/blob/ff6aec96948b70d94983af2641a6b67c94faeff5/codex-rs/core/src/agent/control/spawn.rs#L130)。这是平台分派与委派参数共同保证的范围，不是脚本从模型或会话 ID 推断身份。

## 安装

1. 读取仓库根目录的 `AGENTS.md`，并读取维护当日与 AGENTS.md、skills、hooks 和配置加载相关的官方 OpenAI 文档。
2. 解析本仓库的绝对路径，并确保 `~/.codex` 存在。
3. 检查 `~/.codex/AGENTS.override.md`。当该文件存在且非空时，说明它会优先于 `AGENTS.md`，展示两者差异并让用户选择保留、合并或移除。
4. 比较 `~/.codex/AGENTS.md` 与本目录的 `AGENTS.md`。当目标是普通文件且内容已由仓库完整收录时，将目标替换为指向本目录 `AGENTS.md` 的绝对软链接；当目标是软链接时，将链接更新为本目录的绝对路径；当目标包含仓库尚未收录的内容时，先展示差异并取得用户决定。
5. 确保 `~/.codex/hooks/` 存在，将 `~/.codex/hooks/session-start.py` 安装为本目录 `hooks/session-start.py` 的绝对软链接。保留目录中的无关文件；目标已正确链接时不修改，其他目标先比较并保留未收录内容。正文通过脚本真实路径读取，无需另装提示词链接。
6. 读取 `~/.codex/hooks.json` 和本目录的 `hooks.json`，按事件合并 `hooks` 数组。以 `(SessionStart, matcher, statusMessage)` 识别本仓库的两个 handler：`compact` / `Reloading Agent instructions`，以及 `^(startup|resume|clear|fork|compact)$` / `Loading main-agent delegation`。原位更新已存在的 handler；不存在时追加到相同 matcher 的组，无此组则在事件数组末尾追加。保留其他顶层字段、事件、matcher 和同组的无关 handler，不重排原有条目，以保留其索引对应的信任状态。验证完整候选 JSON 后再替换目标文件。
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
* `~/.codex/hooks/session-start.py` 的软链接目标正确，能够读取仓库中的委派正文。
* `~/.codex/hooks.json` 保留原有无关 hooks 及其顺序，并包含本目录声明的两个 `SessionStart` handler。
* 五个来源均匹配委派 handler；`SubagentStart` 不匹配本配置。脚本通过安装链接调用，输出有效 JSON 和完整策略；非 `SessionStart` 输入无上下文，错误输入或缺失正文报告失败。
* 共享 `AGENTS.md` 不包含委派正文或指向它的加载指令；档位和 `fork_turns` 隔离约束只在 `prompts/delegation.md` 维护。
* `codex --strict-config doctor --summary --no-color` 加载配置且无新增失败；实际信任状态通过 `/hooks` 核实。脚本检查和源码证据不等同于真实模型会话、子代理或自动压缩的端到端验证。
