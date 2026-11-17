# sandbox-api 启动时等待缺失的配置 Secret

## 问题与目标

用户反馈：sandbox-api 通过配置 Secret 启动时，如果 Secret 尚不存在，进程会直接 crash。希望启动阶段能够等待配置 Secret 就绪，尽量利用 startup probe 允许的启动窗口，避免因配置暂未创建而立即退出。

用户原文：

> 创建一个工作项。现在 sandbox-api 通过 config secret 启动的时候，如果 secret 不存在会直接 crash。我希望可以尽量等待直到 startup probe 超时（进程不感知）

## 已知范围与约束

- 范围为 sandbox-api 使用配置 Secret 的启动流程，处理启动时目标 Secret 暂不存在的情况。
- Secret 缺失时应保持等待，而非立即 crash；等待期间 Secret 就绪后，应继续正常启动。
- 等待窗口由 Kubernetes startup probe 从进程外部约束。进程不感知 startup probe 的超时，也不依赖读取或复制其超时配置来决定等待期限。
- 本次仅登记需求；具体等待机制、轮询或监听方式、错误分类及退出行为留待后续设计确认。

## 预期验收行为

1. 使用配置 Secret 启动且目标 Secret 暂不存在时，sandbox-api 不因该缺失立即退出，保持等待启动所需配置。
2. 在 startup probe 允许的窗口内创建有效 Secret 后，进程能够继续完成启动，无需因最初缺失而先退出重启。
3. Secret 持续缺失时，进程不因自行推算 startup probe 超时而结束等待；由 Kubernetes 按实际 startup probe 配置判定启动失败并处理容器。
4. Secret 已存在且有效时，保留正常启动行为。

以上是后续验证目标，当前没有源码或运行验证结论。具体探针配置、验证环境及非缺失错误的处理边界尚待确认。

## 交付与当前阶段

本次交付为工作项需求、上下文和状态记录，并提交、推送项目管理分支。当前仅完成需求登记，未开展设计、实现或评审。源码 PR、部署及现场验收等后续交付要求尚未指定。
