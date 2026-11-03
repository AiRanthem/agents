# 当前知识

协议研究见 `evidence/feishu-event-transports.md`；链路、Pause 行为、所需能力和独立性分析见 `evidence/im-wakeup-paths-and-capabilities.md`，均未执行真实环境端到端验证。

2026-11-03 按用户要求完成需求层拆分；随后用户启动 Webhook 设计，并在了解回复链路后确认“那可以做可靠接收”。当前状态为 designing，设计版本仍为 0，完整契约尚未收敛；无正式设计批准、独立审查或业务实施结果。

已保存可靠接收的用户决定，并同步需求、上下文及项目约束。用户随后回复“都按照推荐来”，进一步确认单接入单 Sandbox，以及开关开启时允许手动 Pause 后自动唤醒；已同步需求和决策。OpenClaw 固定源码证据与剩余问题见 context.md；未执行运行验证。

