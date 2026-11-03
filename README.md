# airan-dev-kit

`airan-dev-kit` 集中维护个人 Agent 的全局指令、可复用 skills 和配套配置。仓库中的文件是这些配置的事实来源；安装过程通过软链接或按键合并，让后续仓库更新能够安全地同步到本机。

## 模型适配与限制

这些 skills 专门面向每次维护时的最前沿模型持续迭代和优化，并以仓库原样保存的 prompting 最佳实践（`references/prompting-best-practices.md`）为准（随前沿模型代际刷新）。它们预期运行在具备相近指令遵循、推理、上下文管理和工具调用能力的模型上。

较弱、较旧、上下文或工具能力受限的模型可能无法稳定遵循完整工作流，触发准确性、边界控制、工具使用和产出质量可能不及预期。本项目不保证不同模型之间的等价表现；切换模型或推理配置后，应先用真实任务验证关键工作流。

## 仓库内容

- `skills/`：安装到用户级目录、可在不同仓库复用的 skills。
- `.agents/skills/install/`：仅用于安装、更新、修复或验证本 dev-kit 的仓库级 skill。
- `.agents/skills/absorb-skill/`：评估第三方 skill 的独有价值，选择不吸收、合并或重写，并验证整合结果的仓库级 skill。
- 各宿主同名顶层目录：该宿主的配置、入口、安装说明与验证。公共层不依赖这些目录。
- `AGENTS.md`：维护本仓库时必须遵守的规则。

## 安装与更新

克隆仓库后，在仓库根目录启动支持仓库级 `.agents/skills` 的 Agent，并显式调用：

```text
$install 安装或更新这个 dev-kit
```

`$install` 会执行以下范围内的工作：

1. 按照 [`skills/INSTALL.md`](skills/INSTALL.md) 将所有共享 skills 安装为 `~/.agents/skills/<name>` 的独立绝对软链接。
2. 执行调用方已提供且获授权的安装合同；公共安装入口仅维护共享 skills。
3. 保留目标机器上的无关配置；目标存在仓库未收录的内容时，先展示差异并等待用户决定。
4. 完成对应安装文档要求的验证，并报告仍需重启、信任或人工确认的步骤。

更新仓库后再次调用 `$install`，同步共享 skill 的新增、删除和用户级软链接。

如果当前 Agent 没有发现 `$install`，让它完整读取 [`.agents/skills/install/SKILL.md`](.agents/skills/install/SKILL.md)，并以共享安装文档为安装契约。

## 使用 skills

安装完成后，可用 `$skill-name` 显式调用 skill。项目管理技能直接读取和维护项目文件；新项目使用 `.project/project.yaml`，既有项目按实际文件布局处理，结构更新使用 `$upgrade-project`。创建、更新和删除均可显式指定项目路径：

| Skill | 用途 |
| --- | --- |
| `$create-project` | 创建独立 Git 分支承载的项目工作区，准备元数据、必要背景和需求骨架，选择可选 Aone 后端。 |
| `$upgrade-project` | 直接更新项目结构和管理指令，保留 ID、依赖与当前有效业务约束；Git 历史追溯旧版本，重复执行无变化。 |
| `$delete-project` | 核对并删除选定的本机项目工作区，保留远程分支和 Aone 历史。 |
| `$manage-workitems` | 在项目中创建、查询、更新、归档抽象工作项；通过 Git 和已启用后端持久化。 |
| `$split-workitem` | 将完整设计已通过独立审查的大工作项拆为承接设计的子项，按审定 DAG 组织交付；仅实际阻塞缺口触发子项设计补充。 |
| `$advance-project` | 在已批准初版合同与前置人工验收交付满足后，在单机上串行推进指定范围的阶段，直到等待人工验收。 |
| `$develop-workitem` | 准备工作树、探索设计、衔接独立审查，按已确认设计实现项目工作项。 |
| `$complete-workitem` | 核实项目工作项的实际交付，解锁依赖并单独记录工作树清理结果。 |
| `$create-worktree` | 根据简要任务创建符合仓库惯例的 Git 分支和 worktree，同步创建远程分支并设置追踪。 |
| `$cleanup-worktree` | 核验非忽略文件已提交并推送、工作树干净且可从远程恢复，按授权清理本地 worktree 和分支，保留远程恢复引用。 |
| `$rebase-worktree` | 将当前 Git worktree rebase 到指定分支；有冲突风险时启用恢复与独立验证流程。 |
| `$explore-design` | 探索或细化 Why/What；只读规划衔接实施计划，普通执行 将设计文档标记为 `review-pending`。 |
| `$review-design` | 根据需求和仓库证据独立评审设计；通过后将获批文档标记为 `implementable`。 |
| `$implement-design` | 将已确认设计落实实现，按实际规划/执行 与项目职责加载指令，保留验证和独立审查边界。 |
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

