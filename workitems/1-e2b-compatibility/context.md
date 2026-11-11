# 当前上下文

## 当前合同与用户批准

本项解决 E2B #1083、#1084、#1085。当前合同为 `requirement.md` 与 `spec.md` v7。用户于 2026-11-10 在本会话的 receiving-code-review 评估后回复「同意」，批准保留旧快照 ID、稳定错误消息、新游标方向校验并兼容历史 token，以及 template 拒绝 tag、去空白和转小写；2026-11-11，用户在本会话审查未提交变更后选择「保留现在的做法」，批准省略 `order` 时沿用 `nextToken` 携带的方向，v6 的默认降序校验据此失效。实际来源会话为 `01a1c4bb-498d-7843-8186-cebf503116cf`；批准目标哈希记录在 `.project/state/1-e2b-compatibility.yaml`。

本轮对收到的五项反馈均按已批准目标完成修正。当前设计和实现的独立评审均 pending；历史 v2/v4/v5 的审批、评审及复用记录保持原目标，不作为 v6 的独立通过结论。

## 当前源码与 PR 身份

- 源码仓库 `openkruise/agents`；本地工作树 `worktrees/1-e2b-compatibility`，分支 `fix/e2b-1083-1085-261020`。
- 本轮开始时本地 HEAD 为 `0a80aa84992283deddf7bfb93e66fffe1d059e60`，工作树干净。该本地提交历史与远端 PR 不同；本轮保持历史和分支不变，只留下修正的未提交文件。
- 上游 [PR #1103](https://github.com/openkruise/agents/pull/1103) 当前检查为 OPEN、非草稿、未合入；head `e2dd1348883435758c12315b55e43f89f1b0344f`，比较基线 `0179aad20a43aad1fa6627c2a818372eb4e3f202`，正文关联三个 Issue。`merged` 交付义务仍为 pending。
- 本轮修改 6 个源码/测试文件，+102/-190；相对本地 HEAD 的完整 binary diff SHA256 为 `c7250b84ade4d9a08071b385b05c2ec6246fcef1228528ac644bc9ce4a73ba22`。
- 已用独立临时 index 将该补丁干净应用到 PR head，得到组合 tree `5be6bb8a35694f90afd6847c0d33577cc4684d05`。相对上述 PR 比较基线的完整交付差异为 21 文件、+1237/-156，`git diff --check` 通过。未修改实际 index，也未为源码创建提交或推送。

## 本轮行为与反馈处置

- P1：移除 `reconcileSnapshotAlias` 及其删除辅助流程。命名创建保留所有旧对象，返回本次创建 ID；name 查询仍只返回该 owner 最新可见的一条。旧 owner 非空守卫的待补项随整条自动删除流程移除而不再适用。
- P2：保留 Infra 名称校验与类型化 400 映射；对外返回 `Invalid snapshot name`，其他后端创建失败返回 `Failed to create snapshot`，原始错误继续内部记录。既有授权后资源诊断后缀不变。
- 游标：新 stable token 带 `descending`；显式 `order` 与 token 方向不符返回 400，省略 `order` 时沿用 token 方向，token 无方向时默认降序。历史裸 key 和无方向 stable cursor 继续按当前请求方向处理。快照列表保持升序，其他既有分页调用者不变。
- template：归一化首尾空白和大小写，含 tag 分隔符或归一化后为空时 400；仍通过中性 `GetTemplate()` 匹配，不引入池名旁路。

## 验证与原始证据

原始输出与一次性快照保存在主工作区 `local-storage/e2b-review-261110/`，不作为正式源码或独立评审报告。

- 工作树：`go test ./pkg/utils/pagination ./pkg/servers/e2b -run '^(TestPaginator.*|TestDecodeCursorToken|TestValidateCursorOrder|TestParseListSandboxesReservedParams|TestListSandboxes_Pagination.*|TestCreateSnapshot|TestListSnapshots)$' -count=1`。分页包通过；E2B 包在清理已失效的测试 import 后通过，原始日志 `focused-tests.log`。首次尝试被 Go 缓存写权限阻止，提权执行成功。
- 组合 PR tree：从 `5be6bb8a...` 导出 `pr-target/` 后，以上两个包与同一筛选集全部通过，日志 `pr-target-tests.log`。该快照保留远端已有的其他测试和基线差异，因此验证覆盖实际 PR 组合目标。
- 回归有效性：只读 Go overlay 分别将 snapshot/list 实现切回 PR head，保留新断言。旧实现产生预期的断言失败：旧对象被删、返回其他请求的 ID、错误细节透传，以及 tag/纯空白/大小写/方向校验缺失。日志 `snapshot-baseline-regression.log` 与 `list-baseline-regression.log`；没有编译失败代替行为失败。
- `gofmt`、工作树及组合 PR 的 `git diff --check` 通过。没有更改 API 类型或生成文件，无需新增生成步骤。未运行真实集群、多副本或 E2E；已有远端 CI 只覆盖修正前 head，不能覆盖当前未提交修正。

## 历史人工验收与交付

2026-10-22 用户明确确认「工作项1已经完成开发通过了全部人工验收」，并授权提交、推送和创建上游 PR。既有源码提交 `f448ab3d53573ddef69049011a51497bb8d3b310` 已按该授权提交至 fork `AiRanthem/agents` 并建立 PR #1103；这些是历史交付和人工结论，不自动覆盖当前 v6 修正。原始开发基线为 `fd2bea7193d98c1d456fa6c43a2ae3e7e4f4fd48`。

SandboxSet `spec.templateRef` 模板身份问题已按独立授权提交 [Issue #1102](https://github.com/openkruise/agents/issues/1102)，本轮不修改该问题。PR 评论线程未回复、未 resolve；源码未提交或推送，未部署、关闭 Issue、清理工作树或标记交付完成。

## 保留的边界与待核对事实

- 名称查询为 informer 可见集合上的最终一致；跨副本时钟偏差或创建延迟可能影响最新者排序。旧快照继续占用存储，直到显式删除或既有生命周期清理。
- 历史无方向 token 无法检测跨方向误用；保留兼容，不宣称历史跨版本遍历一致。
- SandboxSet templateRef 和从快照恢复的模板身份限制保持不变。
- 既有 Pause 源码允许 `memory:true`，而 v5 原批准文档要求任何显式 memory 均 400。该差异在本轮评估前已存在，相关后续批准来源尚未核对；本轮反馈及用户确认没有覆盖 Pause，故保留其源码和原审批文本，不把当前代码反推成新的用户批准。
