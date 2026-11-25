# 设计依据

设计核对的 OpenKruise Agents 上游 master 提交为 `3fc1216cea513df40b68f77171b042dc1ef7e8e3`。以下为源码证据。

- 令牌签发通过 `WithoutCancel` 保留请求的上下文值，并单独接入 Manager 停机取消；各调用方独立等待共享结果。仓库已有用例覆盖一个等待者取消后另一个等待者仍拿到令牌。[等待分支](https://github.com/openkruise/agents/blob/3fc1216cea513df40b68f77171b042dc1ef7e8e3/pkg/sandbox-manager/traffic_token.go#L77-L135) · [签发生命周期](https://github.com/openkruise/agents/blob/3fc1216cea513df40b68f77171b042dc1ef7e8e3/pkg/sandbox-manager/traffic_token.go#L205-L221) · [既有用例](https://github.com/openkruise/agents/blob/3fc1216cea513df40b68f77171b042dc1ef7e8e3/pkg/sandbox-manager/traffic_token_test.go#L259-L308)
- 令牌 API 将不可用错误映射为统一响应，Web 框架记录转换后的 `ApiError`。响应文字不足以恢复原始来源。[API 映射](https://github.com/openkruise/agents/blob/3fc1216cea513df40b68f77171b042dc1ef7e8e3/pkg/servers/e2b/traffic_token.go#L54-L72) · [请求结果日志](https://github.com/openkruise/agents/blob/3fc1216cea513df40b68f77171b042dc1ef7e8e3/pkg/servers/web/framework.go#L159-L171)
- Pause/Resume 的等待错误分支检查当前 `ctx.Err()` 并使用客户端取消文案。Claim 则有自己的期限，等 worker 时的错误文案包含 “context canceled”。归因需要区分退出原因和记录时的状态。[Pause](https://github.com/openkruise/agents/blob/3fc1216cea513df40b68f77171b042dc1ef7e8e3/pkg/sandbox-manager/infra/sandboxcr/sandbox.go#L585-L596) · [Resume](https://github.com/openkruise/agents/blob/3fc1216cea513df40b68f77171b042dc1ef7e8e3/pkg/sandbox-manager/infra/sandboxcr/sandbox.go#L663-L675) · [Claim 期限](https://github.com/openkruise/agents/blob/3fc1216cea513df40b68f77171b042dc1ef7e8e3/pkg/sandbox-manager/infra/sandboxcr/infra.go#L149-L165) · [Claim 等待](https://github.com/openkruise/agents/blob/3fc1216cea513df40b68f77171b042dc1ef7e8e3/pkg/sandbox-manager/infra/sandboxcr/claim.go#L374-L381)

设计作者为 Codex。已依据源码核对上述场景，独立设计评审、源码实现与运行验证尚未进行。
