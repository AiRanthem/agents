# Main workspace association

Identity: **OKAWorkspace** (`oka`).

Recovery reference: `git@gitlab.alibaba-inc.com:serverlessinfra/OKAWorkspace.git` at `refs/heads/master`.

Local binding: `.project-local/main-workspace.json`.

## Project-specific instructions and routes

# OKA 主工作区关联

本项目关联 OKAWorkspace，主工作区根目录为 `/Users/sophon/Workspace/OKAWorkspace`，主工作区仓库为 `git@gitlab.alibaba-inc.com:serverlessinfra/OKAWorkspace.git`，主分支为 `refs/heads/master`。

主工作区原始 `AGENTS.md` 是业务约束、仓库布局、主检出与隔离 worktree 纪律、Python 环境及发布规则的权威入口。开展依赖主工作区的操作时读取该原始文件，按需加载相关业务技能。

项目管理记录使用独立 Git 仓库与专用远程分支，代码开发工作树位于项目内 `worktrees/`。共享 Python 环境为主工作区 `.venv/`。业务代码仓库、开发基线及交付目标随实际工作项确认。
