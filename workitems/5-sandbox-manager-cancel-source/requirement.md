# 在 sandbox-manager 日志和 API 错误响应中区分内部取消与 HTTP 请求取消

运维人员排查 `context canceled` 时，需要从 sandbox-manager 的日志判断是哪一方取消了当前操作。同一个请求可以同时涉及请求自己的等待和由 Manager 控制的后台工作，二者需要分别归因。

验收时，入站请求取消导致等待退出的日志可按 `cancelSource=http_request` 查询，Manager 主动取消操作的日志可按 `cancelSource=internal` 查询。已确认发生取消但无法判断来源时显式记录 `cancelSource=unknown`。同一失败到达已有的 API 错误日志时保留原归因。普通超时、业务失败和成功后的常规清理省略此字段。

如果取消导致 API 返回错误，调用方也需要从 JSON 响应的可选字段 `cancelSource` 取得同一来源，包括转换为通用错误消息的情况。保留既有状态码和错误消息，成功、超时和普通业务错误省略该字段。详见[设计 v2](spec.md)。
