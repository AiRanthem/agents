# 项目业务约束

## 工作项 1 的既有约束

迁入的 `1-gateway-wakeup-lifecycle` 继续遵守原项目已批准的开发基线约束：开发分支从 OpenKruise Agents 最新 upstream/master 创建，创建前核验 upstream 指向 `https://github.com/openkruise/agents` 并刷新基线；主检出保持主分支，在隔离 worktree 中开发。

既有开发工作树位于 `worktrees/1-gateway-wakeup-lifecycle`，保留其原分支、基线和未提交代码。配置中的源码仓库实际位于 `.project-local/repos/agents`；读取 `.project/repositories.yaml` 获取其现有位置。项目记录升级保留源码位置、真实用户决定、批准、审查、作者和交付事实。

工作项 2 仅登记需求，目标代码仓库及实现方式待明确；项目中的 agents 仓库配置来自工作项 1，不代表已为工作项 2 选定实现仓库。