已授权的项目阶段由主控显式委派相应技能，不需要用户逐阶段重复调用。

项目从自己的根目录开展工作。Agent 直接维护项目配置、工作项文档和状态；每次完成授权修改后，提交相关文件并普通推送到配置的项目分支。保留无关修改，推送失败时保留本地文件和提交并处理实际错误。项目元数据发布与源码提交分别遵循各自授权。详见[写入规范](skills/manage-workitems/references/commands.md)。

项目可以独立存在，也可以关联业务主工作区。记录真实路径、仓库、分支和原始指令位置，保留主工作区的文件、环境与权限边界。源码工作树可放在项目的 `worktrees/` 或约定的主工作区目录，由各代码仓库管理。详见[主工作区关联](skills/manage-workitems/references/main-workspace.md)。

新工作项使用“层级编号 + 英文短语”的 ID，例如 `123-quota-lock（统一配额锁）`。每层使用 `1`–`9`、`A`–`Z`；Agent 根据现有项目分配未占用编号。编号表达拆分归属，依赖关系表达交付顺序。稳定 ID、标题、依赖和源码位置直接记入项目文件。详见[记录约定](skills/manage-workitems/references/schema.md)。

创建阶段建立项目背景、元数据和用户提供的需求骨架；未知范围、验收和交付细节保持待确认。设计、拆解、独立审查和实现依用户请求开展。需要拆解时，保留完整父设计及其跨项约定，子项承接相关设计和验收场景，避免仅为流程重复设计。

`$advance-project` 按用户指定范围推进设计审查、实施、独立代码审查与修正。主控读取真实文档与当前代码，判断依赖和剩余工作，向执行者分配具体职责，并直接登记阶段结果。执行者负责被分配的源码、设计或评审工作；主控负责项目记录和整合。真实作者、独立评审者、用户验收与交付事实分别记录，不能用 AI 通过代替用户验收或实际交付。详见[主控入口](skills/advance-project/SKILL.md)。

项目正文记录当前有效内容：`requirement.md` 记录目标、范围、验收和交付；`spec.md` 记录设计；`decision.md` 记录决定；`context.md` 和 `logs.md` 记录事实、验证和交接。Agent 同步维护必要元数据和当前证据，Git 历史保留旧版本。用户验收阶段保留其最终代码与设计，按真实结论登记验收；未执行的验证如实说明。

启用 Aone 等后端时，通过可用工具同步真实项目内容并记录结果。Git 推送成功不代表外部同步完成；外部创建结果未知时先核实实际状态再重试。详见[持久化](skills/manage-workitems/references/persistence.md)。

交付后发现缺陷，创建独立关联修复项并保留原交付事实。调整执行方式或替换旧成果时，记录当前源码位置、保留方式和后续责任，保护未发布内容。清理和删除只处理授权目标，按实际 Git 和文件状态确认可恢复性；远程引用和外部历史不随本地项目自动删除。见[资源维护](skills/manage-workitems/references/resource-lifecycle.md)。

共享项目规范更新后，用 `$upgrade-project` 直接刷新选定项目的指令和结构，保留 ID、依赖、源码位置、有效业务约束和真实证据。无需项目控制器、票据或豁免记录；独立工具不作为写入前置条件。

在本仓库中使用 `$absorb-skill <第三方 skill 路径或来源>` 评估和整合技能。能力价值低或已有覆盖时不新增技能；代码质量由通用代码质量要求和现有评审覆盖。审计本地安装快照不代表已核查上游最新版本。

## 维护约束

修改任何 `AGENTS.md`、skill 或其他 Agent 指令前，遵循仓库 `AGENTS.md` 的 `# 提示词维护`：官方 prompting 最佳实践已逐字保存到 `references/prompting-best-practices.md`，日常维护无需联网检索；仅当目标前沿模型代际变化或该文件与实际行为冲突时，才重新查阅下方官方文档并用最新原文整体替换该文件。所有新增或修改的提示词都必须满足这些实践，并完成仓库 `AGENTS.md` 要求的验证。

相关官方文档（代际刷新时以此为准）：

- [Prompt engineering](https://developers.openai.com/api/docs/guides/prompt-engineering)
- [Model guidance（最新模型 prompting 最佳实践）](https://developers.openai.com/api/docs/guides/latest-model)
