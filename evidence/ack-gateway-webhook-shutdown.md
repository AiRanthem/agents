# ACK Gateway 优雅下线与内存事件边界

核验日期：2026-11-03。范围：工作项 `2-feishu-wake-openclaw` 的设计调查。用户接受 Gateway 退出后丢失内存事件，要求在每次唤醒固定耗时 10 秒的假设下，判断现有优雅退出能否等所有事件处理结束。

## 结论

默认编排给下线开始前已启动的 10 秒任务留出了处理窗口，但现有机制不能保证排空所有已确认的后台内存事件。缺口是没有明确停止接收业务事件并等待任务完成的进程级流程，而不是 Pod 总宽限期小于 10 秒。当前源码也尚未实现本需求的 Webhook ACK 后内存缓冲。

## 编排与镜像身份

配置证据仅来自 `/Users/sophon/Workspace/OKAWorkspace/ack-components`，主检出在干净 master 上执行 `git pull --ff-only` 后为 `02d1a5f3b1c7fe5478ea69e105eb9dddfada8934`。未使用 Agents 源码仓中的示例编排。

- 主分支组件目录：`addons/ack-sandbox-manager/main/v0.6.14-release.1`。
- 已刷新的 `origin/release/ack-sandbox-manager-v0.6.15-release.1` 为 `572f5388ae19659fb27819075f3b60a0038124c5`；该版本 Gateway Deployment 模板与上述版本完全相同，相关默认时间值相同。
- 已刷新的 `origin/release/ack-sandbox-manager-v0.6.14-release.2` 为 `01a3f9e978c73f0286da086dfa8e0698b35a53d2`；该版本也核对了以下相同的退出配置，不声明其完整模板相同。
- `configs/default.yaml:13-15` 指定 `acs/ack-sandbox-gateway:v0.6.0-release.1`，`component.yaml:45` 映射到构建源镜像 `ack-sandbox-gateway-v0.6.0-release.1_e55d70c7f_202610160807`。
- 对应 Gateway 源码固定为 `e55d70c7fc7d603e8a585918919788edd0374e31`。其 `dockerfiles/sandbox-gateway-inner.Dockerfile` 和社区 Dockerfile 均以 `envoyproxy/envoy:contrib-v1.37.3` 为运行基座；进程是 Envoy，Gateway Go 代码作为共享库运行。

这些证据确认组件包的默认编排和镜像绑定，不代表已读取某个线上集群的实际覆盖值、imageID 或发布状态。

## 已核对的默认配置

下表路径相对上述 v0.6.14-release.1 组件目录：

| 项目 | 值与位置 |
| --- | --- |
| Pod 终止总宽限期 | `drainTimeSeconds + 60`，默认 90 秒；`charts/ack-sandbox-manager/templates/sandbox-gateway.yaml:41-43` |
| Envoy drain 时长 | `--drain-time-s 30`；模板 85-86 行，`values.yaml:339` |
| preStop | `curl -sS --max-time 5 -X POST http://127.0.0.1:9901/drain_listeners?graceful`，随后 `sleep 30`；模板 143-151 行 |
| 就绪检查 | Go system server 的 `/readyz:7789`，不是 Envoy admin readiness |
| 普通流量唤醒等待上限 | `wakeTimeoutSeconds: 600`；`values.yaml:381`。这是上限，不是此次固定 10 秒的实际耗时假设，也不是退出等待时间。 |

已执行 `helm template`，以实际 `configs/default.yaml` 叠加 Chart，核验输出为上述 90 秒、30 秒及 preStop 命令。配置中的 RegistryURL 以 Chart 已有仓库地址展开，与退出无关的 ClusterID 使用 `render-check` 占位。原始渲染输出位于本机临时目录 `/var/folders/c3/v8kf0ppx7rxbr57gt865pl0r0000gp/T/webhook-gateway-shutdown-hz1hfxik/rendered-gateway.yaml`。

## 为什么不能推出所有事件完成

