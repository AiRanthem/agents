# 源码依据

2026-11-27 核对开源 `upstream/master` 提交 `986ae83e1f3737e745255db6d6ae8d558167560a`。

- `api/v1alpha1/annotations.go` 定义保留前缀与新旧指纹常量。`pkg/controller/sandbox/sandbox_controller.go` 在 Sandbox 上补写当前指纹，`pkg/controller/sandbox/core/common_inplace_update_handler.go` 比较它以决定是否允许原地更新。
- `pkg/servers/e2b/sandbox.go` 的 `convertToE2BSandbox` 先读标签，再读注解，对两类键应用 `pkg/utils/annotations/blacklist.go` 的共享黑名单。`pkg/servers/e2b/{create,list,pause_resume,services}.go` 共用该转换函数。
- E2B 创建校验、`label:` 扩展解析、列表筛选解析及 `pkg/controller/sandboxclaim/core/common_control.go` 的注解透传也复用该黑名单。详见[设计 v3](spec.md)。

用户先确认设计 v2 并要求落地修改，之后确认以共享黑名单实现的暂存版本创建普通 PR。详见[用户决定](decision.md)。

## 实现与验证

Codex 从刷新并核验的上游提交 `986ae83e1f3737e745255db6d6ae8d558167560a` 建立分支 `fix/e2b-metadata-filter-261127`，工作树为 `worktrees/6-e2b-metadata-filter`。创建 PR 前再次刷新上游，基线仍是该提交。按用户确认的暂存版本提交 6 个开源文件，提交为 `6f8a548b0c294381f69c93ab624b14e1ef0fea02`，相对上游基线的二进制 diff SHA-256 为 `0ff96998f61c40e72e15fdeac50d937d215b5043397d72d2775b2f15664ef5c3`。

初版回归测试在基线上因指纹注解和同域标签出现在响应中而失败。本次提交通过 E2B 转换、创建请求解析及共享黑名单的定向测试。`make generate manifests` 完成，产物与暂存版本一致。`git diff --check` 通过。

E2B 全包测试发现 `TestCreateSandbox/fail_with_forbidden_metadata_key` 的断言写死了旧前缀列表。后续提交 `3141a6afdcb03b08fd88c025fa1c8d9a3f42c83a` 让该测试校验 HTTP 400 和被拒绝的键，前缀覆盖由创建解析测试验证。复跑 `go test ./pkg/servers/e2b ./pkg/servers/e2b/models ./pkg/utils/annotations ./pkg/controller/sandboxclaim/core -count=1`，四个包全部通过。PR 完整差异相对上游基线的 SHA-256 为 `250c6f474903f35766f1ff85fdeb35ccde6e3c8912a844ea22d225fb73aba066`。

## PR

2026-11-27 已推送 `AiRanthem/agents:fix/e2b-metadata-filter-261127` 并创建普通 PR。回读确认目标为 `openkruise/agents:master`，PR HEAD 与远端分支和本地提交一致，状态为 OPEN。CI 仍在运行，独立评审和人工验收尚未开展。[OpenKruise Agents PR #1291](https://github.com/openkruise/agents/pull/1291)
