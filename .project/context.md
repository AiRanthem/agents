# OKA 日常开源开发

# OKA 日常开源开发

本项目用于持续记录和管理 OpenKruise Agents 的日常开源开发需求，关联 OKAWorkspace，共享主工作区的业务背景、仓库约定和 Python 环境。

初始需求来自用户：当前的 sandbox-gateway 支持流量自动唤醒，但是没有调整 shutdownTime/pauseTime。需要优化这个问题。

原工作项 `1-gateway-wakeup-lifecycle` 已按用户要求于 2026-11-03 迁入“IM 自动唤醒”项目，工作项记录与包含未提交代码的工作树一并迁移，保持既有状态；其已发布编号保留，不重新分配。

迁移目标：`/Users/sophon/Workspace/OKAWorkspace/projects/im-auto-wakeup/workitems/1-gateway-wakeup-lifecycle`；代码工作树位于目标项目的 `worktrees/1-gateway-wakeup-lifecycle`。迁移前记录可从本项目提交 `4939ae96e463dbf8064a752cc32853fb85a2034a` 恢复。

已完成工作项：[2-sandboxset-create-consistency（修复独立 SandboxSet 创建后 E2B create 的缓存同步竞态）](../workitems/2-sandboxset-create-consistency/requirement.md)。用户明确要求登记完成，[PR #1207](https://github.com/openkruise/agents/pull/1207) 已于 2026-11-11 合入 master，合并提交为 `91274e22331bd620ce2c0173f1f97cc28d80bf4f`。源码交付、人工结论与未进行的部署/现场验证分别保留，详见[工作项上下文](../workitems/2-sandboxset-create-consistency/context.md)。

当前工作项：[3-sandboxset-test-latency（修复 SandboxSet 有限等待引入的单测耗时回归）](../workitems/3-sandboxset-test-latency/requirement.md)。`fixes` 关联工作项 2。已完成测试层修复与验证，并创建独立 [PR #1208](https://github.com/openkruise/agents/pull/1208)，提交为 `24e5feb24b8fe1ca4e76b4ff879c4252010d37ee`；生产合同与实现保持不变。固定增加 5 秒的用例恢复为 0.05 秒，五个受影响包的本地 race 检查通过；新 CI 单测步骤耗时 14分44秒，单测、lint 与覆盖率门禁通过，详见[验证记录](../workitems/3-sandboxset-test-latency/context.md)。当前待审查和人工验收，未合并或部署。
