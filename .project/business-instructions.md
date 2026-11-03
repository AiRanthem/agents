# 项目业务约束

## 工作项 1 的既有约束

迁入的 `1-gateway-wakeup-lifecycle` 继续遵守原项目已批准的开发基线约束：开发分支从 OpenKruise Agents 最新 upstream/master 创建，创建前核验 upstream 指向 `https://github.com/openkruise/agents` 并刷新基线；主检出保持主分支，在隔离 worktree 中开发。

本次只迁移已有开发工作树，保留其原分支、基线和未提交代码，不重新创建分支或刷新集成基线。既有批准、豁免、审查、作者与交付状态保持原含义。

工作项 2 仅登记需求，目标代码仓库及实现方式待明确；项目中的 agents 仓库配置来自工作项 1，不代表已为工作项 2 选定实现仓库。
