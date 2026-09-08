# 全局 Skills 安装与更新

本目录是共享全局 skills 的事实来源。每个 skill 以独立软链接安装到 `~/.agents/skills/<name>`。

## 安装

1. 读取仓库根目录的 `AGENTS.md`，并读取维护当日与 Codex skills 结构和发现路径相关的官方 OpenAI 文档。
2. 使用 `find skills -mindepth 2 -maxdepth 2 -name SKILL.md` 发现并验证仓库中的每个 skill，确保 `~/.agents/skills` 存在。skill 名为含 `SKILL.md` 的目录名，且须与 frontmatter `name` 一致。
3. 对每个 skill，将 `~/.agents/skills/<name>` 创建或更新为指向仓库 `skills/<name>` 绝对路径的软链接。目标若是普通文件或目录，先展示它与仓库的差异并取得用户决定。已有软链接更新为仓库目录的绝对路径。
4. 检查 `~/.agents/skills` 中解析目标位于当前仓库 `skills/` 目录内的条目。名称属于当前 skill 集合的保留并校正；名称不属于当前集合的删除。保留其他文件、目录和软链接。
5. 检查每个 skill 链接可解析，且其下 `SKILL.md` 存在。重启当前 Agent 后使用其技能列表确认结果。

## 更新

仓库更新后重新执行安装流程。新增 skill 必须补齐对应软链接；删除 skill 必须移除对应软链接。不得留下指向本仓库、但已无对应 skill 的用户级链接。

## 验证

确认以下结果：

* `~/.agents/skills/<name>` 对仓库每个 skill 都是指向 `skills/<name>` 的绝对软链接，且 `SKILL.md` 可读取。
* `~/.agents/skills` 中没有解析目标位于本仓库 `skills/` 内、但名称不属于当前 skill 集合的条目。
* `~/.agents/skills` 中与本仓库无关的条目未被改动。
