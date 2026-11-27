# E2B Sandbox 响应中过滤内部注解

## 对外行为

E2B 将 Sandbox 转成响应对象时，跳过以 `sandbox.agents.kruise.io/` 开头的所有键。斜杠是 Kubernetes 域名和键名的分隔符。规则覆盖当前指纹、旧版指纹、该域下的业务自定义键和今后新增的键。

创建（含克隆）、连接、详情和列表共用此规则。E2B 为兼容旧数据还会读取标签，从标签或注解进入响应的键都应用同一规则。普通注解继续覆盖同名普通标签。

## 作用范围和验收

仅在组装响应 metadata 时应用该前缀规则。已有的保留前缀规则、显式返回的 claim method、按条件返回的 Pod IP 和服务端生成的资源标识继续生效。控制器读写、claim 注解透传、创建请求校验以及列表查询条件沿用各自的现有规则。

在同一个 Sandbox 上放入指纹注解、`sandbox.agents.kruise.io/custom` 标签和 `sandbox.agents.kruise.io.example/team` 注解。响应中前两项应消失，第三项按原值返回，原始 Sandbox 仍含三项。
