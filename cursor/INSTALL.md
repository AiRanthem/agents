# Cursor 配置安装与更新

本目录维护个人 Cursor 用户级规则文件和 CLI status line。

## 安装

1. 读取仓库根目录的 `AGENTS.md`，并读取维护当日与 Cursor Rules、CLI status line 和 `cli-config.json` 相关的官方文档。
2. 解析本仓库的绝对路径，并确保 `~/.cursor` 与 `~/.cursor/rules` 存在。
3. 使用 `find cursor/rules -maxdepth 1 -name '*.mdc'` 发现本目录收录的规则。对每个文件比较 `~/.cursor/rules/<name>` 与仓库中的对应文件。将已由仓库完整收录的普通文件替换为指向仓库文件的绝对软链接；将已有软链接更新为仓库文件的绝对路径；当目标包含仓库尚未收录的内容时，先展示差异并取得用户决定。保留 `~/.cursor/rules` 中仓库未收录的其他文件。
4. 删除 `~/.cursor/rules` 中与本目录已收录规则内容相同、但文件名不在本目录列表中的 `.mdc`，避免同一规则被加载两次。
5. 比较 `~/.cursor/statusline.sh` 与本目录的 `statusline.sh`。当目标是普通文件且内容已由仓库完整收录时，将目标替换为指向本目录 `statusline.sh` 的绝对软链接；当目标是软链接时，将链接更新为本目录的绝对路径；当目标包含仓库尚未收录的内容时，先展示差异并取得用户决定。
6. 读取 `~/.cursor/cli-config.json` 与本目录的 `cli-statusline.json`。以 `statusLine.command` 为 `~/.cursor/statusline.sh` 识别本仓库条目：不存在时写入 `statusLine`，存在时更新为仓库版本。保留目标文件中的其他键。写入前用 JSON 解析器验证完整结果。
7. 确认本目录 `statusline.sh` 可执行，并用官方 mock payload 运行一次，确认标准输出非空。

## 更新

仓库更新后重新执行安装流程。规则和 `statusline.sh` 的软链接会直接使用仓库版本；`cli-config.json` 的 `statusLine` 需要重新合并。

## 验证

确认以下结果：

* `~/.cursor/rules` 中每个本目录收录的 `.mdc` 都是指向本目录对应文件的绝对软链接。
* `~/.cursor/rules` 中没有与本目录已收录规则内容相同、但文件名不同的 `.mdc`。
* `~/.cursor/statusline.sh` 的软链接目标是本目录的 `statusline.sh`。
* `~/.cursor/cli-config.json` 可被 JSON 解析，且 `statusLine` 等于本目录 `cli-statusline.json`。
* `echo '{"model":{"display_name":"Opus"},"context_window":{"used_percentage":25}}' | ~/.cursor/statusline.sh` 标准输出非空。
