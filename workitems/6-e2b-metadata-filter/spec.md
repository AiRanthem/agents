# Sandbox 控制器保留的 metadata 前缀

## 对外行为

共享黑名单将 `sandbox.agents.kruise.io/` 标记为保留前缀。斜杠是 Kubernetes 域名和键名的分隔符。规则覆盖当前指纹、旧版指纹和域下的其他键。

- **E2B 响应**。创建（含克隆）、连接、详情和列表共用 Sandbox 转换函数。转换时过滤注解和兼容读取的标签。普通注解继续覆盖同名普通标签。
- **E2B 创建请求**。普通 metadata 和 `label:` 扩展解析后的键都应用保留前缀校验，命中时返回 HTTP 400。
- **E2B 列表请求**。解析 `metadata` 参数和作为 metadata 筛选键的其他查询参数时，命中保留前缀返回 HTTP 400。
- **SandboxClaim**。从 `spec.annotations` 向 Pod 模板透传注解时，丢弃以该前缀开头的键。

## 作用范围和验收

已有的保留前缀规则、显式返回的 claim method、按条件返回的 Pod IP 和服务端生成的资源标识继续生效。新旧指纹常量继续指向原有注解键，响应转换保留原始 Sandbox 数据。

- 在同一个 Sandbox 上放入指纹注解、`sandbox.agents.kruise.io/custom` 标签和 `sandbox.agents.kruise.io.example/team` 注解。响应过滤前两项并返回第三项的原值，原始 Sandbox 仍含三项。
- 用 `sandbox.agents.kruise.io/custom` 创建 Sandbox 或筛选列表时，API 拒绝该键。SandboxClaim 的同名前缀注解在写入 Pod 模板前被过滤。相似域名 `sandbox.agents.kruise.io.example/` 仍可通过前缀检查。
