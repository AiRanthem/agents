# 当前上下文

用户最新已确定运维直接配置 Kubernetes、不调整 OpenClaw、关闭入口只拒绝新事件。已接收任务继续原有有限唤醒/投递，不因入口关闭而取消。Gateway 验证信息需外置并由运维维护一致性，不要求 OpenClaw 改为共享 Secret 注入。企业范围、修改绑定和轮换密钥仍处于背景解释阶段；见父项配置说明，未将建议登记为批准或新的独立通过。

2026-11-04 按用户“等待最多60秒”和“拆成两个子任务，编排变更依赖代码交付”建立。完整背景与剩余契约见 [父项需求](../2-feishu-wake-openclaw/requirement.md)、[父项上下文](../2-feishu-wake-openclaw/context.md)；固定版本源码与实际 ACK 编排依据见 [下线核验](../../evidence/ack-gateway-webhook-shutdown.md)。

本项承担整个 Webhook 能力的 Gateway 代码及内存任务排空，不只新增一个没有任务归属的停机接口。下线顺序和 60 秒业务上限已确认；父项其余 Webhook 契约仍需细化，没有完整 spec 可继承。

2026-11-04，独立 `/root/webhook_design_reviewer` 审查提交 `27e8ae89472e3844104ec75a18182091e3088c12`，本项结论为 **Unable to conclude**。必要缺口为 G1（应用交付和有效确认协议）及 G2（接入配置、授权目标身份和开关变化语义）。正常下线子契约未发现阻塞缺陷，但不能覆盖整个接收/交付链路。原始 [报告](../2-feishu-wake-openclaw/records/design-review-20261104.md) 单独评估本项，不沿用父项结论替代子项审查；未修改候选或记录 implementable。

源码入口为 `/Users/sophon/Workspace/OKAWorkspace/agents`，实施前读取原始 AGENTS.md 及内部/外部代码隔离规则；不能使用工作项 1 的未提交代码作为已交付能力。此前核验的 Gateway 镜像源码 `e55d70c7fc7d603e8a585918919788edd0374e31` 仅说明现有行为，不是已选实施基线。

用户随后明确本项为独立的标准飞书 IM Webhook，并提出 E2B 数据面 URL。核验确认完整 URL 可复用 Host 寻址；现有 token/JWT 认证与飞书来源验证仍需在专用入口衔接，任务对象身份也不能仅依赖域名。应用接收确认收敛为标准 HTTP 200，不要求 OpenClaw 私有 durable 标记。详见 [入口核验](../../evidence/feishu-e2b-webhook-entry.md)。

按用户要求，原独立 reviewer 再次审查提交 `5061001783fd3d9fd431c3e820f6862f7a5e4eb6`，确认上述协议与寻址部分闭合，仍因 G1-R（ACK 后失败/响应丢失的有限处置）和 G2-R（入口配置/授权及启停变化）而 **Unable to conclude**。报告见 [第二轮复审](../2-feishu-wake-openclaw/records/design-review-20261104-r2.md)。复用原正常下线覆盖，现有适配器窄测试通过；不等于新功能已实施。原报告及其目标提交保持不变，未记 implementable。

尚无分支、工作树、实现、人工验收、源码合并或镜像产物。子任务 22 依赖本项真实代码交付，编排启用还须核验镜像与接口匹配。

第二轮之后用户确定沿用当前默认唤醒等待，恢复后指数退避最多五次重试，失败日志后放弃。需求已同步首次加五次重试、请求与总期限有界及下线截止优先。实际 ACK Chart 默认等待 600 秒，区别于二进制缺省 60 秒；具体安装覆盖值未检查。飞书配置所需输入和待选择的配置/撤销方案见 [配置说明](../../evidence/feishu-webhook-config-and-retry.md)。该修订尚未独立复核，原审查绑定保持不变。
