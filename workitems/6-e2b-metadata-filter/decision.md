# 过滤范围

用户在确认 E2B 响应过滤范围时决定：“直接过滤前缀 sandbox.agents.kruise.io 吧”。按 Kubernetes 键的域名边界匹配 `sandbox.agents.kruise.io/`，覆盖从注解和兼容标签汇入响应 metadata 的键。

2026-11-27 创建 PR 前，用户确认“按当前暂存版本提交，并同步更新设计记录”。设计 v3 采用暂存版本的共享黑名单，也将该前缀用于 E2B 创建校验、E2B 列表筛选校验和 SandboxClaim 向 Pod 模板透传注解。
