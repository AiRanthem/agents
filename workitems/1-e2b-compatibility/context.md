# 当前上下文

本总项管理 E2B 兼容性。用户于 2026-10-20 要求先讨论每项解决必要性，确认后再设计；项目记录存储于 GitHub `AiRanthem/agents` 的 `projects/e2b-compatibility` 分支。

## 当前合同与批准

用户要求解决 #1083、#1084、#1085，并在必要性讨论后确认三项均需修复。此后用户逐项确认了扩展范围：Pause 禁止显式 memory；Snapshot 的 memory 映射与持久化内容头优先；本版本支持命名快照、同名替换与按 name 过滤。2026-10-21，用户要求同步设计文档并按计划实施，计划包含“同名快照改为创建成功后再删除旧快照”和“Pause 拒绝尾随内容”；随后指出“先查后建”在并发同名创建下仍会泄漏，要求改为创建成功后再列举并排除刚创建的对象，据此把替换语义定为“先建、成功后按最新者收敛”。

当前合同为 `spec.md` v4 与同步后的 `requirement.md`，批准来源会话 `e933eec0-f2b0-46e5-8b79-c2eef79d1b20`，程序记录 `approval: current`。原 v1/v2/v3 批准与独立评审报告保留在 `records/`，但其合同绑定已被 v4 取代。

## 当前实现状态

源码仓库 `openkruise/agents`，工作树 `worktrees/1-e2b-compatibility`，分支 `fix/e2b-1083-1085-261020`，基线 `fd2bea7193d98c1d456fa6c43a2ae3e7e4f4fd48`。

工作树内共 20 个文件的改动（本轮修复后需重新暂存），覆盖：列表保留参数与方向感知分页；Pause 可选 body 与 memory 拒绝；Snapshot memory 映射、别名 label、同名替换、name 过滤与数组型 `names`；以及本轮修复——替换改为“先建、成功后按最新者收敛”（最新者删除其余对象，被取代者删除自身并返回最新者 ID），Infra 的 `CreationTimestamp` 改为固定宽度 UTC 纳秒串，Pause 请求体拒绝首个 JSON 对象之后的尾随内容。

本轮验证：`gofmt` 无差异；`go vet ./pkg/servers/e2b/ ./pkg/sandbox-manager/infra/sandboxcr/` 通过；`go test ./pkg/servers/e2b/... ./pkg/sandbox-manager/infra/sandboxcr/ -count=1` 全部通过，包含新增的“创建失败保留旧快照”“创建期间旧快照仍存在”“多个旧别名持有者被清理”“被更新者让位并返回最新 ID”“尾随内容被拒绝”等用例。未运行 E2E。

## 门禁与后续

- `design-review` 当前 eligible；需要未实质编写 v4 的独立会话执行。
- `development-start` 仍被“当前用户批准与独立设计评审”门禁阻塞，因为 v4 是实质合同变更，原 v2 独立评审覆盖不能直接复用。
- 未提交、未推送、未创建 PR、未关闭 Issue。项目文档发布不授权上述外部动作。
- 已知残余：收敛完成前同别名可能短暂重复；并发同名创建中较早请求已返回的 `snapshotID` 可能被较新请求删除；列举或删除失败只记录日志，残留由后续替换清理。`CheckpointInfo.CreationTimestamp` 已改为固定宽度 UTC 纳秒串，排序不再受秒精度限制。

## 主要来源

- https://github.com/openkruise/agents/issues/1083
- https://github.com/openkruise/agents/issues/1084
- https://github.com/openkruise/agents/issues/1085
- https://github.com/e2b-dev/E2B/blob/b52cd30c14bf7038ba5bfbd15456b1dabe567082/spec/openapi.yml
- https://help.aliyun.com/zh/cs/user-guide/clone-agent-sandbox-using-checkpoint
