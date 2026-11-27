# E2B Sandbox metadata 过滤内部注解

控制器把沙箱模板的指纹保存在 Sandbox 注解中，用于判断配置能否原地更新。业务用户通过 E2B 查看沙箱时会看到这项实现细节。

将 `sandbox.agents.kruise.io/` 保留给 Sandbox 控制器。E2B 创建、连接、查看详情和列举沙箱时，响应 metadata 隐藏该前缀的键，包括 `hash-immutable-part`。E2B 拒绝创建请求中的同前缀 metadata 和 `label:` 扩展键，以及列表请求中的同前缀 metadata 筛选条件。SandboxClaim 向 Pod 模板透传用户注解时跳过该前缀。控制器继续从 Sandbox 读取原始指纹。
