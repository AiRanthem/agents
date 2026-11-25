# 设计依据

设计核对的 OpenKruise Agents 上游 master 提交为 `3fc1216cea513df40b68f77171b042dc1ef7e8e3`。以下为源码证据。

- 令牌签发通过 `WithoutCancel` 保留请求的上下文值，并单独接入 Manager 停机取消；各调用方独立等待共享结果。仓库已有用例覆盖一个等待者取消后另一个等待者仍拿到令牌。[等待分支](https://github.com/openkruise/agents/blob/3fc1216cea513df40b68f77171b042dc1ef7e8e3/pkg/sandbox-manager/traffic_token.go#L77-L135) · [签发生命周期](https://github.com/openkruise/agents/blob/3fc1216cea513df40b68f77171b042dc1ef7e8e3/pkg/sandbox-manager/traffic_token.go#L205-L221) · [既有用例](https://github.com/openkruise/agents/blob/3fc1216cea513df40b68f77171b042dc1ef7e8e3/pkg/sandbox-manager/traffic_token_test.go#L259-L308)
- 令牌 API 将不可用错误映射为统一响应，Web 框架记录转换后的 `ApiError`。响应文字不足以恢复原始来源。[API 映射](https://github.com/openkruise/agents/blob/3fc1216cea513df40b68f77171b042dc1ef7e8e3/pkg/servers/e2b/traffic_token.go#L54-L72) · [请求结果日志](https://github.com/openkruise/agents/blob/3fc1216cea513df40b68f77171b042dc1ef7e8e3/pkg/servers/web/framework.go#L159-L171)
- Pause/Resume 的等待错误分支检查当前 `ctx.Err()` 并使用客户端取消文案。Claim 则有自己的期限，等 worker 时的错误文案包含 “context canceled”。归因需要区分退出原因和记录时的状态。[Pause](https://github.com/openkruise/agents/blob/3fc1216cea513df40b68f77171b042dc1ef7e8e3/pkg/sandbox-manager/infra/sandboxcr/sandbox.go#L585-L596) · [Resume](https://github.com/openkruise/agents/blob/3fc1216cea513df40b68f77171b042dc1ef7e8e3/pkg/sandbox-manager/infra/sandboxcr/sandbox.go#L663-L675) · [Claim 期限](https://github.com/openkruise/agents/blob/3fc1216cea513df40b68f77171b042dc1ef7e8e3/pkg/sandbox-manager/infra/sandboxcr/infra.go#L149-L165) · [Claim 等待](https://github.com/openkruise/agents/blob/3fc1216cea513df40b68f77171b042dc1ef7e8e3/pkg/sandbox-manager/infra/sandboxcr/claim.go#L374-L381)

设计作者为 Codex。独立设计评审已通过；源码实现与运行验证尚未进行，待用户另行授权实现。

## 2026-11-25 独立设计评审

**结论：通过（`pass`），无阻塞项。** 当前设计状态登记为 `implementable`；这表示已确认设计经过独立可实现性评审，不代表实现授权、源码交付或人工验收。

### 评审身份与输入

- 评审者：Qoder（本会话未参与原设计或任何实质修订）。设计作者仍为 Codex；本次登记不增加设计作者。
- 辅助 Explore 代理仅定位其余取消日志入口并提供基线证据，未承担独立通过结论；主评审者自行核对关键源码、错误包装及测试断言。未声明跨模型评审。
- 评审与登记授权来自[用户决定](decision.md#2026-11-25-评审与登记授权)。
- 评审输入：项目提交 `c8c55f3cf99c259fdfcb83283223abdb1ed5693e` 中的 `requirement.md`、完整 `spec.md` v1、`decision.md` 和源码依据；适用项目、主工作区及源码仓库的原始指令。
- 输入设计 SHA256：`144ba8829edacb9df65c87a1c2ed4da51d1000e9a83f6bb60d88ca6192a99a88`。
- 输入需求 SHA256：`4b207b329c5286cbc0e2ce4f80250e9a725f1fb46d626f674e80d2551dd7a695`。
- 源码基线：`3fc1216cea513df40b68f77171b042dc1ef7e8e3`。源码主检出为 `62532a56c593cc30c8690c2a45bb4d424da86c46`（`develop`），与设计基线不同；评审通过 Git 固定对象及对应文件差异校准证据，没有将主检出视作上游基线。

### 覆盖与依据

- 共享令牌的请求等待与独立签发分别归因；请求退出不取消其他等待者，Manager 停机取消签发，两个退出分支同时就绪时以实际采用的分支及原因确定来源。核对 `pkg/sandbox-manager/traffic_token.go:77-135,205-221` 及既有取消、签发超时和停止排空测试。
- 原始取消错误与归因需跨 Manager 错误包装、API 消息转换保留，且不能泄漏到 HTTP 响应。核对 `pkg/sandbox-manager/errors/error.go`、`pkg/sandbox-manager/api.go`、`pkg/servers/e2b/traffic_token.go:54-70`、创建及 Pause/Resume 的错误映射，以及 `pkg/servers/web/framework.go:159-171`。
- Pause/Resume 等待会二次检查对象；取消信号不一定等于最终失败原因，也可能最终成功或返回冲突。核对 `pkg/cache/utils/wait.go:183-260`、等待相关测试和基线 `pkg/sandbox-manager/infra/sandboxcr/sandbox.go`。设计要求冲突、超时、成功省略字段，与这一边界一致。
- Claim/Clone 自有期限、重试和错误文案不能替代取消证据。核对 Infra 等待、错误分类、最终错误包装及清理路径，要求保留本地可取得的原因，不改变已有超时、重试和状态码规则。
- 核对 quota、配置/密钥存储、生命周期、后台清理和既有静默取消入口。设计保留原日志级别及静默路径，不要求新增取消日志；成功后的常规 `cancel()` 清理不应产生 `cancelSource=internal`。
- `unknown` 仅用于确认取消但来源证据不足的情况；请求 ID、错误文本或写日志时的 context 状态都不能单独定因。未发现必需的未决设计选择或阻塞性可实现性缺口。

### 实现交接注意

以下是已确认合同的验证重点，不是设计阻塞项或新增需求：

1. 验证取消归因经过 API 映射后仍保留，同时 HTTP 状态码、JSON 字段及响应消息沿用现有行为。
2. 验证后到取消不覆盖已确定的来源；覆盖共享签发失败与请求取消交错，以及等待二次检查返回成功、冲突和普通超时的字段省略场景。

### 实际检查与限制

执行了 `git status`、`git rev-parse`、`git ls-tree`、`git show`、针对性 `git diff` 和 `shasum -a 256`，结合原文件阅读核验输入身份、基线及关键路径；评审结束时需求、设计指纹保持不变，项目与源码工作树均无改动。参考 Go context 文档核对取消脱离、回调及首个取消原因的语义。

本轮为只读设计评审，未修改源码、运行测试、启动应用或进行现场验证；既有测试只核对其行为与断言，未将其视为本次运行通过。设计可实现性通过不代替后续独立实现评审、人工验收或交付。

本次登记仅将 `spec.md` 的 `design_status` 从 `review-pending` 改为 `implementable`，正文、需求、版本和源码基线保持不变；最终登记指纹保存于 metadata 和 state。
