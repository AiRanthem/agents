# E2B Sandbox metadata 过滤内部注解

控制器把沙箱模板的指纹保存在 Sandbox 注解中，用于判断配置能否原地更新。业务用户通过 E2B 查看沙箱时会看到这项实现细节。

E2B 返回的 Sandbox metadata 应隐藏所有以 `sandbox.agents.kruise.io/` 开头的键，包括 `hash-immutable-part`。创建、连接、查看详情和列举沙箱时采用一致规则。控制器继续从 Sandbox 读取原始指纹。
