# 当前决策

## 生效的范围与来源

日期：2026-10-21。当前完整合同为 `spec.md` v3 与同步后的 `requirement.md`；两者字节哈希由程序按本次发布记录，本文不再抄录易失的旧哈希。

用户决策来源：

- 2026-10-20 会话 `bfa1920e-2676-4e3a-a8d9-70c449134a7b`：要求解决 #1083、#1084、#1085，选择“最小修复”并批准设计、授权独立评审。
- 2026-10-21 会话 `931f200a-68eb-4cb3-b377-5c39587f145a`：Pause 暂时禁止指定 memory（任何显式值均 400）；Snapshot 的 body `memory` 绑定到持久化内容（`true` → memory+filesystem，`false` → filesystem），持久化内容扩展头优先；请求体改用 models 形式解析。
- 2026-10-21 会话 `f6ea19b0-7a10-413d-894f-d6772422bf5d`：本版本支持快照 `name`；label 格式校验下沉 Infra；Infra 使用中性 `Alias` 概念；同名替换编排留在 API 层；列表按 name 过滤且保持 user 级可见性、多条取最新。
- 2026-10-21 会话 `e933eec0-f2b0-46e5-8b79-c2eef79d1b20`：要求同步设计文档并按计划实施；计划包含“同名快照改为创建成功后再删除旧快照”与“Pause 拒绝首个 JSON 对象之后的尾随内容”。

源码基线：`openkruise/agents@fd2bea7193d98c1d456fa6c43a2ae3e7e4f4fd48`；协议基线：E2B OpenAPI `b52cd30c14bf7038ba5bfbd15456b1dabe567082`。

## 当前行为

- #1083：`GET /v2/sandboxes` 的 `order`、`template`、`startedAfter` 为保留参数且不进入 metadata；默认降序、显式升序；`limit`、`nextToken`、`order`、`template`、`startedAfter` 空值或重复值 400；按领取时间（固定宽度 UTC 纳秒）加 Sandbox ID 稳定分页；筛选先于分页；共享分页器的其他调用者保持默认升序。
- #1084：Pause 请求体可为空或恰好一个 JSON 对象；任何显式 `memory` 返回 400；非法 JSON、非对象或尾随内容返回 400，且不触发暂停或写入；空 body、空白、`null`、`{}` 保持原流程；404/409/500 分类不变。
- #1085 memory：body `memory` 映射到本次持久化内容（`true` → memory+filesystem，`false` → filesystem，省略不修改）；持久化内容扩展头优先，多值合并去重；`names` 始终为数组。
- #1085 name：`name:null`/`""` 视为未命名；非空写入 Checkpoint label `agents.openkruise.io/checkpoint-alias`；格式由 `sandboxcr.CreateCheckpoint` 按 label value 规则校验并映射为 400；同名替换顺序为“先查、再建、成功后才删”，删除失败只记录日志，不回滚已成功的创建；`GET /snapshots?name=` user 级过滤并返回最新一条。
- 分层：E2B 协议语义与替换编排留在 API 层；存储格式约束在 Infra 入口校验并返回领域错误；API 层只做状态码映射。

## 替换顺序与列表语义

旧快照只在新快照创建成功之后删除，因此任何创建失败、别名非法、等待超时都不会丢失既有快照。替换窗口内允许同别名出现两条 Succeeded 对象：不带 name 的列表可能短暂同时返回它们；带 name 的列表在创建期间返回旧快照，创建成功后返回新快照（按创建时间升序取末元素）。创建时间为秒精度，同一秒内的新旧对象次序由名称决定，但窗口结束后只剩新对象。并发同名创建不加锁，残留对象由后续同名替换清理。

## 其他边界

项目文档发布不授权源码提交/推送、PR、Issue 关闭、部署、人工验收或交付完成。当前实现改动保留在工作树内，提交与外部发布需另行授权。
