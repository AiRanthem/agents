# 工作项 2 独立设计审查

结论：**Independent review passed**。未发现由本设计引入或分配给本项但未满足的阻塞问题；没有需修订的非阻塞发现或必要证据缺口。用户已批准的 v1 合同可进入实现准备，设计状态登记为 `implementable`。本结论不构成实现授权、代码审查、人工验收或运行验证。

## 审查身份与输入

- 日期：2026-11-11。
- 审查者：Codex（本次独立审查会话，主 agent `/root`）。当前会话未参与 v1 或任何前序版本的实质设计编写、修订；直接读取完整原文和关键源码完成评估，未派生额外审查者，未声称跨模型审查。
- 授权：用户本次原文“独立审查工作项2的设计”。用户此前对完整 v1 的批准来源见 [decision.md](../decision.md)。项目指令授权本次审查记录、状态同步、提交及普通推送。
- 工作项：`2-sandboxset-create-consistency`，无前置工作项；开发分支和 worktree 尚未创建。
- 项目输入提交：`d4a5509fea0b282df5d06b3144abc9228ce0b90e`，输入工作区干净。
- 完整输入：[requirement.md](../requirement.md)、[spec.md](../spec.md)、[decision.md](../decision.md)、[context.md](../context.md)、项目及原始主工作区和源码仓库适用指令。

| 文档身份 | SHA-256 |
| --- | --- |
| 审查输入 requirement.md | `f2880a7ea323cc16cd90acd2972394840afdc647c93f3d636703a031183f0c1d` |
| 审查输入 spec.md v1 | `70cb9eee36a6db9a56b57554d1556303573bd9cb933055d4d4ca90904776cd46` |
| 审查输入 decision.md | `9ce6c3a9dde12e4f2c0baec97106b78e2be61a1e1d3ceed389bb0717dd73dc76` |
| 状态登记后 spec.md v1 | `d2e50ca6a0b1c4561d38477f30a65838302572f629b30fd5e238eef75b0ca49a` |

本轮对设计文件的唯一修改是 front matter 的 `design_status: review-pending` → `implementable`，正文逐字不变，版本仍为 1，原用户批准继续覆盖该合同。需求、决定和上下文的同步仅记录本次已发生的审查，不新增产品决定。

源码目标为成功刷新并由 `git ls-remote upstream refs/heads/master` 核验的开源提交 `3d9af5799d873e278cbfcb8871a0d0a3ec726447`。实际阅读的干净主检出 `/Users/sophon/Workspace/OKAWorkspace/agents` 保持 `develop`，成功执行 `git pull --ff-only` 后 HEAD 为 `7b86412bf14373963c648a7ceed91d91b5c02ceb`。逐文件比较确认本次关键 cache、Manager、Infra、模板 API 和 namespace/auth 链路与上游相同；`create.go` 的差异是 clone 路径中的内部存储鉴权 hook，不改变被审查的模板判定及其顺序。此处为分析基线，不是未来开发分支基线。

## 判断与源码依据

