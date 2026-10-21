# 当前决策

## 生效的范围与来源

日期：2026-10-21。当前完整合同为 `spec.md` v4 与同步后的 `requirement.md`；两者字节哈希由程序按本次发布记录，本文不再抄录易失的旧哈希。

用户决策来源：

- 2026-10-20 会话 `bfa1920e-2676-4e3a-a8d9-70c449134a7b`：要求解决 #1083、#1084、#1085，选择“最小修复”并批准设计、授权独立评审。
- 2026-10-21 会话 `931f200a-68eb-4cb3-b377-5c39587f145a`：Pause 暂时禁止指定 memory（任何显式值均 400）；Snapshot 的 body `memory` 绑定到持久化内容（`true` → memory+filesystem，`false` → filesystem），持久化内容扩展头优先；请求体改用 models 形式解析。
- 2026-10-21 会话 `f6ea19b0-7a10-413d-894f-d6772422bf5d`：本版本支持快照 `name`；label 格式校验下沉 Infra；Infra 使用中性 `Alias` 概念；同名替换编排留在 API 层；列表按 name 过滤且保持 user 级可见性、多条取最新。
- 2026-10-21 会话 `e933eec0-f2b0-46e5-8b79-c2eef79d1b20`：要求同步设计文档并按计划实施；计划包含“同名快照改为创建成功后再删除旧快照”与“Pause 拒绝首个 JSON 对象之后的尾随内容”。
- 2026-10-21 同一会话后续：指出仅在创建前列举 Succeeded 无法阻止并发同名创建泄漏，要求改为创建成功后再列举并排除刚创建的对象；据此批准“先建、成功后按最新者收敛”的替换语义。

源码基线：`openkruise/agents@fd2bea7193d98c1d456fa6c43a2ae3e7e4f4fd48`；协议基线：E2B OpenAPI `b52cd30c14bf7038ba5bfbd15456b1dabe567082`。

## 当前行为

- #1083：`GET /v2/sandboxes` 的 `order`、`template`、`startedAfter` 为保留参数且不进入 metadata；默认降序、显式升序；`limit`、`nextToken`、`order`、`template`、`startedAfter` 空值或重复值 400；按领取时间（固定宽度 UTC 纳秒）加 Sandbox ID 稳定分页；筛选先于分页；共享分页器的其他调用者保持默认升序。
- #1084：Pause 请求体可为空或恰好一个 JSON 对象；任何显式 `memory` 返回 400；非法 JSON、非对象或尾随内容返回 400，且不触发暂停或写入；空 body、空白、`null`、`{}` 保持原流程；404/409/500 分类不变。
- #1085 memory：body `memory` 映射到本次持久化内容（`true` → memory+filesystem，`false` → filesystem，省略不修改）；持久化内容扩展头优先，多值合并去重；`names` 始终为数组。
- #1085 name：`name:null`/`""` 视为未命名；非空写入 Checkpoint label `agents.openkruise.io/checkpoint-alias`；格式由 `sandboxcr.CreateCheckpoint` 按 label value 规则校验并映射为 400；同名替换为“先建、成功后收敛别名”：按创建时间（固定宽度 UTC 纳秒）与名称选最新者，最新者删除其余对象，被取代者删除自身并返回最新者 ID；删除失败只记录日志，不回滚已成功的创建；`GET /snapshots?name=` user 级过滤并返回最新一条。
- 分层：E2B 协议语义与替换编排留在 API 层；存储格式约束在 Infra 入口校验并返回领域错误；API 层只做状态码映射。

## 替换顺序与列表语义

替换不在创建前读取或删除旧对象，因此任何创建失败、别名非法、等待超时都不会丢失既有快照。创建成功后按别名列举同 namespace 的 Succeeded checkpoint，按 Checkpoint 创建时间（`AsCheckpointInfo` 输出固定宽度 UTC 纳秒串，字典序等于时间序）与对象名组成确定的全序：

- 本次新建的是最新者：删除其余同别名对象，返回本次 `snapshotID`。
- 本次新建的不是最新者：删除本次新建对象，返回最新者的 `snapshotID`，避免把已被取代的对象 ID 当作有效结果。

这样并发同名创建收敛到唯一最新对象，而不是留下多条记录；顺序替换仍是新对象替换旧对象。仍存在的竞态是：较早的请求先返回 201 后，较新的请求仍可能删除它，已经返回的 `snapshotID` 可能随后失效，这是不保留旧 build 的固有取舍。带 name 的列表在创建期间返回旧快照，成功后返回最新快照；收敛完成前不带 name 的列表可能短暂看到两条。删除使用与请求解耦的 5 秒超时，失败只记录日志，由后续替换清理。

## 其他边界

项目文档发布不授权源码提交/推送、PR、Issue 关闭、部署、人工验收或交付完成。当前实现改动保留在工作树内，提交与外部发布需另行授权。
