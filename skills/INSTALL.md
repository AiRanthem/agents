# 全局 Skills 安装与更新

本目录是共享全局 skills 的事实来源，并以一个集合软链接安装。

## 安装

1. 读取仓库根目录的 `AGENTS.md`，并读取维护当日与 Codex skills 结构和发现路径相关的官方 OpenAI 文档。
2. 使用 `find skills -mindepth 2 -maxdepth 2 -name SKILL.md` 发现并验证仓库中的每个 skill，确保 `~/.agents/skills` 存在。
3. 将 `~/.agents/skills/dev-kits` 创建或更新为指向仓库 `skills` 目录绝对路径的软链接。目标若是普通文件或目录，先展示它与仓库的差异并取得用户决定。
4. 清理本仓库旧安装方式留下的逐 skill 软链接，但只处理目标明确位于当前仓库 `skills` 目录下的链接。保留其他文件、目录和软链接。
5. 检查集合链接可解析，并确认其下每个 `SKILL.md` 都能被当前 Agent 发现。重启当前 Agent 后使用其技能列表确认结果。

`known-limit:` 集合链接已在 Codex 0.153.4 验证。其他 Agent 必须先确认会递归扫描集合软链接；不支持时应在对应 Agent 的安装目录中定义兼容方式。

## 更新

仓库更新后确认 `~/.agents/skills/dev-kits` 仍指向当前仓库的 `skills` 目录，并重新发现和验证全部 skills。新增或删除仓库子目录不需要增删用户级软链接。
