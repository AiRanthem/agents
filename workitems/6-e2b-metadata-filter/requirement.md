# E2B Sandbox metadata 过滤内部注解

控制器把沙箱模板的指纹保存在 Sandbox 注解中，用于判断配置能否原地更新。业务用户通过 E2B 查看沙箱时会看到这项实现细节。

E2B 返回的 Sandbox metadata 应隐藏 `sandbox.agents.kruise.io/hash-immutable-part`，并支持集中追加需要隐藏的内部键。创建、连接、查看详情和列举沙箱时采用一致规则。业务 metadata 继续按原值返回，控制器继续从 Sandbox 读取原始指纹。
