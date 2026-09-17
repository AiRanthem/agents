# Codex 配置安装与更新

本目录维护个人 Codex 全局指令、专用 skills 和需要合并到现有配置的 hooks。

## 安装

1. 读取仓库根目录的 `AGENTS.md`，并读取维护当日与 AGENTS.md、skills、hooks 和配置加载相关的官方 OpenAI 文档。
2. 解析本仓库的绝对路径，并确保 `~/.codex` 存在。
3. 检查 `~/.codex/AGENTS.override.md`。当该文件存在且非空时，说明它会优先于 `AGENTS.md`，展示两者差异并让用户选择保留、合并或移除。
4. 比较 `~/.codex/AGENTS.md` 与本目录的 `AGENTS.md`。当目标是普通文件且内容已由仓库完整收录时，将目标替换为指向本目录 `AGENTS.md` 的绝对软链接；当目标是软链接时，将链接更新为本目录的绝对路径；当目标包含仓库尚未收录的内容时，先展示差异并取得用户决定。
5. 读取 `~/.codex/hooks.json` 和本目录的 `hooks.json`，按事件合并 `hooks` 数组。保留目标文件中的其他事件和其他 matcher；以 `matcher: compact` 和 `statusMessage: Reloading Agent instructions` 识别本仓库条目，不存在时追加，存在时更新为仓库版本。
6. 将本目录 `skills/` 中的各个 skill 以独立绝对软链接安装到 `~/.codex/skills/<name>`，保留 `.system` 和其他无关 skills。目标已正确链接时不做修改；目标是其他链接或普通文件、目录时，先检查差异，保留未收录内容并取得用户决定后再替换。
7. 使用 JSON 解析器验证合并后的 `~/.codex/hooks.json`，验证各个专用 skill 的 frontmatter，再运行 `codex --strict-config doctor --summary --no-color`。
8. 在 Codex 中打开 `/hooks`，审核并信任新增或发生变化的 hook 定义。

## 更新

仓库更新后重新执行安装流程。`AGENTS.md` 和专用 skill 软链接会直接使用仓库版本；新增 skill 需要补链。删除 skill 时，仅清理目标位于本目录 `skills/` 内的对应失效链接。hooks 需要重新合并并在内容变化后重新审核信任。

## 验证

2026-09-17：移除与全局委派规则重复的 `astra-lead` 及其用户级软链接；`SessionStart` / `compact` hook 恢复为只重载全局和仓库 `AGENTS.md`。

2026-09-15：调整 subagent 汇报规则，以派发参数为准，不检查运行时设置；现有 `~/.codex/AGENTS.md` 软链接直接读取仓库更新，无需调整机器配置。

确认以下结果：

* `~/.codex/AGENTS.md` 的软链接目标是本目录的 `AGENTS.md`。
* `~/.codex/AGENTS.override.md` 的处理结果符合用户选择。
* `~/.codex/skills` 中不存在指向本目录已删除 skill 的失效链接。
* `~/.codex/hooks.json` 保留原有 hooks，并包含本目录声明的 `SessionStart` / `compact` 条目。
* `codex --strict-config doctor --summary --no-color` 通过。
