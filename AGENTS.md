# 仓库用途

本仓库维护个人 Agent 配置，并作为仓库内配置文件的唯一事实来源。本工作副本对应共享远程 `git@github.com:AiRanthem/agents.git` 的 `devkits/` 命名空间。

# Git 远程与分支

本工作副本的 origin 是共享仓库 `git@github.com:AiRanthem/agents.git`，只使用其中的 `devkits/` 命名空间，不使用该远程的默认分支或其他前缀。

* 目标结果：fetch、pull、push、rebase、worktree 基线和新建分支都把本地分支 `<name>` 映射到远程分支 `devkits/<name>`。`master` 对应 `devkits/master`。本地分支名不含 `devkits/` 前缀。
* 成功标准：`remote.origin.url` 为 `git@github.com:AiRanthem/agents.git`；`remote.origin.fetch` 为 `+refs/heads/devkits/*:refs/remotes/origin/*`；`remote.origin.push` 为 `refs/heads/*:refs/heads/devkits/*`；当前分支的 `branch.<name>.merge` 为 `refs/heads/devkits/<name>`。
* 适用范围：本仓库的本地分支、worktree 和 origin 同步。
* 证据：`git remote -v`、`git config --get-regexp '^remote\.origin\.|^branch\.'`，以及当前分支的 `@{upstream}`。
* 停止条件：不读取、创建或更新 `refs/heads/devkits/*` 以外的远程引用；不 force-push；不修改全局 git config。

# 提示词维护

* 修改任何 `AGENTS.md`、skill（包括 `SKILL.md` 及其支持文件）、hooks 提示词或其他 Agent 指令前，必须先获取并阅读维护当日最新的 OpenAI 官方 prompting 最佳实践；若变更主题另有相关的官方 OpenAI 文档，也必须一并读取。
* 所有新增或修改的提示词必须满足所获取的最新 prompting 最佳实践，并以相关官方 OpenAI 文档为准确定结构、措辞和行为边界；完成维护前审计并验证这一点。
* 用目标结果、成功标准、适用范围、证据要求和停止条件描述期望行为。仅在执行路径本身属于契约时规定具体步骤。
* 修改行为时，用新的期望行为直接替换原有文字，并删除旧行为描述、历史说明和迁移叙事。
* 审计全局指令、仓库指令和 skills 组成的完整指令链，保持优先级清晰、语义一致和职责单一。
* 为安全、权限、数据保护和不可逆操作保留明确边界。

# 变更纪律

* 选择满足需求的最小变更，复用官方格式和仓库现有模式。
* 将安装动作记录在对应目录的 `INSTALL.md` 中，并在安装或更新时保留目标机器上的无关配置。
* 共享 skill 在用户级以 `~/.agents/skills/<name>` 的独立软链接生效，目标为本仓库 `skills/<name>`。增删 `skills/` 中的 skill 时，必须同步处理这些现存软链接：新增则补链，删除则只移除目标位于本仓库的对应链接，使链接集合与仓库目录一致。安装与清理边界以 `skills/INSTALL.md` 为准。
* 验证变更涉及的 Markdown、YAML、JSON、软链接和 Codex 配置加载行为。
* 完成维护后报告参考的官方文档、变更路径、实际验证结果和仍需人工完成的步骤。
