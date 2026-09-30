# Cursor 配置安装与更新

本目录维护个人 Cursor 用户级规则、CLI status line 和 CLI 偏好。共享 skills 在本机的 Cursor 入口安装为 `~/.cursor/skills/<name>` 的绝对软链接，目标为仓库 `skills/<name>`。

## 安装

1. 读取仓库根目录的 `AGENTS.md`，并读取维护当日与 Cursor Rules、Agent Skills、CLI status line 和 `cli-config.json` 相关的官方文档。
2. 解析本仓库的绝对路径，并确保 `~/.cursor`、`~/.cursor/rules` 与 `~/.cursor/skills` 存在。
3. 使用 `find cursor/rules -maxdepth 1 -name '*.mdc'` 发现本目录收录的规则。对每个文件比较 `~/.cursor/rules/<name>` 与仓库中的对应文件。将已由仓库完整收录的普通文件替换为指向仓库文件的绝对软链接；将已有软链接更新为仓库文件的绝对路径；当目标包含仓库尚未收录的内容时，先展示差异并取得用户决定。保留 `~/.cursor/rules` 中仓库未收录的其他文件。
4. 清理 `~/.cursor/rules`：删除解析目标位于本仓库 `cursor/rules/` 内、但文件名不属于本目录当前收录规则的软链接（仓库已移除的规则）；删除与已收录规则内容相同、但文件名不在本目录列表中的其他 `.mdc`，避免同一规则被加载两次。保留其余无关文件和软链接。
5. 使用 `find skills -mindepth 2 -maxdepth 2 -name SKILL.md` 发现仓库共享 skills。skill 名为含 `SKILL.md` 的目录名，且须与 frontmatter `name` 一致。对每个 skill，将 `~/.cursor/skills/<name>` 创建或更新为指向仓库 `skills/<name>` 绝对路径的软链接。目标若是普通文件或目录，先展示它与仓库的差异并取得用户决定。已有软链接更新为仓库目录的绝对路径。
6. 检查 `~/.cursor/skills` 中解析目标位于当前仓库 `skills/` 目录内的条目。名称属于当前 skill 集合的保留并校正；名称不属于当前集合的删除。保留其他文件、目录和软链接。不修改 `~/.cursor/skills-cursor`。
7. 比较 `~/.cursor/statusline.sh` 与本目录的 `statusline.sh`。当目标是普通文件且内容已由仓库完整收录时，将目标替换为指向本目录 `statusline.sh` 的绝对软链接；当目标是软链接时，将链接更新为本目录的绝对路径；当目标包含仓库尚未收录的内容时，先展示差异并取得用户决定。
8. 读取 `~/.cursor/cli-config.json`、本目录的 `cli-config.json` 与 `cli-statusline.json`。将 `cli-config.json` 的每个顶层键写入目标并覆盖同名键。以 `statusLine.command` 为 `~/.cursor/statusline.sh` 识别本仓库的 status line：不存在时写入 `statusLine`，存在时更新为 `cli-statusline.json`。保留目标中仓库未列出的其他键。写入前用 JSON 解析器验证完整结果。
9. 确认本目录 `statusline.sh` 可执行，并用官方 mock payload 运行一次，确认标准输出非空。

## 更新

仓库更新后重新执行安装流程。规则、`statusline.sh` 和 `~/.cursor/skills` 的软链接会直接使用仓库版本；`~/.cursor/cli-config.json` 中由本目录 `cli-config.json` 与 `cli-statusline.json` 提供的键需要重新合并。新增规则或 skill 补齐对应软链接；移除规则则删除 `~/.cursor/rules` 中指向本仓库、但已无对应规则的软链接；移除 skill 则删除 `~/.cursor/skills` 中指向本仓库、但已无对应 skill 的软链接。不得遗留悬空链接。

## 验证

确认以下结果：

* `~/.cursor/rules` 中每个本目录收录的 `.mdc` 都是指向本目录对应文件的绝对软链接。
* `~/.cursor/rules` 中没有解析目标位于本仓库 `cursor/rules/` 内、但文件名不属于当前收录规则的软链接。
* `~/.cursor/rules` 中没有与本目录已收录规则内容相同、但文件名不同的 `.mdc`。
* `~/.cursor/skills/<name>` 对仓库每个共享 skill 都是指向 `skills/<name>` 的绝对软链接，且 `SKILL.md` 可读取。
* `~/.cursor/skills` 中没有解析目标位于本仓库 `skills/` 内、但名称不属于当前 skill 集合的条目。
* `~/.cursor/skills` 中与本仓库无关的条目未被改动，`~/.cursor/skills-cursor` 未被改动。
* `~/.cursor/statusline.sh` 的软链接目标是本目录的 `statusline.sh`。
* `~/.cursor/cli-config.json` 可被 JSON 解析；其中由本目录 `cli-config.json` 列出的每个顶层键与仓库一致，且 `statusLine` 等于本目录 `cli-statusline.json`。
* `echo '{"model":{"display_name":"Opus"},"context_window":{"used_percentage":25}}' | ~/.cursor/statusline.sh` 标准输出非空。

## 云端范围

本安装只在本机建立上述链接和配置。Cursor 托管 Cloud Agent 要使用这些 skills，还需要用户在 Settings → Agents 打开 Sync Skills for Cloud Agents。该同步只复制 `~/.cursor/skills/` 的内容。`~/.cursor/rules`、`cli-config.json` 和 status line 不进入该同步。安装完成时报告该开关仍需人工确认。
