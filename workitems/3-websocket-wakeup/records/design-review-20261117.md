# WebSocket 唤醒设计 v1 独立审查

日期：2026-11-17。范围：`3-websocket-wakeup` 完整首期设计；用户明确调用 `review-design`。本报告由独立于设计作者的当前 Codex 会话直接完成，未委派评审，也未进行实质设计修订。

## 结论

**Independent review passed。** 在完整需求、已批准设计和下列固定源码证据范围内，未发现由本设计引入或被明确分配给本设计而仍未解决的阻塞问题；无需要用户补充决定的必要契约缺口。正式设计可登记为 `implementable`，版本仍为 1。

该结论覆盖父项整体契约和后续分解边界，不代表子项已经创建或通过独立评审。源码、镜像和编排位置在实施准备中确定，不妨碍本次 Why/What 评审；没有把这些尚未执行的工作视为已经完成。未建立实施授权、业务实现、源码合并、部署或真实端到端验收。

## 输入与独立性

- 项目输入提交：`7ceca3385618090fd712fbea7634049559baca4c`；开始审查时工作区干净，远端 `refs/heads/projects/im-auto-wakeup` 与该提交一致。
- 完整读取本项 requirement、spec、decision、context、metadata、logs，以及项目配置、项目／主工作区原始指令。用户对完整契约的批准来自 `decision.md` 记录的 2026-11-17“确认”，本轮审查不新增产品决定。
- 审查者：Codex 主代理 `/root`，会话 `01a1e84a-3acc-7e12-9870-7ff4bcdff90d`。设计累计实质作者记录为会话 `01a1bf6f-56d9-78a3-b359-c34f9bbaab3f`；当前会话未参与原设计及任何实质修订。历史资料用于导航和确认已接受边界，结论来自本轮原文及原始源码核读。
- 首次完整审查，未借用其他工作项的 Pass；Webhook 的可靠性和协议决定不作为本项的默认契约。

| 输入 | SHA-256 |
| --- | --- |
| `spec.md`（审查前） | `f6a66f09211952aa566bed2a01bffd43c7547d15618e43c2bd0fbe3fe364a64a` |
| `requirement.md`（审查前） | `4f89449943edcfae8984a8668064d734b32aa026678d151a98917c8652a0f858` |
| `decision.md` | `02d025dbecf574f13596ecba72d18240bc4624c978ddb5052f881a4345ca9528` |
| `spec.md`（状态登记后） | `2d45b38f3f5a55fd959fa4b024af92f79aaa9b613d1c09dbcc1a56a993fd18db` |

正式设计的唯一变更为 frontmatter 的 `review-pending` → `implementable`；正文与已批准输入逐字一致，不构成实质作者身份或新设计版本。需求和上下文仅同步本次评审事实。登记本身不替代独立判断。

## 关键核验及判断

### 接收、平台确认和内存边界

设计第 44–76、97–111 行将连接所有权、完整事件准入、平台确认与后续恢复／交付分开。同账号单活、旧实例停止前不接管，以及应用关闭自身接收连接，能够避免把飞书竞争消费当作广播监听；受控重启的停机和内存丢失属于明确接受的上限。

