# 当前上下文

本总项管理 E2B 兼容性。用户于 2026-10-20 要求先讨论每项解决必要性，确认后再设计；项目记录存储于 GitHub `AiRanthem/agents` 的 `projects/e2b-compatibility` 分支。

## 当前合同与批准

用户要求解决 #1083、#1084、#1085，并在必要性讨论后确认三项均需修复。此后用户逐项确认了扩展范围：Pause 禁止显式 memory；Snapshot 的 memory 映射与持久化内容头优先；本版本支持命名快照、同名替换与按 name 过滤。2026-10-21，用户要求同步设计文档并按计划实施，把替换语义定为“先建、成功后按最新者收敛”。

2026-10-22，独立实现评审（multi-agent，会话 `3387366e-d695-4926-9dea-fc31e52a5491`）判定实现与 v4 文本冲突：别名收敛按 owner 作用域执行，而 v4 要求 team 作用域。用户裁决采用 **owner 作用域并修订契约**；同时确认 `template` 筛选以中性 Infra 的 `GetTemplate()` 为准、不在 API 层叠加池名匹配，SandboxSet `spec.templateRef` 造成的模板身份不一致判定为 SandboxSet 侧缺陷并另提上游 Issue，由快照恢复的 Sandbox 的模板身份记录为已接受限制。

当前合同为 `spec.md` v5（sha256 `773c6bb3c5a55db6415cdcecab7f7ca65a3f77aeb470ca1fdab5c69bc3d430bf`）与 `requirement.md`（sha256 `675a6318cc86f9440b9537247ccf28d685e618776a4f4d093f3e4018d88f30c0`），批准来源会话 `3387366e-d695-4926-9dea-fc31e52a5491`，程序记录 `approval: current`。v4 及更早的批准与独立评审报告保留在 `records/`，其合同绑定已被 v5 取代。

## 当前实现状态

源码仓库 `openkruise/agents`，工作树 `worktrees/1-e2b-compatibility`，分支 `fix/e2b-1083-1085-261020`，基线 `fd2bea7193d98c1d456fa6c43a2ae3e7e4f4fd48`。

工作树内 21 个已暂存文件（+1315/-137，`git diff HEAD` sha256 `c263c6aff74963ed54c498cfab35cab888154ffd9cbd91c18536f8643f070eaf`），覆盖：列表保留参数与方向感知分页；Pause 可选 body 与 memory 拒绝；Snapshot memory 映射、别名 label、owner 作用域同名替换、name 过滤与数组型 `names`；Infra 的中性 `Alias` 与高精度创建时间 annotation；cache 的 label 过滤。

契约修订（v5）后仍需补的实现项，源码尚未改动：

- `reconcileSnapshotAlias` 增加 owner 非空守卫：owner 为空时跳过收敛并记日志，避免空值退化为跨 owner 的列举与删除。
- 列表 `template` 筛选补正例测试（现仅有“未知模板返回空集”的反例，无法区分恒假实现）。
- 可选测试盲点：`name` 与非法 `limit` 组合、superseded 用例断言本次新建对象确已删除、同 key 排序 oracle 与名称顺序解耦。

评审阶段验证：针对性 `go test`（`pkg/servers/e2b`、`pkg/servers/e2b/models`、`pkg/utils/pagination`、`pkg/cache`、`pkg/sandbox-manager/infra/sandboxcr`）通过；`go test -race ./pkg/servers/e2b -run '^TestCreateSnapshot$' -count=3` 通过；`git diff --check` 无输出。未运行 E2E，未做多副本或真实集群验证。

## 门禁与后续

- `design-review` 当前 eligible（approval 已 current），需要未实质编写 v5 的独立会话执行。
- `development-start` 仍被“独立设计评审”门禁阻塞。
- 未提交、未推送、未创建 PR、未关闭 Issue；项目文档发布不授权上述外部动作。
- 用户已另行授权向上游 `openkruise/agents` 提交 SandboxSet `spec.templateRef` 模板身份与 E2B TemplateID 不一致的 Issue；该授权不覆盖源码提交、PR 或关闭既有 Issue。
- 已知残余：同一 owner 的并发同名创建在多副本或 informer 滞后下可能残留重复对象，由后续同名创建清理；跨 owner 同名共存是契约预期；较早返回的 `snapshotID` 可能被较新请求删除。`CheckpointInfo.CreationTimestamp` 为固定宽度 UTC 纳秒串，存量对象缺失 annotation 时降级为秒级精度。

## 主要来源

- https://github.com/openkruise/agents/issues/1083
- https://github.com/openkruise/agents/issues/1084
- https://github.com/openkruise/agents/issues/1085
- https://github.com/e2b-dev/E2B/blob/b52cd30c14bf7038ba5bfbd15456b1dabe567082/spec/openapi.yml
- https://help.aliyun.com/zh/cs/user-guide/clone-agent-sandbox-using-checkpoint