1. **graceful drain 不是立即停止接流。** Envoy 1.37.3 在 drain 期间仍可接受新连接，到 drain 时限才停止 listener；HTTP/1 通过 Connection: close、HTTP/2 通过 GOAWAY 引导连接退出。[固定版本说明](https://www.envoyproxy.io/docs/envoy/v1.37.3/intro/arch_overview/operations/draining)、[固定版本处理函数](https://github.com/envoyproxy/envoy/blob/v1.37.3/source/server/admin/listeners_handler.cc#L15-L56)。不能把更新版本的 drain 行为套用到此镜像。
2. **ACK 后的任务不再是未完成 HTTP 请求。** Envoy 不会自动统计新加的 Go 内存事件队列。现有 `filter.go:160-171` 为每条流量唤醒创建 goroutine，`OnDestroy:497-507` 只取消该请求的 context，没有等待它完成。新 Webhook 任务也不能直接沿用该 stream context：提前返回 ACK 后，需要由进程级任务所有者继续持有事件和执行上下文。
3. **8 秒 StopProcess 清理的是 peer 服务。** `filter/config.go:178-191` 的 Config.Destroy 调用 `server.StopProcess`，`server.go:51-53` 给出 8 秒等待上限；`server.go:400-417` 停止 peer/system HTTP server、memberlist 和 peer outbound，没有排空业务事件的计数或 join。8 秒也不是保底等待时长，完成清理即可返回。
4. **90 秒不是强制保活。** Kubernetes 在 preStop 完成后发送 TERM，宽限期到期才对仍未退出的容器强制终止；应用可以提前退出。Envoy 1.37.3 的 TERM 进入 `shutdown()` 并结束 dispatcher，而不是自动再给所有业务任务等满余下时间。[Kubernetes 终止流程](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#pod-termination-flow)、[Envoy 信号与退出源码](https://github.com/envoyproxy/envoy/blob/v1.37.3/source/server/server.cc#L980-L994)。

源码 main 还使用 Background context 启动 controller manager 和 peer server（`cmd/sandbox-gateway/main.go:54-95`）；目前没有统一取消并 join 这些后台任务的总流程。Kubernetes EndpointSlice 对终止 Pod 的摘流与本地 preStop 并行推进，不能代替应用自身确定的停止接收边界。

## 固定 10 秒的反例

以下仅是由当前机制允许的时序，不是实测故障：

- t=0：调用 graceful drain，开始 30 秒 preStop 等待。
- t=25：一条仍可到达旧 Pod 的连接提交事件，Gateway 内存接收并 ACK，后台唤醒需 10 秒。
- t≈30：preStop 结束，收到 TERM。现有退出流程不等这个内存任务，进程可以退出。
- t=35：事件本应完成；如果进程此前已退出，该事件丢失。

对于 t=0 前已开始、没有排队且可并行推进的事件，固定 10 秒在 30 秒窗口内能够完成。这个算术条件不等价于“所有已接收事件都能完成”：下线期间的新事件、排队等待以及唤醒后的转发时间仍要计入。

## 对当前设计的影响

用户已接受正常下线先停收、排空、再退出的方向。无需因此引入持久存储：先停止接收并对新事件返回可重试失败，再等待已接收事件的唤醒及应用交付完成，最后允许进程退出。任务生命周期须与已经结束的 Webhook HTTP 请求分开。

在固定 10 秒、没有排队积压且转发及时完成的假设下，现有 90 秒总预算足够安排该顺序；当前仅有 drain + 固定 sleep，尚未实现事件级排空。这是设计建议，未据此修改编排或业务源码。

## 正常下线的建议细节

以下是对已确认顺序的细化建议，并非完整 Webhook spec 或已实现机制。建议先执行业务排空，再执行现有 Envoy 连接 drain；这种串行顺序在已有 90 秒预算内可容纳假定的 10 秒唤醒，也能使任务交付期间需要的 listener、peer 与路由能力持续工作。

1. **接收时先登记，再 ACK。** 进程级任务所有者保存事件以及唤醒、交付所需的请求数据，覆盖排队和执行中的事件。合法请求的接收检查与任务登记同停收操作互斥，保证并发事件要么被登记并纳入排空，要么返回失败。ACK、客户端断连或 Envoy stream 销毁均不结束已接收任务；后续执行不调用已销毁 stream 的 API。
2. **preStop 发起业务 drain。** 通过仅限 Pod 内访问的本地管理接口，原子切到 draining，后续新事件返回 503，不 ACK、不入队、不触发唤醒。readiness 同时返回失败，liveness 保持正常；不把内部 route registry 设为不可用，也不提前关闭 route 同步、peer 服务或 outbound。现有 system server 同时承载 peer refresh 且可启用 TLS，不能直接在其可达地址上暴露无鉴权的停机操作；推荐独立的 loopback 管理入口，并禁止经业务 listener 代理访问。
3. **有界等待原有事件。** 等待范围是接收时已登记的全部事件，直到应用有效确认接收或事件按统一策略进入失败终态；区分成功交付、失败终态和仍未完成的数量。等待不覆盖 OpenClaw 的模型调用及飞书最终回复。排空开始不会取消任务；建议业务排空最长 30 秒，队列清空则提前返回。到期后停止重试、取消剩余任务并记录未完成数量和原因，按允许丢失的边界继续退出，不把超时记为成功交付。
4. **完成原有连接退出。** 业务排空结束后，preStop 再调用 Envoy `/drain_listeners?graceful` 并保留原 30 秒 sleep。之后 hook 返回，Kubernetes 才发送 TERM，沿用既有 Envoy/Go 资源清理。这使业务排空发生在 `Config.Destroy` 和 8 秒 `StopProcess` 清理之前，不在后者中承担 10 秒唤醒等待。

管理调用应幂等：重复调用复用首次停收状态和绝对排空截止时间，不重新开放接收或延长业务排空预算。调用方断连不取消已接收事件，也不撤销 draining。调用失败或超时要可识别并记录，随后仍执行现有连接 drain，不宣称已正常排空；崩溃、强制终止和跳过 preStop 的直接进程终止不新增保交付保证。Kubernetes 的 hook 可能重复投递，且 preStop 占用 Pod 总终止宽限期，见 [官方 hook 契约](https://kubernetes.io/docs/concepts/containers/container-lifecycle-hooks/)。

时间预算建议：业务 drain 服务端最多 30 秒，本地调用最多 35 秒；加现有 Envoy admin 调用最多 5 秒和连接等待 30 秒，正常一次 preStop 执行最多约 70 秒，默认 90 秒总 grace 还留约 20 秒给 TERM 后的清理与调度开销。实际唤醒若在 10 秒完成且交付及时，则业务 drain 约 10 秒后即可结束，整个 preStop 约 40 秒加交付与调用开销。自定义时间值需满足同一总预算约束；不是固定多 sleep 30 秒。

本次反例检查覆盖停收前后并发接收、ACK 后 stream 销毁、下线中依赖被提前关闭、重复 drain 和超时。上述建议给出了相应边界；任意积压不能由“单次唤醒固定 10 秒”推出 30 秒内全部交付，内存容量、并发与短时重试需在完整 Webhook 设计中共同收敛。未做运行验证或独立设计审查。

已执行：刷新仓库、组件模板及默认配置核对、镜像到源码匹配、固定版本源码与官方文档检查、Helm 渲染。未执行：读取指定线上集群覆盖值、真实 Webhook 10 秒唤醒、删除或滚动 Gateway Pod、故障注入及端到端验证。
