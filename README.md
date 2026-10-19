# airan-dev-kit

`airan-dev-kit` 集中维护个人 Agent 的全局指令、可复用 skills 和配套配置。仓库中的文件是这些配置的事实来源；安装过程通过软链接或按键合并，让后续仓库更新能够安全地同步到本机。

## 模型适配与限制

这些 skills 专门面向每次维护时的最前沿模型持续迭代和优化，并以仓库原样保存的 prompting 最佳实践（`references/prompting-best-practices.md`）为准（随前沿模型代际刷新）。它们预期运行在具备相近指令遵循、推理、上下文管理和工具调用能力的模型上。

较弱、较旧、上下文或工具能力受限的模型可能无法稳定遵循完整工作流，触发准确性、边界控制、工具使用和产出质量可能不及预期。本项目不保证不同模型之间的等价表现；切换模型或推理配置后，应先用真实任务验证关键工作流。

## 仓库内容

- `skills/`：安装到用户级目录、可在不同仓库复用的 skills。
- `.agents/skills/install/`：仅用于安装、更新、修复或验证本 dev-kit 的仓库级 skill。
- `.agents/skills/absorb-skill/`：评估第三方 skill 的独有价值，选择不吸收、合并或重写，并验证整合结果的仓库级 skill。
- `codex/`：Codex 全局指令、固定自主阶段角色，以及按模型组装的主代理与 Astra 子代理委派 hooks。
- `cursor/`：Cursor 用户级规则、`~/.cursor/skills` 入口、CLI status line 和 CLI 偏好。
- `qoder/`：Qoder 固定自主阶段角色、会话身份 hook 和自主推进适配。
- `AGENTS.md`：维护本仓库时必须遵守的规则。

## 安装与更新

克隆仓库后，在仓库根目录启动支持仓库级 `.agents/skills` 的 Agent，并显式调用：

```text
$install 安装或更新这个 dev-kit
```

`$install` 会执行以下范围内的工作：

1. 按照 [`skills/INSTALL.md`](skills/INSTALL.md) 将所有共享 skills 安装为 `~/.agents/skills/<name>` 的独立绝对软链接。
2. 识别当前 Agent，只选择对应的顶层配置进行安装。例如，Codex 使用 [`codex/INSTALL.md`](codex/INSTALL.md)，Cursor 使用 [`cursor/INSTALL.md`](cursor/INSTALL.md)，Qoder 使用 [`qoder/INSTALL.md`](qoder/INSTALL.md)。
3. 保留目标机器上的无关配置；目标存在仓库未收录的内容时，先展示差异并等待用户决定。
4. 完成对应安装文档要求的验证，并报告仍需重启、信任或人工确认的步骤。

更新仓库后再次调用 `$install`。共享 skill 的新增和删除会同步到用户级软链接；需要合并的 Agent 配置也会按对应 `INSTALL.md` 重新处理。

如果当前 Agent 没有发现 `$install`，让它完整读取 [`.agents/skills/install/SKILL.md`](.agents/skills/install/SKILL.md)，并以该文件选出的 `INSTALL.md` 为安装契约。

## 使用 skills

安装完成后，可用 `$skill-name` 显式调用 skill。项目管理技能在 schema v2（`.project/project.yaml`）项目中使用；创建、迁移和删除可显式指定项目路径。v1（`.project/project.json`）只支持诊断读取与显式迁移：

| Skill | 用途 |
| --- | --- |
| `$create-project` | 创建独立 Git 分支承载的项目工作区，准备元数据、必要背景和需求骨架，选择可选 Aone 后端。 |
| `$upgrade-project` | 确定性迁移项目结构并刷新程序生成的管理指令，保留 ID、依赖与当前有效业务约束；Git 历史追溯旧版本，重复执行无变化。 |
| `$delete-project` | 核对并删除选定的本机项目工作区，保留远程分支和 Aone 历史。 |
| `$manage-workitems` | 在项目中创建、查询、更新、归档抽象工作项；通过 Git 和已启用后端持久化。 |
| `$split-workitem` | 将项目大需求拆为可独立交付的工作项，用无环依赖图表达交付顺序。 |
| `$advance-project` | 在已批准初版合同与前置人工验收交付满足后，并发推进指定范围的阶段，直到等待人工验收。 |
| `$develop-workitem` | 准备工作树、探索设计、衔接独立审查，并在远程认领后实现项目工作项。 |
| `$complete-workitem` | 核实项目工作项的实际交付，解锁依赖并单独记录工作树清理结果。 |
| `$create-worktree` | 根据简要任务创建符合仓库惯例的 Git 分支和 worktree，同步创建远程分支并设置追踪。 |
| `$cleanup-worktree` | 核验非忽略文件已提交并推送、工作树干净且可从远程恢复，按授权清理本地 worktree 和分支，保留远程恢复引用。 |
| `$rebase-worktree` | 将当前 Git worktree rebase 到指定分支；有冲突风险时启用恢复与独立验证流程。 |
| `$explore-design` | 探索或细化 Why/What；Plan mode 直接衔接实施规划，Agent mode 将设计文档标记为 `review-pending`。 |
| `$review-design` | 根据需求和仓库证据独立评审设计；通过后将获批文档标记为 `implementable`。 |
| `$implement-design` | 将已确认设计落实实现，按实际 Plan/Agent 与项目职责加载指令，保留验证和独立审查边界。 |
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

