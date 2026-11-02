# 当前上下文

本工作项属于“OKA 日常开源开发”项目，目标代码仓库登记为 OpenKruise Agents（`agents`）。

设计基线为开源 master 提交 `cfbd102bc05c6df663965c5e23463a0eafd34948`。已核实该版本的 Gateway 自动唤醒通过底层 Resume 调整自动暂停期限；运行中尚无流量自动续期。E2B connect 已实现只延长有效截止时间的语义。

用户已确认：create metadata 显式开启；使用创建时的初始 timeout；新请求及双向实际数据到达时按 10% 阈值检查；空闲连接不续期；connect 与 Gateway 共用生命周期核心逻辑。完整设计仍在收敛，尚未执行独立评审或业务源码实现。

## 当前恢复记录

用户于 2026-11-02 明确授权修复共享项目脚本及必要测试，使设计和设计评审仅准备本地源码上下文；授权将本项目源码远端明确为 upstream=openkruise/agents、origin=AiRanthem/agents，并保留本地副本和原设计事务。此授权不包含业务源码实现或代码分支推送。

核对恢复目标时发现最初的设计准备命令已在先前检查后继续完成：项目提交 `58174ae190aa995986eae6258b4d5038677053e3` 已发布，本地 worktree 干净且 HEAD 为上述基线。它还未经设计授权向 openkruise/agents 创建了 `feature/oka-daily-open-source/1-gateway-wakeup-lifecycle-da492871d798`，远端回读 OID 为上述基线，没有业务源码改动。该事实已向用户披露；用户随后明确授权删除这一精确分支。已使用该 OID 的 force-with-lease 条件删除，随后 ls-remote 确认分支不存在。AiRanthem/agents 的同名源码分支也未发布。

因此保留现有完整克隆和干净 worktree，修正配置、开发绑定及本地 reservation，使后续目标指向 AiRanthem/agents；该目标上的源码分支记录为未发布。恢复前配置、事务及 Git 配置备份在本机 `.project-local/recovery/20261102-design-recovery-before.tar.gz`。原 tickets `06dd51633c8712d5670c23c7773957ae` 与 `307b5885dffecf5414f1bd489fc7ab5f` 均保留，按原返回命令恢复后者并刷新当前输入。

