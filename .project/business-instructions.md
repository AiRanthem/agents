# 项目强制指令

## 开发分支基线

本项目的所有代码开发分支必须从 OpenKruise Agents 上游仓库 `https://github.com/openkruise/agents` 的最新 `master` 创建。

每次创建开发分支前，必须核验 `upstream` 指向该上游仓库，成功执行 `git fetch upstream master`，并以本次刷新后的 `upstream/master` 提交作为新分支的起点。刷新失败时停止创建分支，待成功取得上游最新提交后继续。

按主工作区约定在 `worktrees/` 下创建隔离 Git worktree，主检出保持约定主分支。创建后核验新分支的初始 HEAD 与本次获取的 `upstream/master` 提交一致，并记录基线 commit。

本规则适用于项目全部工作项；本项目创建代码开发分支时，以本条统一基线要求为准。