本轮直接读取飞书 Node SDK 固定提交 `b188be60134d409b61259546bcf69c731d2b0b7c` 的 [WSClient](https://github.com/larksuite/node-sdk/blob/b188be60134d409b61259546bcf69c731d2b0b7c/ws-client/index.ts)：`handleEventData` 在完整重组后等待 `eventDispatcher.invoke`，成功返回才发送成功业务确认，异常对应失败确认。控制消息由独立路径处理。这给出了在恢复前完成有限内存准入的可行接入点，不需要等待 Agent。

同时核读 [EventDispatcher.invoke](https://github.com/larksuite/node-sdk/blob/b188be60134d409b61259546bcf69c731d2b0b7c/dispatcher/event.ts#L154)：未注册 handler 并不自动成为失败；适配实现必须让准入失败真正传递到确认边界，并在普通 handler 归一化前保留原始封装。这是落实设计第 67–68、89、103 行的实现责任，不是尚未决定的设计行为。

条数／字节数、任务总期限、恢复等待和单次交付超时均有有限正值约束；期限从接纳开始，不随等待或重试重置。应用临时失败最多追加五次，恢复失败、永久错误、接收器退出各有终态。未把平台重投与应用交付重试混用，也未承诺固定回复时延或恰好一次。

### 原目标、授权与生命周期

设计第 56–58、69–76、91、115–121 行约束了平台身份、可信绑定、当前目标权限、自动唤醒开关和不可复用目标身份；正文不能选择其他账号或 Sandbox。手动 Pause 可恢复与关闭自动唤醒后的拒绝行为一致。每条消息保存原身份，并要求 Resume 写入、等待及最终交付全部保持该身份，覆盖检查后同名重建的窗口。

本轮通过 `git show cfbd102:...` 读取 Agents 固定基线 `cfbd102bc05c6df663965c5e23463a0eafd34948`，没有把工作项 1 工作树的未提交修改作为本项已交付能力。核读位置：

- `pkg/sandbox-gateway/wake/wake.go`：`SandboxUIDMatches` 只提供前置缓存检查，`Wake` 仍按 namespace/name 查找并调用 Resume。
- `pkg/sandbox-manager/infra/interface.go:154–163`：该基线的 `ResumeOptions` 尚无预期 UID 参数。
- `pkg/sandbox-manager/infra/sandboxcr/sandbox.go:232–308,594–680`：刷新及冲突重试重新按名字读取，乐观锁保护当前读到对象的写入，但不自动保证它仍是任务原来的对象。

因此，原实例约束是 A 部分必须实现的增量，不能直接宣布旧 Wake 接口已经满足。设计第 39、76、149 行已经明确承担该责任，且不允许直接操作底层 Pod／虚拟机或扩大 Gateway 跨层依赖，故不是设计遗漏。实现和代码评审须验证预期身份贯穿实际副作用，不能仅增加调用前一次 UID 比较。固定基线中的限制没有被误报为当前提案新引入的缺陷。

停用仅影响新接纳，旧任务在原目标和现行授权下继续；换绑不迁移旧任务。配置／凭据重启生效与受控重启后允许丢失剩余内存任务相容。每绑定串行交付与共享恢复不合并不同消息相容，不额外承诺应用执行顺序。

### 应用接纳、业务授权与回复

设计第 78–95、123–129 行建立了内部版本化 JSON 事件入口，要求认证、账号／目标匹配、完整原生事件及稳定交付身份；只有原生队列接纳后 HTTP `202` 和相同 `deliveryId` 才结束外部任务。缺失或错误回执不算成功，未知结果重试不换事件身份。应用业务拒绝和最终回复另行观察。

直接读取 OpenClaw 固定提交 `f7257f2c66884611f4f4043367eada029b704918`：

- [feishu-ingress.ts](https://github.com/openclaw/openclaw/blob/f7257f2c66884611f4f4043367eada029b704918/extensions/feishu/src/feishu-ingress.ts#L397)：`invokeWebhook` 保留原生封装，从 `header.event_id` 提取身份，并等待 `monitor.admit`；成功后返回 durable 接纳结果，不等整轮 Agent 完成。这支持应用薄入口复用已有队列。
- [monitor.account.ts](https://github.com/openclaw/openclaw/blob/f7257f2c66884611f4f4043367eada029b704918/extensions/feishu/src/monitor.account.ts#L644)：当前 monitor 启动 ingress 后选择 Webhook 或 WebSocket。因此外部接收模式需要 B 部分新增，不能靠把账号禁用或误用现有 Webhook 模式就声称完成。
- [channel ingress 契约](https://github.com/openclaw/openclaw/blob/f7257f2c66884611f4f4043367eada029b704918/docs/plugins/sdk-channel-ingress.md)：生产接入继续在实际宿主中生成并使用授权证据；设计没有把外部 JSON 视为应用业务授权。
- [durable ingress 契约](https://github.com/openclaw/openclaw/blob/f7257f2c66884611f4f4043367eada029b704918/docs/plugins/sdk-channel-plugins/durable-ingress.md)：去重身份为队列／事件，完成墓碑受保留期限和容量约束。设计保留这一有限去重边界；复用应用队列不改变外部队列只在内存的选择。
- [message-send.ts](https://github.com/openclaw/openclaw/blob/f7257f2c66884611f4f4043367eada029b704918/extensions/feishu/src/message-send.ts)：回复使用 `client.im.message.reply/create`，不依赖保留原接收长连接。

实现应在飞书插件自身或其正式 SDK 边界完成入口与生命周期接线，遵循 OpenClaw 根、extensions 和 channels 的原始指令，不另建绕过原生权限判断的处理器。现有内部 SDK 不是可直接调用的外部 HTTP 服务；设计已明确新增适配及匹配应用版本，不作未修改插件即插即用的承诺。

### 范围、复杂度与验收

统一核心只承担目标／生命周期／交付语义，平台连接和应用处理留在各自适配层。首期仅普通飞书消息，排除同步卡片等交互；其他平台会话回复是后续适配责任。单活、运维配置、既有原生队列和有限处理满足当前承诺，不需要引入持久外部队列、动态账号调度或通用会话 RPC。

A、B 共享事件和接纳契约，C 依赖两者实际交付；没有要求未交付的工作项 1 或并列 Webhook 项作为前置。验收覆盖旧连接完全失效后的真实消息至回复、授权、并发事件、回执丢失、同名重建、超限、超时、停用和换绑，能够区分恢复成功、应用接纳与最终回复。未发现需通过扩大首期范围才能兑现的承诺。

## 实际检查与剩余验证

已完成原始需求和完整设计核读、上述固定版本源码静态追踪、输入 SHA-256 核对、原作者与当前会话身份核对，以及项目远端输入提交核对。源码阅读使用固定提交和官方 GitHub 文件，未将浮动最新源码、工作树未提交改动或旧调查结论替代受审基线。

没有修改业务源码，没有运行新功能测试、SDK 进程、真实账号、Pause／Resume 或部署实验；这些不在本次设计审查内。具体实现基线与应用构建选定后，仍须检查上述能力和接口假设是否适用；变化只使受影响覆盖需要复核，不自动抹去本报告的固定版本证据。代码独立评审、源码合并和 C 的真实完整链路验证仍分别待完成。

项目登记仅更新设计状态、review 元数据及当前上下文，保留原设计作者、用户批准、`next_action: split` 和 `delivery.status: pending`。分解及后续实施未在本轮执行。

登记后检查通过：Ruby YAML 解析、v1／implementable／pass／pending 一致性、登记 SHA-256、设计正文与审查输入逐字比较、8 份 Markdown 的代码围栏及 15 个本地链接；`git diff --check` 通过。这些仅验证记录一致性，不验证运行行为。
