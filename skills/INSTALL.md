# 全局 Skills 安装与更新

本目录中的每个含 `SKILL.md` 的子目录都是一个全局 skill 的事实来源。

## 安装

1. 读取仓库根目录的 `AGENTS.md`，并读取维护当日与 Codex skills 结构和发现路径相关的官方 OpenAI 文档。
2. 使用 `find skills -mindepth 2 -maxdepth 2 -name SKILL.md` 发现需要安装的 skills，并确保 `~/.agents/skills` 存在。
3. 对每个 skill 比较 `~/.agents/skills/<name>` 与仓库中的目录。将已由仓库完整收录的普通目录替换为指向仓库 skill 目录的绝对软链接；将已有软链接更新为仓库 skill 目录的绝对路径；当目标包含仓库尚未收录的内容时，先展示差异并取得用户决定。
4. 使用 skill 校验器验证每个 `SKILL.md`，并检查所有软链接均可解析到对应仓库目录。
5. 重启 Codex，使用 `/skills` 确认 skills 可被发现。

## 更新

仓库更新后确认软链接仍指向当前仓库路径，并重新运行 skill 校验。软链接会直接使用仓库中的最新内容。
