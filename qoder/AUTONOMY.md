# Qoder 自主推进适配

适用于同一 Qoder harness 的各使用形态。业务流程读取共享 `advance-project`
及其 coordinator / stage-executor 引用；本文件只定义 Qoder 宿主边界。
安装检查、角色发现、配置核对与主控身份操作只由主控执行。阶段执行者读取其适用的
上下文、权限与报告规则，不运行宿主配置检查或查看安装副本、执行者设置及账户。
主控从已安装 skill 的物理路径找到本仓库并运行：

```sh
python3 <dev-kit-root>/qoder/host.py check
```

Qoder 专用入口为 `qoder/host.py`（`check`、`role --name`）。`disk_ready` 只证明报告
列明的磁盘模板、技能入口、身份 hook 和配置核对通过，不证明当前会话工具、模型访问、
身份注入或权限可用。主控在进入共享 coordinator 前提供本文件的角色绑定、检查证据、
项目命令入口和权限边界；共享层不负责加载本适配。

四个原生角色固定具体型号：两类审查 Qwen3.8-Max / xhigh，实现和修复 DeepSeek-Flash / max。
原生 `model` 字段使用 `"[显示名](模型 ID)"` 形式；ID 于 2026-10-19 按本机 `/model`
持久化（`qmodel_38max`）、既有角色文件与模型参数面板（`dfmodel`）解析固定，effort
支持范围以[官方模型文档](https://docs.qoder.com/cli/model.md)和当前参数面板为准。
升级型号属于明确配置维护，不在运行时动态换型；不支持指定模型或 effort 时报告
具体能力缺失，不降档。各模板保留现有显式高值 `maxTurns`，仍是有限正整数。

| runtime role | 原生角色 | 明确阶段 skill | 固定 model / effort |
| --- | --- | --- | --- |
| design-review | project-design-reviewer | review-design | Qwen3.8-Max / xhigh |
| design-revision | project-design-reviewer | explore-design | Qwen3.8-Max / xhigh |
| implementation / baseline / rebase | project-implementer | implement-design | DeepSeek-Flash / max |
| code-review | project-implementation-reviewer | review-implementation（single-agent） | Qwen3.8-Max / xhigh |
| fix | project-fixer | receiving-code-review | DeepSeek-Flash / max |

主控通过当前会话真实暴露的 Agent 工具以 `subagent_type` 选择原生角色，并用
`qoder agents list` 或 `/agents` 确认用户级定义未被项目、插件或 `--agents` 同名定义
遮蔽。自然语言提及或 `@name` 本身不是派发成功证据。交互式 Agent 工具没有 model /
effort 参数，角色配置由实际加载的定义及有效 override 决定。角色未发现、被禁用、
遮蔽或固定配置冲突时，报告具体缺口并按安装流程处理，不以普通派发冒充模板生效。

Headless / SDK 可用 `--agents` JSON 等价显式注入。运行 `qoder/host.py role --name <角色>`
取得以角色名为键的注入 JSON：helper 保留模板的 `description`、`effort`、`maxTurns`，
把 Markdown `model` 转为裸 ID（`qmodel_38max` / `dfmodel`），把 `developer_instructions`
映射为 Qoder 的 `prompt`。当前 CLI 的 JSON 注入不解析 Markdown 模型链接。将该 JSON 交给
`--agents`，记录实际派发方式，不伪称用户级原生角色选择。主控不按难度改变一级角色
配置，也不要求后台执行；等待、结果读取和收尾以实际工具回执为准。

## 阶段上下文与审查

一级派发使用干净隔离上下文，不 fork 主控或作者历史。交付完整当前原始合同、
适用指令、源代码位置、基线、允许写入范围、候选/报告路径和证据索引；摘要只是导航。
阶段角色将主控提供的安装路径或 `~/.agents/skills/advance-project` 解析为物理目录；
该目录为 `<dev-kit>/skills/advance-project`，其 `parent.parent` 才是仓库根，宿主文件为
`<dev-kit>/qoder/AUTONOMY.md`。完整读取该宿主文件、skill 与阶段引用，不依赖当前工作
目录猜路径。必读文件实际缺失或不可读时阻塞，不能用其他摘要替代或自行豁免。
选中 skill 已列出且 Skill 工具可用时显式调用；未列出或工具未暴露时，通过文件工具
完整读取已授权安装路径中的 `SKILL.md` 及适用引用并执行该阶段。仅发现列表缺失不
构成阻塞；真正禁用、拒绝或不可读仍生效，文件读取不能绕过它们。已授权推进阶段
覆盖该范围内的显式调用要求。`baseline` / `rebase` 还须完整读取
`advance-project/references/predevelopment.md`，只执行绑定的隔离 Git 转换。

当前观察到的 Qoder 子代理工具集不含 Agent，也没有 follow-up 输入工具；这些阶段
直接在现有工具能力内完成。官方仅说明 Agent 可用时支持后代派发，不能据此推断本次
子代理具备该能力，也不能把本次观察宣称为所有 Qoder 版本或模式的永久禁令。没有
follow-up 工具时，复审用新的干净派发交付当前原始输入与可复用证据，不伪造续接。
事实问题由阶段执行者调查；必要的用户决策与能力缺口返回主控，继续不依赖它的工作。

`advance-project` 的 code-review 使用 `review-implementation` 的 single-agent 模式：
由一名合格且独立的审查者覆盖正确性、实现质量与可维护性、安全、验证及实际风险
边界，不要求 quality 子代理或额外独立专员。高风险仍要求该审查者具备关键边界的
判断能力与充分证据；资格、稳定目标或必要验证的具体缺口阻止 Pass。主控登记真实
结论，不代审。其他使用场景按共享 skill 的适用模式执行，本适配不改变其他宿主。

## 身份、证据与权限

主控使用 SessionStart 身份 hook（`qoder/hooks/session-identity.py`）注入的
`additionalContext`，在每条 project.py 命令的同一命令内导出其准确的
`PROJECT_SESSION_ID=<session_id>`，调用
`python3 <dev-kit-root>/qoder/project.py --root <project> COMMAND`。
该入口只读取 `PROJECT_SESSION_ID`，返回续接命令保留本入口与准确身份的环境参数，原样执行，不依赖上一条 shell 的环境。
身份来自当前 Qoder hook，不能用逐轮值、worker ID、其他宿主变量或随机值替代。
hook 未安装、未生效或当前主控身份未暴露时，报告缺口并阻塞项目状态写入。

主控为每个真实贡献执行安排 contributor-session 标签，供 `--author-session` /
`--reviewer-session` 与报告归属使用；标签区分真实作者、审查者和登记者，不登记存活
状态，也不要求未暴露的宿主 worker ID。写入前记录实际作者，替换或修复执行继续保留
累积作者归属。独立审查必须排除相应成果的实质作者及登记者；新标签、干净上下文或
其他作者的后续修改，都不能让先前实质作者恢复独立性。设计的机械修正遵循共享边界。

主控维护当前真实任务回执、等待、结果整合及可控资源收尾；项目状态仅保存内容绑定
成果与实际贡献证据，不以 worker 存活锁住工作项。跨宿主接管从可访问成果继续，旧
任务不可查询不要求恢复或证明其停止；真实代码写入协调与必要隔离仍由主控负责。
仅报告工具直接暴露的执行信息，不读取私有会话日志补取身份。角色和 settings 配置、
磁盘检查也不是实际型号证据；真实回执未暴露型号则标记未验证，已暴露
型号与固定配置不符时按配置未满足处理，不静默接受回退。

继承当前权限模式；模板不写 `permissionMode`，不设置宽松权限或自动 worktree 隔离。
子代理不能自行收紧已继承的宽松权限，实际拒绝仍然生效；原生 Plan 保持只读。
共享 skill、原生角色和适配须在实际环境可读。Qoder 用户级通过 `~/.agents/skills`
发现共享 skills，无需 `~/.qoder/skills` 重复链接。角色是安装副本，仓库修改后须按
[安装与更新](INSTALL.md)重新复制并 reload；磁盘更新与当前会话加载是不同证据。

共享技能的只读规划合同对应本宿主明确启用的 Plan；普通执行合同对应 Agent 并保留
实际权限。仅提到计划、探索姿态或工具拒绝不能切换模式。授权安装时由本宿主入口
提供 [INSTALL.md](INSTALL.md)，公共安装技能只执行已提供的安装合同。
