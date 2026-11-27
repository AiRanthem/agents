# 源码依据

2026-11-27 核对开源 `upstream/master` 提交 `986ae83e1f3737e745255db6d6ae8d558167560a`。

- `api/v1alpha1/annotations.go` 定义新旧指纹常量。`pkg/controller/sandbox/sandbox_controller.go` 在 Sandbox 上补写当前指纹，`pkg/controller/sandbox/core/common_inplace_update_handler.go` 比较它以决定是否允许原地更新。
- `pkg/servers/e2b/sandbox.go` 的 `convertToE2BSandbox` 先读标签，再读注解。现有校验按前缀过滤，两个指纹均在已覆盖的前缀之外。
- `pkg/servers/e2b/{create,list,pause_resume,services}.go` 共用该转换函数。`pkg/utils/annotations/blacklist.go` 定义的前缀还影响输入或透传，直接扩展它会改变响应以外的行为。

用户已选定在响应侧按域名前缀过滤，见[用户决定](decision.md)，并在确认设计 v2 后要求“落地修改”。

## 实现与验证

Codex 从本次刷新并核验的上游提交 `986ae83e1f3737e745255db6d6ae8d558167560a` 建立分支 `fix/e2b-metadata-filter-261127`，工作树为 `worktrees/6-e2b-metadata-filter`。源码和回归测试位于 `pkg/servers/e2b/sandbox.go` 和 `pkg/servers/e2b/sandbox_test.go`。两项变更保存在本地工作树，`git diff --binary HEAD | shasum -a 256` 为 `81a4b78efa97288256a670420937915c5cc8423ce84223fcde3ca1439fce65b9`。

新增回归测试在基线上因指纹注解和同域标签出现在响应中而失败。修改后，`go test ./pkg/servers/e2b -run '^TestConvertToE2BSandbox' -count=1 -v` 的五组测试全部通过，覆盖前缀边界、原始对象保留、同名普通注解优先和显式返回字段。`git diff --check` 通过。独立评审、人工验收和部署均待开展。
