# airan-dev-kit

`airan-dev-kit` 集中维护个人 Agent 的全局指令、可复用 skills 和配套配置。仓库中的文件是这些配置的事实来源；安装过程通过软链接或按键合并，让后续仓库更新能够安全地同步到本机。

## 模型适配与限制

这些 skills 专门面向每次维护时的 OpenAI 前沿模型持续迭代和优化，并以维护当日最新的官方 prompting 最佳实践为准。它们预期运行在具备相近指令遵循、推理、上下文管理和工具调用能力的模型上。

较弱、较旧、上下文或工具能力受限的模型可能无法稳定遵循完整工作流，触发准确性、边界控制、工具使用和产出质量可能不及预期。本项目不保证不同模型之间的等价表现；切换模型或推理配置后，应先用真实任务验证关键工作流。

## 仓库内容

- `skills/`：安装到用户级目录、可在不同仓库复用的 skills。
- `.agents/skills/install/`：仅用于安装、更新、修复或验证本 dev-kit 的仓库级 skill。
- `codex/`：Codex 全局指令和 hooks。
- `cursor/`：Cursor 用户级规则和 CLI status line。
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

安装完成后，可在任意工作目录中使用 `$skill-name` 显式调用 skill：

| Skill | 用途 |
| --- | --- |
| `$create-worktree` | 根据简要任务创建符合仓库惯例的 Git 分支和 worktree。 |
| `$explore-design` | 在实现前探索或细化设计，并产出经确认的计划或中文设计文档。 |
| `$review-design` | 根据需求和仓库证据独立评审设计的实现准备度。 |
| `$implement-design` | 实现已确认的设计并提供测试和验证证据。 |
| `$review-implementation` | 根据已确认设计独立验收完成的实现。 |
| `$translate-design` | 将稳定的中文设计同步为语义等价的英文版本。 |

例如：

```text
$review-design 评审 docs/proposal.md
```

Codex 也可以在任务与 skill 的 `description` 匹配时隐式选择 skill。`review-design` 和 `review-implementation` 配置为仅允许显式调用，以保证评审行为由用户主动启动。

## 维护约束

修改任何 `AGENTS.md`、skill 或其他 Agent 指令前，必须先获取并阅读维护当日最新的 OpenAI 官方 prompting 最佳实践。所有新增或修改的提示词都必须满足这些最佳实践，并完成仓库 `AGENTS.md` 要求的验证。

相关官方文档：

- [Custom instructions with AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [Build skills](https://learn.chatgpt.com/docs/build-skills)
- [Model guidance](https://developers.openai.com/api/docs/guides/latest-model)
