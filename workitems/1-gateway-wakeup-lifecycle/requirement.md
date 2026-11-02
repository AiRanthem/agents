# 优化 sandbox-gateway 流量自动唤醒后的 shutdownTime/pauseTime 调整

## 目标

优化 sandbox-gateway 流量自动唤醒时对 `shutdownTime` / `pauseTime` 的处理。

用户原始需求：

> 当前的 sandbox-gateway 支持流量自动唤醒，但是没有调整 shutdownTime/pauseTime。需要优化这个问题。

## 范围

- 关注 sandbox-gateway 流量自动唤醒流程与 `shutdownTime` / `pauseTime` 调整之间的关系。
- 具体调整规则、触发条件、涉及组件及兼容性要求待后续确认。

## 验收条件

待确认：自动唤醒后两个时间字段的预期值、适用场景及验证方式。

## 交付结果

待确认具体代码交付和文档要求。本次仅登记需求，尚未进入设计或实现。
