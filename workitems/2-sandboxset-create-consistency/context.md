# 当前证据与交接

## 设计及阶段

正式设计为 `spec.md` v1，用户已批准，并于 2026-11-11 通过本次独立审查会话的完整设计审查，状态为 `implementable`，见 [records/design-review.md](records/design-review.md)。本轮保存审查报告并同步项目状态，设计正文未改。没有开发分支或代码 worktree，没有业务代码修改、运行时复现或实现验证。

编号 `1-gateway-wakeup-lifecycle` 已发布后迁出本项目，保留其编号，本项使用此前未占用的 `2-sandboxset-create-consistency`。这是针对用户报告的问题建立的独立缺陷工作项；尚未确定对应的原始交付工作项，故 `fixes` 保持空列表，不推测关联。

## 源码证据索引

分析阶段已在 `/Users/sophon/Workspace/OKAWorkspace/agents` 的干净 `develop` 主检出执行成功的 `git pull --ff-only`，得到 `7b86412bf14373963c648a7ceed91d91b5c02ceb`，并成功 `git fetch upstream master`，取得开源分析快照 `3d9af5799d873e278cbfcb8871a0d0a3ec726447`。后续设计讨论核对的 HEAD 与上述值一致。

主会话比较了相关文件与该上游快照：cache、Manager、sandboxcr 核心链路一致；`create.go` 的差异位于无关的 clone storage hook。本记录中的源码行号对应分析时检出，仅作导航，应结合提交读取原文。

| 原文位置 | 已核实事实 |
| --- | --- |
| `pkg/cache/cache.go:395`，`PickSandboxSet` | 通过 informer 客户端的名称索引 List 查询 SandboxSet，未命中立即失败；使用 `indexGetGroup` 合并瞬时查询。 |
| `pkg/cache/interface.go:36`，`Provider` | Get/List 方法只读进程内 informer store；本项保留这一合同。 |
| `pkg/cache/cache.go:162`，`BuildCacheConfig` | Sandbox-family 对象受配置的 namespace 与 label selector 过滤。 |
| `pkg/sandbox-manager/infra/sandboxcr/infra.go:343`，`HasTemplate` | 调用 `PickSandboxSet`，以 `err == nil` 返回 bool。 |
| `pkg/servers/e2b/create.go:103`，`CreateSandbox` | 先检查 SandboxSet，再检查 checkpoint；均未命中时返回 HTTP 400 和 `Template or Checkpoint not found`。 |
| `pkg/sandbox-manager/api.go:141`，`ClaimSandbox` | 在调用 Infra claim 前再次执行 `HasTemplate`。 |
| `pkg/sandbox-manager/infra/sandboxcr/claim.go:636`、`:951` | 库存 revision 优选及冷启动通过同一个 `PickSandboxSet` 查询。 |
| `pkg/servers/e2b/templates.go:101`、`:137` | 模板 GET 和模板删除判定也复用 SandboxSet 查询链，属于已说明的等待延迟影响范围。 |
| `pkg/servers/e2b/sandbox.go:110`，`getNamespaceOfUser` | 普通 team 使用 team 名作为 namespace，管理员使用空 namespace 保持跨 namespace 查询。 |
| `pkg/servers/e2b/keys/utils.go:25`、`pkg/servers/e2b/routes.go:138` | 旧 key 及关闭鉴权的匿名请求均可能采用管理员范围。 |
| `pkg/cache/index.go:116`，`IndexTemplateID` | SandboxSet 模板 ID 索引使用 `metadata.name`。 |
| `pkg/cache/tasks.go:34`，`SandboxUpdateFunc` | 现有部分等待 helper 经 `GetFromInformerOrApiServer` 隐式回源；不能直接用于本项的纯 informer 等待。 |

旁路调用方、命名和 namespace 证据由 Luna（`gpt-6-luna / high`，任务 `01a1c894-b75a-7da1-820b-c21521e0a4b1`）只读枚举；主会话直接检查关键链路并负责设计。该证据收集任务不是独立设计评审。

## 设计完整性反思

已覆盖首次命中、窗口内传播、持续未命中、提前取消或超时、读取错误、并发请求的独立有效期、namespace 与 selector 边界、同名 checkpoint 分支，以及共用方法的 GET 和删除延迟影响。将单次 5 秒窗口与整个创建期限分开，避免不实的端到端上限承诺。Ref 场景遵照用户决定排除；不向上扩展接口或错误协议。

原作者反思认为当前合同没有未决的阻塞设计问题；接受有限窗口不能保证任意延迟下成功，以及共用调用方的未命中延迟。作者反思本身不是独立 Pass；本轮独立结论及其源码依据单列在审查报告中。未查询现场集群和请求日志，用户报告的现场原因与延迟分布未进行运行时验证。

## 项目文档验证

2026-11-11 使用主工作区 `.venv/bin/python` 和 PyYAML 完成检查：工作项与状态文件的 ID、版本和阶段状态一致，文档路由及本地链接存在，正式设计具备三个约定主章节，所有本轮文件无行尾空白且以换行结尾。设计、实现、人工验收和源码交付状态没有混淆。另执行 `git diff --check`，通过。

审查输入 `spec.md` v1 的 SHA-256 为 `70cb9eee36a6db9a56b57554d1556303573bd9cb933055d4d4ca90904776cd46`；只登记 `design_status: implementable` 后为 `d2e50ca6a0b1c4561d38477f30a65838302572f629b30fd5e238eef75b0ca49a`。独立报告绑定这两个身份，正文不变。审查时再次成功 pull 并 fetch，源码基线仍为上文提交，远端 master 已直接核验；没有执行业务代码测试或 E2E。

## 后续边界

设计独立评审已获授权并通过，当前状态为 `implementable`。实现尚未授权或开始。实现验证应覆盖独立调用窗口与取消、真实读取错误和禁止隐式回源；现有 fake client 测试不能证明真实 informer 传播延迟。将来创建开发分支时须重新遵守 `.project/business-instructions.md`：核验上游、成功 fetch 最新 `upstream/master`，从该最新提交创建隔离 worktree 并记录实际开发基线。上述分析快照不是已建立的开发基线。

源码交付方式尚未指定，人工验收、源码 push、PR、合并、部署和 E2E 结果均未发生。项目配置没有外部同步后端，因此本轮不创建或发送外部系统工作项与消息。
