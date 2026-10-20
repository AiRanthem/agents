# 当前上下文

本总项管理 E2B 兼容性。用户于 2026-10-20 要求先讨论每项解决必要性，确认后再设计；项目记录存储于 GitHub `AiRanthem/agents` 的 `projects/e2b-compatibility` 分支。

## 当前范围与确认

用户要求解决 `openkruise/agents` #1083、#1084、#1085。在核对事实并讨论三项均有必要修复后，用户明确选择“最小修复 (Recommended)”：#1083 完整修复列表筛选/排序/分页；#1084 对 `memory:false` 返回 400；#1085 支持 filesystem-only 快照、修正 `names` 数组，对创建和列表的 `name` 返回 400。实际问题与选择原文见 `decision.md`，当前验收范围见 `requirement.md`。

## 已取得的证据

- 三个上游 Issue 查询时均为 OPEN、无评论；读取了其引用的 E2B OpenAPI `b52cd30c14bf7038ba5bfbd15456b1dabe567082` 原文，并查阅 E2B 文档。SDK 报告版本为 e2b 2.56.0。
- 源码主检出 `/Users/sophon/Workspace/OKAWorkspace/agents` 保持 `develop`。本会话先确认干净并执行 `git pull --ff-only`，再刷新 upstream；只读核对基线为 `upstream/master@2b06e110327f52da85053730a531ec3b3b0d6a46`，三项问题仍存在。
- 列表共享分页器默认升序，启动时间来源是领取时间，模板 ID/现有别名来自已有模板身份；不能全局反转其他列表的顺序。
- PauseOptions 无单次持久化内容选择；Checkpoint 已支持单次 PersistentContents 覆盖，但无 E2B 命名/同名 build/tag 体系。

## 当前批准

用户在会话 `bfa1920e-2676-4e3a-a8d9-70c449134a7b` 明确回复「批准设计并授权独立评审」。批准已通过 `decision-record --approval-source` 发布，提交为 `0b10678f8f320da086c4df75275b43ea6a041546`，程序返回 `approval: current` 与 `handoff: independent_review`。

批准目标和评审后复核目标一致：设计版本 1，`spec.md` SHA256 为 `f79b4857b1edb0b8797d79b61801b7e5764554f51592132a676c25b9eb2f9971`，`requirement.md` SHA256 为 `3123f4c399576e7c3a6744af42127014c329541e1c4c32e44c63cd7e1506d656`。设计和需求正文未改，不需要重复批准该未变版本。

## 独立评审证据：暂无法判定通过

已通过实际 `functions.Agent` 调用，由未参与设计编写的新 `general-purpose` 执行完整报告型设计评审。结论为 **unable / Unable to conclude**：未发现已证实的阻塞设计缺陷，但有一项关键可行性证据缺口 E1。完整临时报告：`/tmp/e2b-design-review.tEAObC/design-review.md`；已核对 SHA256 为 `a651d21b9b5bb6ff1ed9f3a681ecf185f48ef7274b0cccf61c75d0b4b7437a46`。

报告覆盖列表参数、实际领取时间、稳定游标与共享分页，Pause 可选请求体及拒绝无写入，Snapshot 内容集合/扩展头/名字拒绝/数组，路由、租户可见性和错误边界。认为这些 API 修复有可行的既有接口基础；未将用户接受的限制当成缺陷，也未将作者自评当作独立证据。

### E1：filesystem-only 恢复的依赖尚未闭环

`spec.md:57-65` 承诺该次 filesystem-only 快照能够用于从保存的文件系统冷启动。固定源码基线的 `pkg/sandbox-manager/infra/sandboxcr/clone.go:586-597` 能表达单次内容覆盖，`:520` 写入 `AnnotationRestoreFrom`，但评审核对的默认 controller 路径尚不能证明该标识被用于恢复实际产物：`pkg/controller/sandbox/core/interface.go:130-133` 仅注册 common 控制；`common_control.go:118-126` 初次 Pod 创建没有传入 CheckpointID；`pod_control.go:145-168` 需要调用方提供非空 CheckpointID 及配置的注解键才注入恢复标识。该开源基线的 checkpoint controller 目录不含内部 develop 中的完整执行实现；历史规格也描述执行 controller 为独立组件。现有快照测试通过装饰器写成功状态，不能证明实际恢复。

因此需要既有 checkpoint/restore 后端的稳定版本、能力契约及接入证据，说明单次 filesystem/full 内容、KeepRunning、snapshotID 到恢复产物的关联由何处负责，并解释源模板保持原策略时仍按该次快照内容恢复。外部 controller、定制生成器或 webhook 可能提供能力；报告没有断言它们不存在，也没有将既有默认后端缺失判为本设计引入的数据丢失。

这不是 fail，不可登记成独立 Pass；补齐原始能力和挂接证据即可复核受影响覆盖，不要求为设计阶段新增运行服务或暴露私有实现。不得擅自把已批准的 snapshot memory:false 改成 400。

### 记录边界

本次前台 Agent 返回没有暴露可用于正式登记的 native agentId，评审者也明确未获得自身 native ID。没有生成随机身份、借用作者身份或从私有日志推断身份。当前仅通过本上下文保留实际报告、哈希、结论与证据摘要；未执行正式 design-review 的 pass/fail 持久化，未标记 implementable。后续需要正式记录结论时必须捕获真实独立执行身份。

## 待交接

- 用户设计批准与独立评审授权均已获得；下一步是补齐 E1 的后端证据并复核，不是再次询问是否批准相同设计。
- 项目仍只有 aggregate 总项，尚未注册代码仓库与具体开发项；源码实现须满足独立评审及 development-start 等门禁，不绕过程序直接写代码。
- 本轮未修改源码、未运行测试、未创建代码 worktree、未提交或推送源码、未创建 PR 或关闭 Issue。
- 源码提交/推送、PR、Issue 关闭和交付完成仍依赖各自实际授权与证据。
