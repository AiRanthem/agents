# 当前上下文

本工作项属于“OKA 日常开源开发”项目，目标代码仓库登记为 OpenKruise Agents（`agents`）。

设计基线为开源 master 提交 `cfbd102bc05c6df663965c5e23463a0eafd34948`。已核实该版本的 Gateway 自动唤醒通过底层 Resume 调整自动暂停期限；运行中尚无流量自动续期。E2B connect 已实现只延长有效截止时间的语义。

## 当前设计与评审

当前完整契约见 [设计文档](spec.md)：设计版本 4，SHA-256 `fbb509ab96ef8e1469b7b9ad11487e4a681ca81c5287f2373882628d39f8d149`，状态 `implementable`，发布提交 `50ca0d0f2eadab509326d60ecd59c0c9f219f43f`（程序已回读核验远端）。v4 由独立审查者在 v3（SHA `fe6cb2cc…`，用户批准）上做两处机械修正得到，保留 v3 的用户批准与原实质作者 `01a19b74-fe57-7cb3-9210-d1794ccbf164`、`01a19c14-b08c-7182-a5e0-7f3ae8f5c25c`；修正内容与依据见评审记录 `7915fe6baf16a0c72cc695684846b7f0`。v3 曾先后由会话 `01a19bf3-40ea-7c52-8b82-50b8158a578a` 和 `e38c177b-3df1-4ba1-aa20-0b0b039e07f7` 独立审查通过，后者即 v4 机械修正的审查者。

用户已确认：通过阈值和目标时长两个参数配置续期；阈值支持绝对 duration 或按本次接口 timeout 换算的百分比，持久化为绝对 duration。零阈值关闭时删除阈值记录，目标继续保留；create 的目标缺省为本次 timeout，connect/timeout 通过 header 按字段更新，缺省不改。新请求及双向非空数据触发检查，空闲连接不续期，connect 与 Gateway 共用生命周期核心逻辑。用户还要求续期配置与当次改期在同一接口中原子完成、校验前置，并确认目标时长为至少 2 秒的正整秒、暂停恢复配置与初始期限原子提交且等待失败不回滚、新扩展参数错误使用 400/409。这些约定均已体现在当前 spec 中。

尚未执行业务源码实现或功能验证；实现需用户另行授权并经 `development-start`。

## 实现交接

以下事项来自独立设计审查的 Low 发现，不改变已批准契约，实现及实现审查须逐项落实并核对：

- **续期写入不得挤占流量唤醒**：Gateway 由 `ctrl.GetConfigOrDie()` 构造客户端（`pkg/sandbox-gateway/controller/gateway_controller.go:132`），默认 20 QPS / 30 burst，现有唤醒的 Get 与 patch 共用该令牌桶。契约允许 R=`2s`、H 接近 R，持续流量下每个 Sandbox 约每秒写一次。实现除按 Sandbox UID 合并外，须为续期设置 Gateway 级全局并发或速率上限（超额时放弃本次续期即可，续期是尽力而为），并保证流量唤醒不排在续期写入之后，例如使用独立的限流或客户端。
- **唤醒规则 `PauseTimeout` 的优先级**：spec 已写明续期与流量唤醒都开启时恢复时长由 R 决定，不采用 `AutoPausePolicy.Resume.OnIngressTraffic.PauseTimeout`。实现须在代码注释与提案中写明，并用测试覆盖 R 与 `PauseTimeout` 不同、以及 `PauseTimeout` 未设置两种情况。
- **提案**：按仓库规则在 `docs/proposals/` 提交描述本设计的提案，包含上述优先级关系。

既有基线警告（与本变更无关）：控制器到达 `ShutdownTime` 时无条件 `Delete`（`pkg/controller/sandbox/sandbox_controller.go:1183-1206`），自动销毁模式下紧贴到期的续期仍可能被删除，spec 已声明此类尽力续期边界。

## 源码远端与历史恢复

用户于 2026-11-02 明确授权修复共享项目脚本及必要测试，使设计和设计评审仅准备本地源码上下文；授权将本项目源码远端明确为 upstream=openkruise/agents、origin=AiRanthem/agents。此授权不包含业务源码实现或代码分支推送。

最初的设计准备命令曾未经设计授权向 openkruise/agents 创建 `feature/oka-daily-open-source/1-gateway-wakeup-lifecycle-da492871d798`；经用户授权已按 OID 条件删除，ls-remote 确认不存在。AiRanthem/agents 的同名源码分支也未发布。现有完整克隆和干净 worktree 保留，配置、开发绑定及本地 reservation 指向 AiRanthem/agents，源码分支记录为未发布。恢复前配置、事务及 Git 配置备份在本机 `.project-local/recovery/20261102-design-recovery-before.tar.gz`；原 tickets `06dd51633c8712d5670c23c7773957ae` 与 `307b5885dffecf5414f1bd489fc7ab5f` 作为恢复证据保留。

恢复期间曾误将事务内保留的旧候选发布为 v1（提交 `83a1cf8075ab9975dba916a9e97c09abb687f9a7`），旧稿含布尔开关和固定 10% 阈值，与用户确认内容不符，已向用户披露；该版本及其登记不能作为任何约定的依据。后续评审及实现只使用当前 spec。
