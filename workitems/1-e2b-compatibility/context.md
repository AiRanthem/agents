# 当前上下文

本总项管理 E2B 兼容性。用户于 2026-10-20 要求先讨论每项解决必要性，确认后再设计；项目记录存储于 GitHub `AiRanthem/agents` 的 `projects/e2b-compatibility` 分支。

## 当前合同与批准

用户要求解决 #1083、#1084、#1085，并在必要性讨论后确认三项均需修复。此后用户逐项确认了扩展范围：Pause 禁止显式 memory；Snapshot 的 memory 映射与持久化内容头优先；本版本支持命名快照、同名替换与按 name 过滤。2026-10-21，用户要求同步设计文档并按计划实施，把替换语义定为“先建、成功后按最新者收敛”。

2026-10-22，独立实现评审（multi-agent，会话 `3387366e-d695-4926-9dea-fc31e52a5491`）判定实现与 v4 文本冲突：别名收敛按 owner 作用域执行，而 v4 要求 team 作用域。用户裁决采用 **owner 作用域并修订契约**；同时确认 `template` 筛选以中性 Infra 的 `GetTemplate()` 为准、不在 API 层叠加池名匹配，SandboxSet `spec.templateRef` 造成的模板身份不一致判定为 SandboxSet 侧缺陷并已提上游 Issue #1102，由快照恢复的 Sandbox 的模板身份记录为已接受限制。

当前合同为 `spec.md` v5（sha256 `773c6bb3c5a55db6415cdcecab7f7ca65a3f77aeb470ca1fdab5c69bc3d430bf`）与 `requirement.md`（sha256 `675a6318cc86f9440b9537247ccf28d685e618776a4f4d093f3e4018d88f30c0`），批准来源会话 `3387366e-d695-4926-9dea-fc31e52a5491`，程序记录 `approval: current`。v4 及更早的批准与独立评审报告保留在 `records/`，其合同绑定已被 v5 取代。

## 当前实现状态

源码仓库 `openkruise/agents`，工作树 `worktrees/1-e2b-compatibility`，分支 `fix/e2b-1083-1085-261020`，基线 `fd2bea7193d98c1d456fa6c43a2ae3e7e4f4fd48`。

已按用户明确授权将 21 个文件（+1315/-137）提交为 `f448ab3d53573ddef69049011a51497bb8d3b310`（含 Signed-off-by），推送到 GitHub fork `AiRanthem/agents` 的 `fix/e2b-1083-1085-261020` 分支，并核验远端 OID 与本地一致。该提交相对父提交的 diff sha256 为 `c263c6aff74963ed54c498cfab35cab888154ffd9cbd91c18536f8643f070eaf`，与原暂存实现一致；发布后工作树干净。覆盖：列表保留参数与方向感知分页；Pause 可选 body 与 memory 拒绝；Snapshot memory 映射、别名 label、owner 作用域同名替换、name 过滤与数组型 `names`；Infra 的中性 `Alias` 与高精度创建时间 annotation；cache 的 label 过滤。

上游 PR：https://github.com/openkruise/agents/pull/1103 ，目标 `openkruise/agents:master`，正文包含 `Fixes #1083`、`Fixes #1084`、`Fixes #1085`。本会话最新查询为 OPEN、非草稿、可合并、尚未合入，head 为上述源码提交。尚未证明 `merged` 交付义务完成。

契约修订（v5）后的既有待补记录如下；本会话只提交既有实现，未执行这些修复，也未将用户人工验收表述当作这些源码差异已经消失的证据：

- `reconcileSnapshotAlias` 增加 owner 非空守卫：owner 为空时跳过收敛并记日志，避免空值退化为跨 owner 的列举与删除。
- 列表 `template` 筛选补正例测试（现仅有“未知模板返回空集”的反例，无法区分恒假实现）。
- 可选测试盲点：`name` 与非法 `limit` 组合、superseded 用例断言本次新建对象确已删除、同 key 排序 oracle 与名称顺序解耦。

评审阶段验证：针对性 `go test`（`pkg/servers/e2b`、`pkg/servers/e2b/models`、`pkg/utils/pagination`、`pkg/cache`、`pkg/sandbox-manager/infra/sandboxcr`）通过；`go test -race ./pkg/servers/e2b -run '^TestCreateSnapshot$' -count=3` 通过；`git diff --check` 无输出。未运行 E2E，未做多副本或真实集群验证。

本会话提交前新增验证：E2B 列表、Pause、Snapshot、模型扩展头、分页定向测试通过，日志 `/tmp/e2b-item1-pr-tests.log`；cache Checkpoint 列举及 Infra Succeeded Checkpoint 筛选定向测试通过，日志 `/tmp/e2b-item1-pr-infra-tests.log`。后者曾受到生成脚本临时 vendor 清理干扰，待生成结束后以 `-mod=mod` 重跑通过。`make generate manifests` 成功且未产生额外源码差异，日志 `/tmp/e2b-item1-pr-generate.log`；gofmt、`git diff --check` 通过；与最新 `upstream/master@a4df9e5498d2a9ba7d34bf87820a48b48680cebf` 的 merge-tree 检查无冲突。未在本会话执行 E2E 或核验 CI 通过；推送钩子返回 `No data need to be scanned`，不作为有效泄漏扫描通过证据。

## 人工验收与控制权

2026-10-22，本会话用户明确确认「工作项1已经完成开发通过了全部人工验收」，并授权提交与创建上游 PR；随后明确要求「接管工作项」。已通过原生入口的 `takeover 1-e2b-compatibility` 接管，项目记录提交 `009c734332892a01af0bcbbd68eff3c218e64706` 已发布并核验远端。接管不改变当前合同，不补造独立评审，也不代表交付完成。

接管后尝试以用户上述真实确认执行 `autonomy accept`，控制器返回 `blocked`，原因为 `delivery requires a current independent implementation review`。用户人工验收确认在本文保留；程序绑定的验收尚未成功登记。需要当前独立实现评审证据满足控制器门禁后才能登记，不能将旧合同的评审或本会话提交前测试当作当前独立评审通过。

## 门禁与后续

- `design-review` 当前 eligible（approval 已 current），需要未实质编写 v5 的独立会话执行。
- `development-start` 仍被“独立设计评审”门禁阻塞。
- 源码已按单独授权提交、推送并创建 PR #1103；PR 尚未合入，未执行 Issue 关闭、部署、清理或将工作项标记为完成。
- 已按用户授权向上游 `openkruise/agents` 提交 SandboxSet `spec.templateRef` 模板身份与 E2B TemplateID 不一致的 Issue：https://github.com/openkruise/agents/issues/1102（bug 标签，核对基线 `master@fd2bea719`）；该授权仅覆盖创建该 Issue，不覆盖源码提交、PR 或关闭既有 Issue。
- 已知残余：同一 owner 的并发同名创建在多副本或 informer 滞后下可能残留重复对象，由后续同名创建清理；跨 owner 同名共存是契约预期；较早返回的 `snapshotID` 可能被较新请求删除。`CheckpointInfo.CreationTimestamp` 为固定宽度 UTC 纳秒串，存量对象缺失 annotation 时降级为秒级精度。

## 主要来源

- https://github.com/openkruise/agents/issues/1083
- https://github.com/openkruise/agents/issues/1084
- https://github.com/openkruise/agents/issues/1085
- https://github.com/openkruise/agents/pull/1103
- https://github.com/e2b-dev/E2B/blob/b52cd30c14bf7038ba5bfbd15456b1dabe567082/spec/openapi.yml
- https://help.aliyun.com/zh/cs/user-guide/clone-agent-sandbox-using-checkpoint
