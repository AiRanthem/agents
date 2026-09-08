# Codex 配置安装与更新

本目录维护个人 Codex 全局指令和需要合并到现有配置的 hooks。

## 安装

1. 读取仓库根目录的 `AGENTS.md`，并读取维护当日与 AGENTS.md、hooks 和配置加载相关的官方 OpenAI 文档。
2. 解析本仓库的绝对路径，并确保 `~/.codex` 存在。
3. 检查 `~/.codex/AGENTS.override.md`。当该文件存在且非空时，说明它会优先于 `AGENTS.md`，展示两者差异并让用户选择保留、合并或移除。
4. 比较 `~/.codex/AGENTS.md` 与本目录的 `AGENTS.md`。当目标是普通文件且内容已由仓库完整收录时，将目标替换为指向本目录 `AGENTS.md` 的绝对软链接；当目标是软链接时，将链接更新为本目录的绝对路径；当目标包含仓库尚未收录的内容时，先展示差异并取得用户决定。
5. 读取 `~/.codex/hooks.json` 和本目录的 `hooks.json`，按事件合并 `hooks` 数组。保留目标文件中的其他事件和其他 matcher；以 `matcher: compact` 和 `statusMessage: Reloading Agent instructions` 识别本仓库条目，不存在时追加，存在时更新为仓库版本。
6. 使用 JSON 解析器验证合并后的 `~/.codex/hooks.json`，再运行 `codex --strict-config doctor --summary --no-color`。
7. 在 Codex 中打开 `/hooks`，审核并信任新增或发生变化的 hook 定义。

## 更新

仓库更新后重新执行安装流程。`AGENTS.md` 软链接会直接使用仓库版本；hooks 需要重新合并并在内容变化后重新审核信任。

## 验证

确认以下结果：

* `~/.codex/AGENTS.md` 的软链接目标是本目录的 `AGENTS.md`。
* `~/.codex/AGENTS.override.md` 的处理结果符合用户选择。
* `~/.codex/hooks.json` 保留原有 hooks，并包含本目录声明的 `SessionStart` / `compact` 条目。
* `codex --strict-config doctor --summary --no-color` 通过。
