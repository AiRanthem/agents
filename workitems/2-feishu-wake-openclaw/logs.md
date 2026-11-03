# 当前知识

协议研究见 `evidence/feishu-event-transports.md`；链路、Pause 行为、所需能力和独立性分析见 `evidence/im-wakeup-paths-and-capabilities.md`，均未执行真实环境端到端验证。

2026-11-03 按用户要求完成需求层拆分，随后用户启动 Webhook 设计。当前状态为 designing，设计版本仍为 0，完整契约尚未收敛；无正式设计批准、独立审查或业务实施结果。

已保存单接入单 Sandbox，以及开关开启时允许手动 Pause 后自动唤醒的决定。用户进一步明确采用 Gateway 内存接收，接受 Gateway 退出丢失事件，已替换此前持久化方向。

本轮核验实际 ack-components 编排、对应 Gateway 镜像源码及 Envoy 1.37.3 drain 语义，并用组件 configs/default.yaml 叠加 Chart 渲染 Gateway Deployment。结论及原始定位见 evidence/ack-gateway-webhook-shutdown.md（相对项目根）；未修改业务源码/编排，也未执行线上终止验证。

