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

## 第三方技能接管

先让仓库内替代技能可审阅并通过验证，再检查原目录、调用策略与来源元数据。第三方普通目录不属于第 4 步的仓库软链接清理范围；取得迁移授权后，将指定原目录完整备份到技能发现路径之外，再验证旧版不再被发现。低价值技能可以不吸收；停用其现存安装仍须在授权范围内。

2026-09-10：已安装 `systematic-debugging`、`receiving-code-review`、`diff-reading-order` 的独立用户级软链接，分别指向本仓库同名目录。前两者保留原安装的 `allow_implicit_invocation: false`。本地 `absorb-skill` 位于 `.agents/skills/`，不创建用户级链接。经用户授权，四个旧目录（含不吸收的 `ponytail-review`）已完整移至 `~/.agents/skill-backups/20260910-150354-devkit-absorption/`，保留原相对目录结构及文件 SHA-256 清单 `manifest.json`，移动前后文件哈希一致。Codex 发现检查中旧条目已消失，`diff-reading-order` 仅保留新版；两个显式技能的实际调用仍未由该发现检查验证。

2026-09-10：新增 `rebase-worktree` 共享 skill，并安装独立用户级软链接 `~/.agents/skills/rebase-worktree`，指向本仓库 `skills/rebase-worktree`。

2026-09-10：新增 `optimize-tests` 共享 skill，并安装独立用户级软链接 `~/.agents/skills/optimize-tests`，指向本仓库 `skills/optimize-tests`。

2026-09-11：更新 `optimize-tests` 的行为目标及入口提示词；验证现有用户级软链接仍指向本仓库且可读取更新后的正文，无需调整链接或机器配置。格式与链接检查不等同于新会话中的实际调用验证。

## 验证

确认以下结果：

* `~/.agents/skills/<name>` 对仓库每个 skill 都是指向 `skills/<name>` 的绝对软链接，且 `SKILL.md` 可读取。
* `~/.agents/skills` 中没有解析目标位于本仓库 `skills/` 内、但名称不属于当前 skill 集合的条目。
* `~/.agents/skills` 中与本仓库无关的条目未被改动。
