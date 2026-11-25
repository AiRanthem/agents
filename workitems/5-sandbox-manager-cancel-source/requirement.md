# 区分 sandbox-manager 日志中的内部取消与 HTTP 请求取消

运维人员排查 `context canceled` 时，需要从 sandbox-manager 的日志判断是哪一方取消了当前操作。同一个请求可以同时涉及请求自己的等待和由 Manager 控制的后台工作，二者需要分别归因。

验收时，入站请求取消导致等待退出的日志可按 `cancelSource=http_request` 查询，Manager 主动取消操作的日志可按 `cancelSource=internal` 查询。已确认发生取消但无法判断来源时显式记录 `cancelSource=unknown`。同一失败到达已有的 API 错误日志时保留原归因。普通超时、业务失败和成功后的常规清理省略此字段。

本次交付为新工作项及已确认的[设计 v1](spec.md)。源码实现、独立评审和运行验证分别记录。
