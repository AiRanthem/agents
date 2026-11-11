# OKA 日常开源开发

# OKA 日常开源开发

本项目用于持续记录和管理 OpenKruise Agents 的日常开源开发需求，关联 OKAWorkspace，共享主工作区的业务背景、仓库约定和 Python 环境。

初始需求来自用户：当前的 sandbox-gateway 支持流量自动唤醒，但是没有调整 shutdownTime/pauseTime。需要优化这个问题。

原工作项 `1-gateway-wakeup-lifecycle` 已按用户要求于 2026-11-03 迁入“IM 自动唤醒”项目，工作项记录与包含未提交代码的工作树一并迁移，保持既有状态；其已发布编号保留，不重新分配。

迁移目标：`/Users/sophon/Workspace/OKAWorkspace/projects/im-auto-wakeup/workitems/1-gateway-wakeup-lifecycle`；代码工作树位于目标项目的 `worktrees/1-gateway-wakeup-lifecycle`。迁移前记录可从本项目提交 `4939ae96e463dbf8064a752cc32853fb85a2034a` 恢复。

当前工作项：[2-sandboxset-create-consistency（修复独立 SandboxSet 创建后 E2B create 的缓存同步竞态）](../workitems/2-sandboxset-create-consistency/requirement.md)。用户已确认在 cache 层进行每次查询最多 5 秒的纯 informer 等待，仅覆盖内嵌模板的 SandboxSet；v1 已于 2026-11-11 通过独立设计审查，状态为 `implementable`，见[审查报告](../workitems/2-sandboxset-create-consistency/records/design-review.md)。业务实现未获授权或开始。
