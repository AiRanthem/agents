# 当前上下文

2026-10-20，用户要求创建「E2B 兼容性」项目，并明确：解决任何 E2B 兼容性问题前，先讨论是否需要解决，确认需要解决的再进入设计。

同日，用户指定项目记录存储于 GitHub `AiRanthem/agents`，分支保持 `projects/e2b-compatibility`，并确认上述约束。

本项为需求管理总项。2026-10-20，用户本轮明确要求「解决上游 #1083 #1084 #1085 三个 Issue」；已将三项问题及上游允许的解决边界登记在当前 requirement.md。三项在查询时均为 OPEN，暂无评论。

- #1083：https://github.com/openkruise/agents/issues/1083 。列表 `order`、`template`、`startedAfter` 被误当 metadata，且排序默认值与协议不同。
- #1084：https://github.com/openkruise/agents/issues/1084 。Pause 忽略请求体 `memory`，可能静默执行与调用者意图不同的暂停模式。
- #1085：https://github.com/openkruise/agents/issues/1085 。Snapshot 忽略创建 `name`/`memory` 与列表 `name`，且返回 `names: null`。

已读取三个 Issue 及其引用的 E2B OpenAPI `b52cd30c14bf7038ba5bfbd15456b1dabe567082` 对应原文。规范中的命名快照包含复用已有模板并分配新 build 的语义，名称筛选还允许 ID、命名空间及 tag；不能将简单记录 checkpoint 名称等同于完整兼容。Pause 的 filesystem-only 语义还影响恢复时冷启动以及 auto-resume。

关联源码仓库 `/Users/sophon/Workspace/OKAWorkspace/agents` 保持 `develop`；已确认干净并执行 `git pull --ff-only`，随后刷新 `upstream`，当前开源候选基线为 `upstream/master` 的 `2b06e1103`。后续证据须区分开源基线与内部 develop，不在主检出上实现修复。

当前仅登记问题并核对证据，未形成正式设计、设计批准、独立评审或源码变更；尚未创建代码 worktree。本项目还没有注册开发代码仓库或具体开发子项。

待讨论事项：三项的实际影响与解决必要性；#1084/#1085 采用完整新能力还是上游允许的显式 400；据此确定行为验收条件、开发项和交付方式。用户的解决请求不能记作对尚未提出的方案的批准。源码提交、推送、PR 与 Issue 关闭仍需覆盖相应操作的授权。
