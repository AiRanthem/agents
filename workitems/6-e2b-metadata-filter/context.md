# 源码依据

2026-11-27 核对开源 `upstream/master` 提交 `986ae83e1f3737e745255db6d6ae8d558167560a`。

- `api/v1alpha1/annotations.go` 定义新旧指纹常量。`pkg/controller/sandbox/sandbox_controller.go` 在 Sandbox 上补写当前指纹，`pkg/controller/sandbox/core/common_inplace_update_handler.go` 比较它以决定是否允许原地更新。
- `pkg/servers/e2b/sandbox.go` 的 `convertToE2BSandbox` 先读标签，再读注解。现有校验按前缀过滤，两个指纹均在已覆盖的前缀之外。
- `pkg/servers/e2b/{create,list,pause_resume,services}.go` 共用该转换函数。`pkg/utils/annotations/blacklist.go` 定义的前缀还影响输入或透传，直接扩展它会改变响应以外的行为。

用户已选定在响应侧按域名前缀过滤，见[用户决定](decision.md)。设计 v2 已据此更新，独立评审与源码实现待开展。
