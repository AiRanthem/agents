# 当前上下文

2026-11-04 按用户明确要求建立：编排子任务依赖 `21-webhook-gateway-code` 的代码交付。当前前置尚未实现或交付，镜像也未选定，故本项尚未开始实际编排变更。

父项的 [需求](../2-feishu-wake-openclaw/requirement.md) 与 [下线核验](../../evidence/ack-gateway-webhook-shutdown.md) 保存共享契约和证据。现有 ack-components 主分支包的默认 grace 为 90 秒、Envoy drain 为 30 秒；增加最多 60 秒的业务排空后，需要将目标 grace 调整到 120 秒。120 秒是设计推导，不是已修改或部署的事实。

仓库入口为 `/Users/sophon/Workspace/OKAWorkspace/ack-components`。此前核对的 v0.6.14-release.1、v0.6.14-release.2 和 v0.6.15-release.1 仅提供现状证据，不代表用户已指定本项落入其中某一发布分支。实施前读取原始主工作区指令并确定目标组件版本。

当前只登记契约与依赖，没有正式 spec、独立审查、工作树、编排差异或集成验证结果。实际变更前检查代码合并交付证据；启用 hook 前核对镜像与本地接口身份。实际环境验证和组件部署分别遵循后续授权。