**修改归属和可行性。** `PickSandboxSet` 已集中承载名称索引查询，返回空列表和读取失败在内部可区分；在此处仅对空结果有限重查，可以保持公开接口和上层分支。现有 `Provider` 明确要求 Get/List 只读已同步的 informer store，生产实例使用 manager 的缓存客户端；设计没有扩大 API 层或 Manager 的职责，也不需要新增公共接口、状态持久化或资源写入。依据：[cache.go:395](https://github.com/openkruise/agents/blob/3d9af5799d873e278cbfcb8871a0d0a3ec726447/pkg/cache/cache.go#L395)、[interface.go:36](https://github.com/openkruise/agents/blob/3d9af5799d873e278cbfcb8871a0d0a3ec726447/pkg/cache/interface.go#L36)、[cache.go:301](https://github.com/openkruise/agents/blob/3d9af5799d873e278cbfcb8871a0d0a3ec726447/pkg/cache/cache.go#L301)。

**创建路径和等待预算。** E2B 先执行 `HasTemplate`，失败后才查 checkpoint；Manager claim 前再次检查；库存选择读取 updateRevision，冷启动再次取得 SandboxSet。对象在等待窗口内可见后，第一次查询可返回对象，后续查询在对象持续可见时立即命中。独立的 cache 窗口不替代 Infra 的 claim context，更不保证 Sandbox 就绪；设计明确区分这些期限，与原需求一致。依据：[create.go:103](https://github.com/openkruise/agents/blob/3d9af5799d873e278cbfcb8871a0d0a3ec726447/pkg/servers/e2b/create.go#L103)、[api.go:141](https://github.com/openkruise/agents/blob/3d9af5799d873e278cbfcb8871a0d0a3ec726447/pkg/sandbox-manager/api.go#L141)、[infra.go:149](https://github.com/openkruise/agents/blob/3d9af5799d873e278cbfcb8871a0d0a3ec726447/pkg/sandbox-manager/infra/sandboxcr/infra.go#L149)、[claim.go:636](https://github.com/openkruise/agents/blob/3d9af5799d873e278cbfcb8871a0d0a3ec726447/pkg/sandbox-manager/infra/sandboxcr/claim.go#L636)、[claim.go:951](https://github.com/openkruise/agents/blob/3d9af5799d873e278cbfcb8871a0d0a3ec726447/pkg/sandbox-manager/infra/sandboxcr/claim.go#L951)。

**取消、错误与并发。** 设计已要求每次调用独立计时、遵守父 context，并区分自身窗口用尽、父 context 结束和真实读取失败。这些结果可在现有 cache 返回接口表达。当前 `indexGetGroup.Do` 合并的是瞬时读取；若把整段等待直接放入它，会让晚到调用继承早到窗口、让等待者依赖首个调用的 context。该反例已经被 spec 的并发约束明确排除，属于实现必须满足的条件，不是设计缺失。等待放置方式、私有 helper 和观察间隔由实现选择，无需扩大公开合同。

**读取边界和租户范围。** 原索引按 SandboxSet 的 `metadata.name` 查找；非空 namespace 通过查询选项限定，空 namespace 保持已有跨 namespace 语义；生产 informer 的 namespace 和 label selector 过滤保持不变。普通 team 的 namespace 取 team 名，管理员及原有匿名/旧 key 场景维持已有范围。每轮沿用相同的缓存读取和匹配条件即可满足隔离要求；不必读取 API Server、搜索其他 namespace 或修改缓存对象。依据：[index.go:116](https://github.com/openkruise/agents/blob/3d9af5799d873e278cbfcb8871a0d0a3ec726447/pkg/cache/index.go#L116)、[cache.go:162](https://github.com/openkruise/agents/blob/3d9af5799d873e278cbfcb8871a0d0a3ec726447/pkg/cache/cache.go#L162)、[cache.go:412](https://github.com/openkruise/agents/blob/3d9af5799d873e278cbfcb8871a0d0a3ec726447/pkg/cache/cache.go#L412)、[sandbox.go:110](https://github.com/openkruise/agents/blob/3d9af5799d873e278cbfcb8871a0d0a3ec726447/pkg/servers/e2b/sandbox.go#L110)。现有 [tasks.go:34](https://github.com/openkruise/agents/blob/3d9af5799d873e278cbfcb8871a0d0a3ec726447/pkg/cache/tasks.go#L34) 等 update helper 使用 `GetFromInformerOrApiServer`，不符合本项纯 informer 约束；实现不能直接复用这些读取闭包。

**共用调用方与兼容性。** 模板 GET 直接调用此方法，删除模板先通过 `HasTemplate` 拒绝 SandboxSet，再处理 checkpoint。新增等待对这些调用及 checkpoint create 的影响已由用户明确接受；同名对象仍按原有 SandboxSet 优先顺序判定。`HasTemplate` 本来就把错误折叠为 bool，GET 本来也将查询错误映射为 404；“cache 保留取消/读取原因”与“上层映射保持原状”并不矛盾。依据：[templates.go:101](https://github.com/openkruise/agents/blob/3d9af5799d873e278cbfcb8871a0d0a3ec726447/pkg/servers/e2b/templates.go#L101)、[templates.go:137](https://github.com/openkruise/agents/blob/3d9af5799d873e278cbfcb8871a0d0a3ec726447/pkg/servers/e2b/templates.go#L137)、[infra.go:343](https://github.com/openkruise/agents/blob/3d9af5799d873e278cbfcb8871a0d0a3ec726447/pkg/sandbox-manager/infra/sandboxcr/infra.go#L343)。这些既有映射及管理员同名对象选择不是本项要求修复的问题，不作为阻塞发现。

**范围与验证可行性。** 冷启动仅在模板为空且存在 `TemplateRef` 时另行读取引用对象；内嵌模板路径不依赖这一步，Ref 排除范围可保持。需求的七项可观察验收覆盖命中、延迟可见、持续未命中、取消/提前截止、读取错误、独立并发、匹配边界和共用调用方。现有 [cache_test.go:291](https://github.com/openkruise/agents/blob/3d9af5799d873e278cbfcb8871a0d0a3ec726447/pkg/cache/cache_test.go#L291) 与 namespace 用例可扩展；读取错误、APIReader 零调用和独立取消仍需实施时的针对性验证。`cachetest.NewTestCache` 使用 fake client，不是真实 watch 传播证据；不得仅凭这些测试声称已验证现场同步时延。

## 实际检查与结论边界

- 完成全部需求、用户决定、设计正文及适用规则检查；直接检查上述关键调用点、初始化/索引/过滤、现有测试和测试设施。
- `git pull --ff-only`、`git fetch upstream master` 成功；远端 master SHA 与刷新后的 `upstream/master` 相同；相关核心文件的上游差异核验通过。源码检出全程无本次代码改动。
- 文档状态、SHA-256、相对链接、设计正文不变及 `git diff --check` 检查通过；本轮结果由项目提交和远端引用验证持久化。
- 未运行业务单元测试、race 测试、运行时复现、集群验证或 E2E；尚无本项实现可验证。本轮没有将用户报告的现场原因或 5 秒窗口的生产覆盖率认定为已实测事实。

保留已批准的限制：5 秒仅为每次缓存未命中的窗口；超过窗口仍可能失败；不提供更新/删除强一致性，不保证整个创建在 5 秒内完成，不新增 Ref 一致性保证，共用调用方允许增加等待延迟。没有待决产品选择或需额外批准的设计改动。

后续实现必须重新从成功刷新并核验的最新 `upstream/master` 创建隔离开发分支。独立实现审查、人工验收、源码交付、合并、部署和 E2E 均保留为未发生。
