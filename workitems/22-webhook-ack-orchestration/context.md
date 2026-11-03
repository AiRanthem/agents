# 当前上下文

2026-11-04 按用户明确要求建立：编排子任务依赖 `21-webhook-gateway-code` 的代码交付。当前前置尚未实现或交付，镜像也未选定，故本项尚未开始实际编排变更。

父项的 [需求](../2-feishu-wake-openclaw/requirement.md) 与 [下线核验](../../evidence/ack-gateway-webhook-shutdown.md) 保存共享契约和证据。现有 ack-components 主分支包的默认 grace 为 90 秒、Envoy drain 为 30 秒；增加最多 60 秒的业务排空后，需要将目标 grace 调整到 120 秒。120 秒是设计推导，不是已修改或部署的事实。

仓库入口为 `/Users/sophon/Workspace/OKAWorkspace/ack-components`。此前核对的 v0.6.14-release.1、v0.6.14-release.2 和 v0.6.15-release.1 仅提供现状证据，不代表用户已指定本项落入其中某一发布分支。实施前读取原始主工作区指令并确定目标组件版本。

2026-11-04，独立 `/root/webhook_design_reviewer` 审查提交 `27e8ae89472e3844104ec75a18182091e3088c12`，本项当前编排语义契约 **Independent review passed**。Reviewer 单独检查本项的职责、顺序、预算、失败行为和前置条件，没有以父项结论代替；原始 [报告](../2-feishu-wake-openclaw/records/design-review-20261104.md) 已保存。接口绑定值由前置交付提供；若其改变绝对截止、幂等、结果区分或本地访问等共享语义，需要复核受影响范围。

随后用户要求再次独立复审。原 reviewer 检查提交 `5061001783fd3d9fd431c3e820f6862f7a5e4eb6` 的标准 HTTP 200 确认对排空的影响，确认未改变本项顺序、预算及失败语义，继续 **Independent review passed**。本项 requirement/decision 与前次相同，实际 ACK 模板/配置 blob 未变，保留原 Helm 渲染覆盖，未重复渲染。新报告见 [第二轮复审](../2-feishu-wake-openclaw/records/design-review-20261104-r2.md)。

当前没有独立 spec 文件、工作树、编排差异或集成验证结果，未登记 implementable。设计契约通过不代表前置已交付；实际变更前检查代码合并交付证据，启用 hook 前核对镜像与本地接口身份。实际环境验证和组件部署分别遵循后续授权。
