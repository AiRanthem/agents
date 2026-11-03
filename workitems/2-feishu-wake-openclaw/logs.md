# 当前知识

协议研究见 `evidence/feishu-event-transports.md`；链路、Pause 行为、所需能力和独立性分析见 `evidence/im-wakeup-paths-and-capabilities.md`，均未执行真实环境端到端验证。

2026-11-03 按用户要求完成需求层拆分，随后用户启动 Webhook 设计。当前状态为 designing，设计版本仍为 0，完整契约尚未收敛；无正式设计批准、独立审查或业务实施结果。

已保存单接入单 Sandbox，以及开关开启时允许手动 Pause 后自动唤醒的决定。用户进一步明确采用 Gateway 内存接收，接受 Gateway 退出丢失事件，已替换此前持久化方向。

本轮核验实际 ack-components 编排、对应 Gateway 镜像源码及 Envoy 1.37.3 drain 语义，并用组件 configs/default.yaml 叠加 Chart 渲染 Gateway Deployment。结论及原始定位见 evidence/ack-gateway-webhook-shutdown.md（相对项目根）；未修改业务源码/编排，也未执行线上终止验证。

用户随后接受正常下线的停收、排空、退出顺序。已补充 preStop 先排空业务再 drain Envoy 的方案，并检查接收与停收并发、stream 生命周期、readiness 与内部路由依赖、重复 hook 和终止预算。此前已刷新 agents 与 ack-components 主检出，复核固定镜像源码和 Kubernetes hook 契约。

2026-11-04，用户确认方案，指定业务排空最多等待 60 秒，并明确要求两个子任务及“编排依赖代码交付”。已建立 `21-webhook-gateway-code` 和 `22-webhook-ack-orchestration`，同步汇总关系与依赖。按新等待上限重算目标总 grace 为 120 秒；既有 90 秒编排事实保留在证据中。本轮仅维护项目记录，未实施代码或编排，也未重新执行 Helm 渲染或运行验证。

