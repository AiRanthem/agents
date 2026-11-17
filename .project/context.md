# OKA 日常开源开发

# OKA 日常开源开发

本项目用于持续记录和管理 OpenKruise Agents 的日常开源开发需求，关联 OKAWorkspace，共享主工作区的业务背景、仓库约定和 Python 环境。

初始需求来自用户：当前的 sandbox-gateway 支持流量自动唤醒，但是没有调整 shutdownTime/pauseTime。需要优化这个问题。

原工作项 `1-gateway-wakeup-lifecycle` 已按用户要求于 2026-11-03 迁入“IM 自动唤醒”项目，工作项记录与包含未提交代码的工作树一并迁移，保持既有状态；其已发布编号保留，不重新分配。

迁移目标：`/Users/sophon/Workspace/OKAWorkspace/projects/im-auto-wakeup/workitems/1-gateway-wakeup-lifecycle`；代码工作树位于目标项目的 `worktrees/1-gateway-wakeup-lifecycle`。迁移前记录可从本项目提交 `4939ae96e463dbf8064a752cc32853fb85a2034a` 恢复。

已完成工作项：[2-sandboxset-create-consistency（修复独立 SandboxSet 创建后 E2B create 的缓存同步竞态）](../workitems/2-sandboxset-create-consistency/requirement.md)。用户明确要求登记完成，[PR #1207](https://github.com/openkruise/agents/pull/1207) 已于 2026-11-11 合入 master，合并提交为 `91274e22331bd620ce2c0173f1f97cc28d80bf4f`。源码交付、人工结论与未进行的部署/现场验证分别保留，详见[工作项上下文](../workitems/2-sandboxset-create-consistency/context.md)。

已完成工作项：[3-sandboxset-test-latency（修复 SandboxSet 有限等待引入的单测耗时回归）](../workitems/3-sandboxset-test-latency/requirement.md)。`fixes` 关联工作项 2。独立 [PR #1208](https://github.com/openkruise/agents/pull/1208) 已于 2026-11-12 合入 master，合并提交为 `2a13009e64e44da79a2b5b4de3eb3262fd6e6294`；用户明确要求关闭工作项，据此登记 `done`。生产合同与实现保持不变，CI 单测步骤由 21分45秒降至 14分44秒，单测、lint 与覆盖率门禁通过，详见[验证与交付记录](../workitems/3-sandboxset-test-latency/context.md)。未执行部署或本地清理。

设计探索中的工作项：[4-sandbox-api-config-secret-wait（sandbox-api 等待配置时避免阻塞发布）](../workitems/4-sandbox-api-config-secret-wait/requirement.md)。2026-11-17，用户更正问题为等待配置时 Pod `0/2 Ready`，导致部分发布系统卡住。当前等待能力已由源码证实；缺配置时的发布完成、Pod Ready、业务准入和滚动更新语义尚待确认。既有等待路径的局部测试通过，未验证本项修订后的发布目标；尚未批准完整设计、实现或评审。
