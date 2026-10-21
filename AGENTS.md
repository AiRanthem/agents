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

* 修改任何 `AGENTS.md`、skill（包括 `SKILL.md` 及其支持文件）、hooks 提示词或其他 Agent 指令前，先阅读并遵循 `references/prompting-best-practices.md`；该文件逐字保存官方 prompting 最佳实践，日常维护无需联网检索。
* 仅当目标前沿模型代际变化、或该文件与实际模型行为冲突时，才重新查阅官方 OpenAI 文档（链接见 `README.md` 的“相关官方文档”），并用最新原文整体替换 `references/prompting-best-practices.md` 的正文。
* 所有新增或修改的提示词必须满足 `references/prompting-best-practices.md`，并以相关官方 OpenAI 文档为准确定结构、措辞和行为边界；完成维护前审计并验证这一点。
* 用目标结果、成功标准、适用范围、证据要求和停止条件描述期望行为。仅在执行路径本身属于契约时规定具体步骤。
* 修改行为时，用新的期望行为直接替换原有文字，并删除旧行为描述、历史说明和迁移叙事。
* 审计全局指令、仓库指令和 skills 组成的完整指令链，保持优先级清晰、语义一致和职责单一。
* 为安全、权限、数据保护和不可逆操作保留明确边界。

# 变更纪律

* 选择满足需求且清晰、可维护的变更，复用官方格式和仓库现有模式。在满足需求和质量约束的前提下，最小化最终 PR：以任务既定集成基线为参照，评估包含累积修改的完整终态差异；不以每次编辑或修补的代码最少为目标。可以替换中间方案、移除本任务已被取代的改动，收敛到更小且完整的交付；保留正确性、可读性、职责归属或可维护性所需的改动，并保留用户无关修改。
* 安装或更新时保留目标机器上的无关配置。
* 共享 skill 在用户级以 `~/.agents/skills/<name>` 的独立软链接生效，目标为本仓库 `skills/<name>`。增删 `skills/` 中的 skill 时，必须同步处理这些现存软链接：新增则补链，删除则只移除目标位于本仓库的对应链接，使链接集合与仓库目录一致。安装与清理边界以 `skills/INSTALL.md` 为准。
* 验证变更涉及的 Markdown、YAML、JSON、软链接和当前宿主配置加载行为。
* 完成维护后报告参考的官方文档、变更路径、实际验证结果和仍需人工完成的步骤。

# 公共内容中立性

* 平台或宿主专属的指令、工具和参数、配置与环境变量、会话身份、模型配置、上下文与缓存机制、安装验证说明、界面元数据及专属测试，只能放在对应的顶层目录中。
* 根目录文档、共享 skills、公共脚本和公共设计只定义通用业务、质量、授权与数据协议，不得包含具体宿主名称、专属路径或文档链接，也不得引用、导入或调用宿主实现。宿主通过自己的入口加载公共内容，并提供公共协议要求的输入。
* 通用行为与宿主实现混在一起时，在保留行为、独立性、权限及数据保护要求的前提下拆分归属；不得通过删除验证、改变调用语义或丢失已有配置来满足目录边界。
* 维护完成前同时审计名称、链接、工具字段和实际行为归属，验证公共层不依赖具体宿主。不得用别名、字符串拼接或间接链接掩盖仍然存在的宿主依赖。
