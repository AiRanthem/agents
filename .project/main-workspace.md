# Main workspace association

Identity: **OKAWorkspace** (`oka`).

Recovery reference: `git@gitlab.alibaba-inc.com:serverlessinfra/OKAWorkspace.git` at `refs/heads/master`.

Local binding: `.project/main-workspace.json`.

## Project-specific instructions and routes

# OKA 主工作区关联

本项目关联 OKAWorkspace（`oka`），本机根目录为 `/Users/sophon/Workspace/OKAWorkspace`。主工作区仓库为 `git@gitlab.alibaba-inc.com:serverlessinfra/OKAWorkspace.git`，主分支为 `refs/heads/master`。

依赖主工作区的操作应读取其原始 `AGENTS.md`，以其中的业务约束、仓库布局、主检出纪律、隔离 worktree 规则、Python 环境和发布规则为准，并按需加载工作区技能。共享 Python 解释器为主工作区 `.venv/bin/python`。

项目管理记录使用独立 Git 仓库及专用远程分支，代码 worktree 放在项目内的 `worktrees/`。开源代码仓库为 `https://github.com/openkruise/agents`，实际开发前读取主工作区 `agents/.agents/skills/internal-external-isolation/SKILL.md`；本项目全部代码开发分支按 `.project/business-instructions.md` 从成功刷新并核验的最新 `upstream/master` 创建，在隔离 worktree 中开发。主检出保持约定主分支。

创建阶段登记项目背景和已知需求。具体设计、实现、验收和代码交付由后续明确授权的任务推进。