Codex 也可以在任务与 skill 的 `description` 匹配时隐式选择 skill。`review-design`、`review-implementation`、`systematic-debugging` 和 `receiving-code-review` 保留仅显式调用策略。已授权的项目阶段由主控显式委派相应技能，不需要用户逐阶段重复调用。

项目使用时始终从项目根目录启动 agent。项目的 `worktrees/` 通过空占位文件保留，源码内容被忽略，Git 状态由各代码仓库自行管理。也可关联 OKAWorkspace 这类业务主工作区，将源码工作树放在主工作区 `worktrees/<项目标识>/` 下；项目保存必要约束、业务上下文和技能的入口，本机绝对路径单独绑定。创建时可选择主工作区的远程仓库，用独立空分支存储项目，主工作区原检出保持原分支。详见 [主工作区关联](skills/manage-workitems/references/main-workspace.md)。

新工作项使用“层级编号 + 英文短语”的 ID，汇报时附中文标题，例如 `123-quota-lock（统一配额锁）`。`123` 表示第 1 个根项下的第 2 个子项下的第 3 个子项；每层用 `1`–`9`、`A`–`Z`，`A` 表示第 10 项。可以用完整 ID、编号、短语或标题定位工作项。编号表达拆分归属，交付顺序仍由依赖图决定；以远端发布成功的编号为准，冲突方刷新后重新分配尚未发布的编号。详见 [编号约定](skills/manage-workitems/references/schema.md#identity-and-hierarchy)。

创建阶段只做到“元数据 + 需求骨架”：程序建立存储远程、专用分支和必要背景；用户同时提供需求时记录目标、范围、验收和交付义务，未知内容保持待确认。创建完成即收尾。普通单项设计与独立设计评审按用户请求执行；自主推进启动授权覆盖指定范围内的阶段调用。实现通常要求当前独立设计评审；用户明确指定某个简单需求可跳过时，用 `development-start --skip-design-review --approval-source <实际用户来源>` 记录当前合同的限定豁免，不伪造评审通过。实现独立评审、owner、依赖与交付证据仍保留，代码提交和推送需要用户授权。

在项目根目录调用 `$advance-project` 可选择全项目、某项及后代，或若干明确工作项。主控直接调度所有就绪 development 项的设计审查、实现、独立代码审查、修复与复核，集中执行项目命令与持久化；每名一级执行者只负责一次阶段，读取原始合同并编辑指定源码工作树、候选稿或报告。aggregate 沿用聚合验收，不进入源码闭环。初版合同须已获用户批准，前置项须已人工验收并完成声明交付；缺少初版设计不会自动补写。设计审查默认执行，只有用户明确指定的范围可以跳过。

自主推进在等待人工验收时保留未提交源码，不自动 commit、push 或创建 PR。AI 审查通过、人工验收与实际交付分别记录；只有人工验收和实际交付完成才解锁下游。合同内局部实现与修复连续执行；需求、公开或存储合同、兼容性、关键约束、安全正确性保证或验收标准改变时，主控合并问题交用户决定，只暂停受影响项。原生 Plan 保持只读，不能委派写入绕过。当前自主推进入口支持 Codex、Cursor 和 Qoder，详见 [主控入口](skills/advance-project/SKILL.md)、[Codex 适配](codex/AUTONOMY.md)、[Cursor 适配](cursor/AUTONOMY.md) 和 [Qoder 适配](qoder/AUTONOMY.md)；配置检查不等于实际宿主委派与模型已获验证。

项目 CLI 需要当前工作区规定的 Python 3 环境、Git 和 PyYAML；用该环境执行 `-m pip install -r skills/manage-workitems/scripts/requirements.txt` 安装声明依赖，不绕过主工作区指定的解释器。

统一入口是 `skills/manage-workitems/scripts/project.py`。Agent 执行固定机械流程：`begin OP [ID] --参数` → 完整读取程序返回的输入与外部原始指令 → 仅编辑返回的绝对 Markdown 路径 → 执行返回的 finish 命令（只有独立设计评审在评审后补程序声明的 result/provenance；实现评审的 result/provenance/reviewer-session/review-file 是 `begin development-finish` 输入）→ 按固定状态处理。YAML、编号、状态、文档路由、DAG、ownership 和 Git/Aone 检查由程序负责。`ready` 读取输入并完成指定编辑，`published`/`no_op` 结束，`partial` 只执行返回的 resume；`blocked` 的 `stale_ticket` 只执行唯一返回的 `next_command`；携带授权或评审材料过期时为 `blocked`、code 是 `stale_evidence` 且不返回后续命令，其余阻塞或缺输入只报告所列事实。见 [命令契约](skills/manage-workitems/references/commands.md)。

工作项正文固定为 `requirement.md`（目标、范围、验收、交付）、`spec.md`（完整当前设计，无机器状态 frontmatter）、`decision.md`（当前有效决定）、`context.md`（当前事实、验证与交接）和 `logs.md`（当前运行摘要与交接）；decision/log 由 Agent 写成完整 Markdown，程序替换文件且不追加机器事件。Git 历史追溯旧版本；records 只保留当前 review、delivery、waiver、cleanup 指针所需的成对 Markdown/YAML 工件，以及待恢复操作材料。设计版本按原始字节生成，首版为 1，变化递增，相同不变。后台同步回执由程序维护。实际 Git 与已启用后端均核实完成后才算持久化；未知外部创建不会盲目重试。Git/Aone 没有原子事务，Aone 没有已验证的字段 CAS。见 [记录契约](skills/manage-workitems/references/schema.md)。

交付后发现缺陷，用 `begin fix ORIGINAL --title TITLE --slug SLUG` 创建独立关联修复项，原项保持 `done` 状态及当前交付证据。未交付的 fix 阻塞原项下游的新实现、交付及 aggregate 完成，活跃会话在下次检查点也受此约束；修复交付后仍需重新核实适用基线与评审。

共享项目技能更新后，在项目根目录执行 `$upgrade-project`，也可显式指定路径。它调用确定性的 `migrate`，仅用户要求预览时使用 `--dry-run`，保留 ID、DAG、owner 和当前有效业务约束；未完成同步或活跃 owner 会明确阻断。迁移只保留当前有效项目内容和仍被当前状态引用的证据；旧正文由 Git 历史追溯。若程序要求整理当前业务指令，复用现有用户维护授权，按当前来源写完整正文；不确定的真实业务变化或权限才报告具体缺口。相同来源哈希不产生修改或空提交。克隆只恢复已发布记录与代码分支，未提交或未推送代码仍在原机器。

在本仓库中使用 `$absorb-skill <第三方 skill 路径或来源>` 评估和整合技能。能力价值低或已有覆盖时不新增技能；代码质量由通用代码质量要求和现有评审覆盖。审计本地安装快照不代表已核查上游最新版本。

## 维护约束

修改任何 `AGENTS.md`、skill 或其他 Agent 指令前，遵循仓库 `AGENTS.md` 的 `# 提示词维护`：官方 prompting 最佳实践已逐字保存到 `references/prompting-best-practices.md`，日常维护无需联网检索；仅当目标前沿模型代际变化或该文件与实际行为冲突时，才重新查阅下方官方文档并用最新原文整体替换该文件。所有新增或修改的提示词都必须满足这些实践，并完成仓库 `AGENTS.md` 要求的验证。

相关官方文档（代际刷新时以此为准）：

- [Custom instructions with AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [Build skills](https://learn.chatgpt.com/docs/build-skills)
- [Prompt engineering](https://developers.openai.com/api/docs/guides/prompt-engineering)
- [Model guidance（最新模型 prompting 最佳实践）](https://developers.openai.com/api/docs/guides/latest-model)
