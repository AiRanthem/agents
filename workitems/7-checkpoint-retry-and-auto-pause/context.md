# Checkpoint 失败排查记录

## 用户核验的现场时序

以下以快照请求到达为零点，时间取整到秒。现场依据为用户核对的 Pod 审计与控制器日志。

| 相对时间 | 事件 |
| --- | --- |
| −22 秒 / −6 秒 | Sandbox 唤醒并重建 Pod，随后转为 Running。 |
| 0 秒 | sandbox-manager 创建 filesystem Checkpoint，使用生成名称并以 `spec.podName` 指向源 Pod。请求设置 `keepRunning=true`、TTL 2160 小时。控制器在同一秒内两次调用 Pending 处理，后端均返回 403 并指出实例状态不允许该操作。 |
| +4 分 54 秒 | 到达自动休眠时间。 |
| +22 分 03 秒 / +22 分 04 秒 | 释放实例并删除 Pod，随后虚拟节点以零宽限期删除 Pod 对象。 |
| +26 分 45 秒 | 这是两次 403 后该对象首次再次进入调谐。此时 Pod 已删除，控制器写入 Failed、完成时间和 `Pod Not Found`。只查询完成时间附近会错过早先的创建和删除审计。 |

同期 4.6 秒的日志样本有 100 次调谐，横跨至少三个命名空间，多数报告终态处理返回 `not implemented`。另一个终态对象两次同样报错也相隔 26 分 45 秒。这些数据支持队列受到持续重试的影响。缺少入队、延迟到期、实际出队及 worker 占用的逐项证据，无法量化它对这次等待的贡献。后端在首次请求时报告状态不符，现场材料也未确定其内部状态。

## 源码核验

- **终态重试。** 在控制器 `v0.6.0-release.1` 发布分支，`pkg/controller/checkpoint/core/common_control.go` 的 `EnsureCheckpointPhaseCompleted` 无条件返回普通错误。控制器在 `checkpoint_controller.go` 的 Succeeded / Failed 分支向上返回该错误，controller-runtime 据此将同一对象限速重排队。缺陷限于选中 common control 的对象。控制模式注解优先；若没有指定模式且 Pod 已消失，控制器会选择 common control。
- **快照失败。** ACS Pending 创建调用失败后返回错误，此时尚未进入 Creating。后续调谐若取不到源 Pod，Pending 分支直接写入 Failed、完成时间及缺失 Pod 的消息。状态写成功后不会再次尝试创建这个快照。休眠控制器在释放后的 DeletePod 阶段可以删除源 Pod。终态重试的对象和受影响的 Pending 快照可以是不同对象。
- **候选修复。** 在应用标签 `agent-sandbox-controller-v0.6.7-release.4` 的最终源码中，终态 pod-info-only 对象走 common control 时直接成功返回。其他内容类型进入该处理分支时写入 Failed、完成时间和不支持的原因，也以成功返回。该版本的单测包含已成功 filesystem 对象转 Failed 的用例。评估升级须复核真实组件到镜像的映射及存量对象所走的控制模式。
- **等待时间。** 核验的发布分支只为 Checkpoint 显式配置 worker 并发数，未指定专用限速器。client-go 默认限速器对单对象指数退避（初值 5 毫秒，上限 1000 秒）和共享令牌桶（10 QPS，突发 100）给出的延迟取最大值。单凭两次创建失败和 26 分 45 秒的调谐间隔，无法反推出该对象已达到指数退避上限，也无法拆分实际等待时间。[client-go 默认限速器](https://github.com/kubernetes/client-go/blob/v0.35.0/util/workqueue/default_rate_limiters.go)

## 版本对应关系

现场报告的组件为 controller `v0.5.25-release.1`（20 个 checkpoint workers）、manager `v0.6.11` 和虚拟节点 `v2.19.1`。旧 controller 的组件模板使用同版本号作为镜像 tag，尚缺该运行镜像的 digest 与源码提交映射。旧版代码与现场重复错误互相印证。manager 组件对应的候选源码也显示，快照请求使用生成名称并将 Sandbox 名称写入 `spec.podName`。

`v0.6.7-release.4` 已核实为控制器应用源码标签。另有组件 `ack-agent-sandbox-controller v0.6.8-release.1` 的构建记录，其控制器镜像对应的源码包含相同的终态处理逻辑，可作为升级评估的候选。目标集群的组件可用性、兼容性及存量快照影响仍待核验。

## 后续取证

优先核对受影响组件与候选组件所用镜像、终态对象的控制模式和内容类型，再按[验收场景](requirement.md)评估升级与竞态处理。若需解释精确等待时间，应对齐该对象的重试次数和入队、出队时间，并结合当时的队列深度、队列等待时长及 worker 使用情况。
