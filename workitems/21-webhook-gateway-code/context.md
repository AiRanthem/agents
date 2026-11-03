# 当前上下文

2026-11-04 按用户“等待最多60秒”和“拆成两个子任务，编排变更依赖代码交付”建立。完整背景与剩余契约见 [父项需求](../2-feishu-wake-openclaw/requirement.md)、[父项上下文](../2-feishu-wake-openclaw/context.md)；固定版本源码与实际 ACK 编排依据见 [下线核验](../../evidence/ack-gateway-webhook-shutdown.md)。

本项承担整个 Webhook 能力的 Gateway 代码及内存任务排空，不只新增一个没有任务归属的停机接口。下线顺序和 60 秒业务上限已确认；父项其余 Webhook 契约仍需细化，没有完整 spec 可继承。

2026-11-04，独立 `/root/webhook_design_reviewer` 审查提交 `27e8ae89472e3844104ec75a18182091e3088c12`，本项结论为 **Unable to conclude**。必要缺口为 G1（应用交付和有效确认协议）及 G2（接入配置、授权目标身份和开关变化语义）。正常下线子契约未发现阻塞缺陷，但不能覆盖整个接收/交付链路。原始 [报告](../2-feishu-wake-openclaw/records/design-review-20261104.md) 单独评估本项，不沿用父项结论替代子项审查；未修改候选或记录 implementable。

源码入口为 `/Users/sophon/Workspace/OKAWorkspace/agents`，实施前读取原始 AGENTS.md 及内部/外部代码隔离规则；不能使用工作项 1 的未提交代码作为已交付能力。此前核验的 Gateway 镜像源码 `e55d70c7fc7d603e8a585918919788edd0374e31` 仅说明现有行为，不是已选实施基线。

用户随后明确本项为独立的标准飞书 IM Webhook，并提出 E2B 数据面 URL。核验确认完整 URL 可复用 Host 寻址；现有 token/JWT 认证与飞书来源验证仍需在专用入口衔接，任务对象身份也不能仅依赖域名。应用接收确认收敛为标准 HTTP 200，不要求 OpenClaw 私有 durable 标记。详见 [入口核验](../../evidence/feishu-e2b-webhook-entry.md)。本轮变化尚未增量独立复核，原报告及其目标提交保持不变。

尚无分支、工作树、实现、人工验收、源码合并或镜像产物。子任务 22 依赖本项真实代码交付，编排启用还须核验镜像与接口匹配。
