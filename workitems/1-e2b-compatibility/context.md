# 当前上下文

本总项管理 E2B 兼容性。用户于 2026-10-20 要求先讨论每项解决必要性，确认后再设计；项目记录存储于 GitHub `AiRanthem/agents` 的 `projects/e2b-compatibility` 分支。

## 已确认范围与批准

用户要求解决 #1083、#1084、#1085，并在必要性讨论后选择最小修复：#1083 完整修复列表筛选/排序/分页；#1084 的 `memory:false` 返回 400；#1085 支持 filesystem-only 快照、`names` 数组，对创建和列表的 `name` 返回 400。实际选择及完整批准原文见 `decision.md`。

用户随后明确回复「批准设计并授权独立评审」。批准通过项目工作流发布于 `0b10678f8f320da086c4df75275b43ea6a041546`，程序返回 `approval: current`。

当前批准目标未变：设计版本 1；`spec.md` SHA256 为 `f79b4857b1edb0b8797d79b61801b7e5764554f51592132a676c25b9eb2f9971`；`requirement.md` SHA256 为 `3123f4c399576e7c3a6744af42127014c329541e1c4c32e44c63cd7e1506d656`。源码基线仍为 `openkruise/agents@2b06e110327f52da85053730a531ec3b3b0d6a46`，协议基线仍为 E2B `b52cd30c14bf7038ba5bfbd15456b1dabe567082`。没有把本地既有适配实现替换为新的源码基线。

## filesystem-only 恢复补证已完成

用户要求补齐 E1 后，已完成源码/接入链、静态发布/编排两路只读取证，并取得公开产品契约。内部材料只保留本机，不上传公开项目仓库。

主要公开来源：

https://help.aliyun.com/zh/cs/user-guide/clone-agent-sandbox-using-checkpoint

取得时间：2026-10-20T04:28:52Z。官方文档明确：

- 适用 ACS Agent Sandbox 算力，要求 `acs-virtual-node >= v2.17.0` 及相关组件。
- Checkpoint 支持 filesystem；显式接口/CR/扩展头手动覆盖本次保留内容，未指定时才继承 Sandbox 配置。
- `x-e2b-kruise-snapshot-keep-running` 默认 true；false 时源 Pod 变为 Succeeded。
- 返回的 snapshotID 可用于创建 clone，并恢复源文件；CR 示例使用 PodTemplate 注解 `checkpoint.alibabacloud.com/restore-from=<checkpointId>`。
- filesystem 之外的保留内容会导致 Checkpoint 创建失败，不能据此声称该后端支持完整内存快照。

本地实际适配链已核验：同一恢复 ID 经现有后处理接缝进入 PodTemplate，再传给首次创建的 Pod；首次 clone 不依赖另一条 resume 路径的 checkpoint-id flag。单次内容传递和源长期策略保持也已核对。这里记录脱敏结论，不公开内部源码、私有依赖及镜像坐标。

上述是服务契约和实际接入链证据，不是现场运行证明；未测量服务端具体 build、真实快照产物或特定源/clone 组合。不能把静态发布记录、样例及测试用例当作已部署或测试成功。

## 独立增量评审：pass，正式登记尚未完成

真实独立执行身份来自 Agent 工具返回：`ageneral-purpose-cef6072cf1d2a7f0`。完成通知 task `a94554b030741777c` 明确该执行已完成。评审者未参与设计编写；主会话没有以自评替代它。

脱敏报告：`/tmp/e2b-filesystem-source-evidence.Z89rSp/independent-review.md`。

已实际读取并核对 SHA256：`931ee5fb6b272915303532ebc7d1b0d441c5a14da10668d4761175e095660c5d`。

结论：**pass**，E1 在设计可实现性层面已充分补证；无已证实的阻塞设计问题。评审直接核验新增源码链与官方契约，复用旧独立报告中仍有效的列表、Pause、数组及权限边界覆盖。旧报告 SHA256 为 `a651d21b9b5bb6ff1ed9f3a681ecf185f48ef7274b0cccf61c75d0b4b7437a46`，其原结论 unable 未被伪造为旧 Pass。

关于源长期策略仍含 memory：评审认为请求级覆盖、按成功 Checkpoint ID 恢复及实际保持源策略的接入链，已足以支撑设计推论；这不是该组合的实测。关于 `memory:true`：合同要求请求 filesystem+memory，成功产物必须符合请求；结合 spec 第65行的真实后端失败约束，不是保证不支持内存的后端也成功，不能降级为 filesystem 后假报成功。没有修订设计或新增用户决策。

### 正式登记阻塞

以真实 reviewer-session 和原样报告执行 `begin design-review` 后，程序返回：

- `status: blocked`
- `code: owner_conflict`
- `message: external design review registration requires an owned developing item`

当前工作项是未占用的 aggregate，总项没有具体开发仓库/开发工作树。此登记操作没有 finish_command 或续行命令，已停止；未改 owner、未虚构 reviewer session、未用作者会话自评、未将状态手工改为 implementable。

独立质量结论、用户批准、正式状态持久化和实现准入是不同事实。当前已有真实批准与独立 pass 报告，尚无程序登记的正式评审通过状态。后续需使用符合当前工作项条件的独立评审登记路径，不重复补证或要求再次批准未变设计。

## 本机材料与后续边界

- 公开契约摘录：`/tmp/e2b-filesystem-source-evidence.Z89rSp/public-contract.md`。
- 内部源码证据：`/tmp/e2b-filesystem-source-evidence.Z89rSp/source-evidence.md`，SHA256 `5b5de634a7487dc6f5ac1ab135f12ff6c651a36a581eaf2e8e9ee4fe0a64254e`。
- 内部离线发布/编排证据：`/tmp/e2b-backend-evidence.QMMKZF`，SHA256 `e963a3edfa80a710c886df3dcd293b29e5f1da2eb89008920e9fe0fb7b02d2e7`。

原始内部材料留在本机；此项目仓库已核验为 PUBLIC，未上传内部报告。没有读取备用钉钉私有文档，已有公开来源直接覆盖本题。

本轮未修改源码或设计、未运行测试/服务/部署、未查询集群、未创建代码 worktree、未提交或推送源码、未创建 PR 或关闭 Issue。源码实现仍需满足项目注册、正式评审和 development-start 等门禁；源码提交、推送、外部发布及交付需各自真实授权与证据。
