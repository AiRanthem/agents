# Main workspace association

Identity: **OKAWorkspace** (`oka-workspace`).

Recovery reference: `git@gitlab.alibaba-inc.com:serverlessinfra/OKAWorkspace.git` at `refs/heads/master`.

Local binding: `.project-local/main-workspace.json`.

## Project-specific instructions and routes

# 主工作区关联

项目关联 /Users/sophon/Workspace/OKAWorkspace，复用其环境、原始 AGENTS.md 指令入口及按任务需要加载的技能。

主工作区继续保持其 master 主检出；项目管理记录使用独立 Git 仓库目录与专用分支。工作项 1 的代码仓库为 OpenKruise Agents（agents），既有代码工作树位于项目内 worktrees/；工作项 2 的代码仓库、实现范围和验收标准尚待明确。
