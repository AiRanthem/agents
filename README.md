# airan-dev-kit

`airan-dev-kit` 集中维护个人 Agent 的全局指令、可复用 skills 和配套配置。仓库中的文件是这些配置的事实来源；安装过程通过软链接或按键合并，让后续仓库更新能够安全地同步到本机。

## 模型适配与限制

这些 skills 专门面向每次维护时的最前沿模型持续迭代和优化，并以仓库原样保存的 prompting 最佳实践（`references/prompting-best-practices.md`）为准（随前沿模型代际刷新）。它们预期运行在具备相近指令遵循、推理、上下文管理和工具调用能力的模型上。

较弱、较旧、上下文或工具能力受限的模型可能无法稳定遵循完整工作流，触发准确性、边界控制、工具使用和产出质量可能不及预期。本项目不保证不同模型之间的等价表现；切换模型或推理配置后，应先用真实任务验证关键工作流。

## 仓库内容

- `skills/`：安装到用户级目录、可在不同仓库复用的 skills。
- `.agents/skills/install/`：仅用于安装、更新、修复或验证本 dev-kit 的仓库级 skill。
- `.agents/skills/absorb-skill/`：评估第三方 skill 的独有价值，选择不吸收、合并或重写，并验证整合结果的仓库级 skill。
- `codex/`：Codex 全局指令和 hooks。
- `cursor/`：Cursor 用户级规则、`~/.cursor/skills` 入口、CLI status line 和 CLI 偏好。
- `AGENTS.md`：维护本仓库时必须遵守的规则。

## 安装与更新

克隆仓库后，在仓库根目录启动支持仓库级 `.agents/skills` 的 Agent，并显式调用：

```text
$install 安装或更新这个 dev-kit
```

`$install` 会执行以下范围内的工作：

1. 按照 [`skills/INSTALL.md`](skills/INSTALL.md) 将所有共享 skills 安装为 `~/.agents/skills/<name>` 的独立绝对软链接。
2. 识别当前 Agent，只选择对应的顶层配置进行安装。例如，Codex 使用 [`codex/INSTALL.md`](codex/INSTALL.md)，Cursor 使用 [`cursor/INSTALL.md`](cursor/INSTALL.md)。
3. 保留目标机器上的无关配置；目标存在仓库未收录的内容时，先展示差异并等待用户决定。
4. 完成对应安装文档要求的验证，并报告仍需重启、信任或人工确认的步骤。

更新仓库后再次调用 `$install`。共享 skill 的新增和删除会同步到用户级软链接；需要合并的 Agent 配置也会按对应 `INSTALL.md` 重新处理。

如果当前 Agent 没有发现 `$install`，让它完整读取 [`.agents/skills/install/SKILL.md`](.agents/skills/install/SKILL.md)，并以该文件选出的 `INSTALL.md` 为安装契约。

## 使用 skills

安装完成后，可用 `$skill-name` 显式调用 skill。项目管理技能除创建、删除项目外，只在有 `.project/project.json` 的有效项目工作区生效：

