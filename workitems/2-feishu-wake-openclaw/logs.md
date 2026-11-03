# 当前知识

2026-11-04，用户要求“再次独立复审”。复用原独立 reviewer 对 `5061001` 进行增量评估，原报告保存为 `records/design-review-20261104-r2.md`，哈希与交回产物一致，13 个输入 blob 已核对。标准协议/载荷与 E2B 寻址已闭合；父项及 21 因 G1-R/G2-R 仍 Unable to conclude，22 继续通过。原下线/编排覆盖保留，适配器窄测试通过；本轮仅登记复审，未修改业务契约或源码、编排，也未执行真实集成验证。

2026-11-04，按用户澄清将本项收敛为标准飞书 IM Webhook。读取官方事件订阅协议，复用独立源码调查并直接核对关键 Host/认证/UID 代码，确认 E2B URL 能解决目标寻址，不能代替来源验证与任务身份约束；标准 HTTP 200 作为接收确认。依据见 `evidence/feishu-e2b-webhook-entry.md`。更新需求与待决范围，原始审查报告保持不变。未修改源码/编排、运行新功能或开展增量独立审查。

协议研究见 `evidence/feishu-event-transports.md`；链路、Pause 行为、所需能力和独立性分析见 `evidence/im-wakeup-paths-and-capabilities.md`，均未执行真实环境端到端验证。

2026-11-03 按用户要求完成需求层拆分，随后用户启动 Webhook 设计。当前状态为 designing，设计版本仍为 0，完整契约尚未收敛；无完整正式设计批准或业务实施结果，独立审查的实际结论记录在下文。

已保存单接入单 Sandbox，以及开关开启时允许手动 Pause 后自动唤醒的决定。用户进一步明确采用 Gateway 内存接收，接受 Gateway 退出丢失事件，已替换此前持久化方向。

本轮核验实际 ack-components 编排、对应 Gateway 镜像源码及 Envoy 1.37.3 drain 语义，并用组件 configs/default.yaml 叠加 Chart 渲染 Gateway Deployment。结论及原始定位见 evidence/ack-gateway-webhook-shutdown.md（相对项目根）；未修改业务源码/编排，也未执行线上终止验证。

用户随后接受正常下线的停收、排空、退出顺序。已补充 preStop 先排空业务再 drain Envoy 的方案，并检查接收与停收并发、stream 生命周期、readiness 与内部路由依赖、重复 hook 和终止预算。此前已刷新 agents 与 ack-components 主检出，复核固定镜像源码和 Kubernetes hook 契约。

2026-11-04，用户确认方案，指定业务排空最多等待 60 秒，并明确要求两个子任务及“编排依赖代码交付”。已建立 `21-webhook-gateway-code` 和 `22-webhook-ack-orchestration`，同步汇总关系与依赖。按新等待上限重算目标总 grace 为 120 秒；既有 90 秒编排事实保留在证据中。本轮仅维护项目记录，未实施代码或编排，也未重新执行 Helm 渲染或运行验证。

随后按用户要求，由独立 `/root/webhook_design_reviewer` 审查提交 `27e8ae8`。父项及 21 为 Unable to conclude（G1、G2 必要契约未决），22 编排契约通过。原始报告和身份记录见 `records/design-review-20261104.md` / `.yaml`，报告复制后哈希与 reviewer 产物一致。Reviewer 本轮独立重新渲染现有 ACK 包并检查源码/官方资料，未运行新功能或修改候选。项目记录登记不改变业务契约，也不建立交付。

