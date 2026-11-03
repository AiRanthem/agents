# 项目业务约束

## 工作项 1 的既有约束

迁入的 `1-gateway-wakeup-lifecycle` 继续遵守原项目已批准的开发基线约束：开发分支从 OpenKruise Agents 最新 upstream/master 创建，创建前核验 upstream 指向 `https://github.com/openkruise/agents` 并刷新基线；主检出保持主分支，在隔离 worktree 中开发。

既有开发工作树位于 `worktrees/1-gateway-wakeup-lifecycle`，保留其原分支、基线和未提交代码。配置中的源码仓库实际位于 `.project-local/repos/agents`；读取 `.project/repositories.yaml` 获取其现有位置。项目记录升级保留源码位置、真实用户决定、批准、审查、作者和交付事实。

## IM 唤醒需求的共同约束

工作项 2、3 分别记录 Webhook 唤醒和 WebSocket 唤醒，二者并列且无相互前置依赖。能力需要通用化，飞书与 OpenClaw 是首个验证场景。拆分依据及 Pause 期间的协议边界见 `evidence/im-wakeup-paths-and-capabilities.md`。

Webhook 工作项 2 按用户要求分成 Gateway 代码与 ACK 编排两个子任务，分别对应主工作区的 agents 和 ack-components；具体开发与发布分支尚未选定。WebSocket 工作项 3 的实现仓库与方式仍待明确。项目中的既有 agents 配置和工作项 1 不构成已交付前置能力的证据。

2026-11-03，用户明确工作项 2 无需强可靠：Gateway 内存接收即可，接收 Gateway 退出造成事件丢失可以接受。该决定替代此前持久化接收的解释。用户要求以所有唤醒固定耗时 10 秒为分析假设，核对实际 ack-components 编排与对应 Gateway 退出机制，不使用 Agents 源码仓的示例编排代替。此选择不扩展到工作项 3，也不代表完整设计或业务实施授权。

2026-11-04，用户确认先停收、业务排空、Envoy drain、最后退出的方案，指定业务排空上限为 60 秒，并要求拆成两个子任务，编排变更依赖代码交付。依赖以真实交付证据判定；设计批准、评审通过或项目记录推送均不代替代码交付。启用新 preStop 还必须核对目标镜像确实包含匹配的管理接口。父项保留整体需求与集成验收责任；本轮仅记录拆分，不自动开始代码、镜像发布、编排修改或部署。