| Skill | 用途 |
| --- | --- |
| `$create-project` | 创建独立 Git 分支承载的项目工作区，选择可选 Aone 后端，生成上下文和恢复入口。 |
| `$delete-project` | 核对并删除选定的本机项目工作区，保留远程分支和 Aone 历史。 |
| `$manage-workitems` | 在项目中创建、查询、更新、归档抽象工作项；通过 Git 和已启用后端持久化。 |
| `$split-workitem` | 将项目大需求拆为可独立交付的工作项，用无环依赖图表达交付顺序。 |
| `$develop-workitem` | 准备工作树、探索设计、衔接独立审查，并在远程认领后实现项目工作项。 |
| `$complete-workitem` | 核实项目工作项的实际交付，解锁依赖并单独记录工作树清理结果。 |
| `$create-worktree` | 根据简要任务创建符合仓库惯例的 Git 分支和 worktree，同步创建远程分支并设置追踪。 |
| `$cleanup-worktree` | 核验至少一个相关 PR/MR 已合并到远程主干，经确认后安全清理对应 worktree、分支及可核实的 rebase 备份分支。 |
| `$rebase-worktree` | 将当前 Git worktree rebase 到指定分支；有冲突风险时启用恢复与独立验证流程。 |
| `$explore-design` | 探索或细化 Why/What；Plan mode 直接衔接实施规划，Agent mode 将设计文档标记为 `review-pending`。 |
| `$review-design` | 根据需求和仓库证据独立评审设计；通过后将获批文档标记为 `implementable`。 |
| `$implement-design` | 将已确认设计落实实现；Agent mode 缺评审状态时先警告并征得用户同意。 |
| `$implement-poc` | 将已确认设计裁剪到明确验收场景，实现并验证可排障的 POC。 |
| `$optimize-tests` | 在充分覆盖行为的前提下，主动清理、合并和精简指定范围内的测试代码，经确认后执行。 |
| `$review-implementation` | 根据已确认设计独立验收完成的实现。 |
| `$explain-design` | 将已确定的设计写成独立、易读且可长期留存的设计介绍，面向不熟悉仓库的技术专家；默认英文，可指定其他语言。 |
| `$systematic-debugging` | 从证据追踪故障原因，按授权修复并验证。 |
| `$receiving-code-review` | 核实审查意见，处理已授权的修复并说明分歧。 |
| `$diff-reading-order` | 为变更生成有依赖依据的阅读导航。 |

例如：

```text
$review-design 评审 docs/proposal.md
```

Codex 也可以在任务与 skill 的 `description` 匹配时隐式选择 skill。`review-design`、`review-implementation`、`systematic-debugging` 和 `receiving-code-review` 配置为仅允许显式调用，后两者保留原安装的调用策略。

项目使用时始终从项目根目录启动 agent。项目的 `worktrees/` 通过空占位文件保留，源码内容被忽略，Git 状态由各代码仓库自行管理。也可关联 OKAWorkspace 这类业务主工作区，将源码工作树放在主工作区 `worktrees/<项目标识>/` 下；项目保存必要约束、业务上下文和技能的入口，本机绝对路径单独绑定。创建时可选择主工作区的远程仓库，用独立空分支存储项目，主工作区原检出保持原分支。详见 [主工作区关联](skills/manage-workitems/references/main-workspace.md)。

先用 `$create-project` 选择存储远程与专用分支，再用 `$manage-workitems` 记录需求。大需求可提前拆解；每个开发项获得自己的设计审查后再实现。前置未交付时允许只读设计，交付后由用户在新上下文显式启动 `$review-design`。实现阶段会通过新 subagent 调用 `$review-implementation`，代码留给用户最终检查、提交和推送。

项目文档在任务收尾时按批次同步；只有最终 Git 推送与所有启用后端都核实成功才算持久化完成。跨机器认领与发布使用 Python 3/Git helper，查询使用可重建的本地索引，源码证据按需加载和验证。Aone 首版采用 agent 驱动的 `a1` CLI 与持久化回执，没有无人值守事务引擎。克隆项目可恢复文档和已发布代码分支，未提交或未推送代码仍在原机器。协议入口见 [project-context.md](skills/manage-workitems/references/project-context.md)。

在本仓库中使用 `$absorb-skill <第三方 skill 路径或来源>` 评估和整合技能。能力价值低或已有覆盖时不新增技能；代码质量由通用代码质量要求和现有评审覆盖。审计本地安装快照不代表已核查上游最新版本。

## 维护约束

修改任何 `AGENTS.md`、skill 或其他 Agent 指令前，遵循仓库 `AGENTS.md` 的 `# 提示词维护`：官方 prompting 最佳实践已逐字保存到 `references/prompting-best-practices.md`，日常维护无需联网检索；仅当目标前沿模型代际变化或该文件与实际行为冲突时，才重新查阅下方官方文档并用最新原文整体替换该文件。所有新增或修改的提示词都必须满足这些实践，并完成仓库 `AGENTS.md` 要求的验证。

相关官方文档（代际刷新时以此为准）：

- [Custom instructions with AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [Build skills](https://learn.chatgpt.com/docs/build-skills)
- [Prompt engineering](https://developers.openai.com/api/docs/guides/prompt-engineering)
- [Model guidance（最新模型 prompting 最佳实践）](https://developers.openai.com/api/docs/guides/latest-model)
