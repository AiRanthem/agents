# M1: Pause/Resume 缺乏幂等性导致并发场景下 timeout 出现回弹

## 一句话概括

`Sandbox.Resume` 中"取消暂停"那一步会无条件调用 `bumpResumeTimeoutProtection`，再叠加 `retryUpdate` 每次 retry 都重新跑 modifier、重新读最新对象，导致同一 sandbox 上并发的 Resume 请求互相覆盖，把已经 `SaveTimeout` 落库的"用户期望 timeout"重新顶回 `now+1h` 的保护值。根因是 pause/resume 没有按幂等接口设计。

## 涉及代码

- `pkg/sandbox-manager/infra/sandboxcr/sandbox.go`
  - `Sandbox.Resume` 取消暂停分支（`Spec.Paused=false` + `bumpResumeTimeoutProtection`）
  - `bumpResumeTimeoutProtection`：只判断"早于 `protectUntil`"，不感知调用方意图
  - `retryUpdate`：每次冲突重试都从 cache 重新拉对象再跑 modifier
- `pkg/servers/e2b/pause_resume.go`
  - `ConnectSandbox` / `ResumeSandbox`：可被同一用户、同一 sandboxID 的请求并发触发
  - `manager.ResumeSandbox` 没有锁、没有 in-flight 去重

## 复现场景

设 sandbox `S` 处于 paused，`Spec.PauseTime = T_pause`、`Spec.ShutdownTime = T_shutdown`（均经过 PauseSandbox 改写为 `now + 1000y`）。两个客户端 A、B 几乎同时对 `S` 调用 `Connect`，`request.TimeoutSeconds = 30`。

| 时刻 | A 的动作 | B 的动作 | 此时 S 在 etcd 的状态 |
|---|---|---|---|
| t0 | `getSandboxOfUser` → 拿到 Paused=true | | Paused=true, T_pause/T_shutdown=now+1000y |
| t1 | 进入 `Resume`，校验通过，进入 `if Spec.Paused { retryUpdate }` | `getSandboxOfUser` → 拿到 Paused=true | 同上 |
| t2 | retryUpdate: 从 cache fetch（Paused=true），modifier 把 Paused=false、bump（now+1000y > now+1h，bump 不动），update 成功 | 进入 `Resume`，校验通过，进入 `if Spec.Paused { retryUpdate }` | Paused=false, T_pause/T_shutdown=now+1000y |
| t3 | `WaitForSandboxSatisfied` 等 running | retryUpdate: 从 cache fetch（**Paused=false** 已是 A 的更新结果），modifier 把 Paused=false（no-op）、bump（仍然 now+1000y > now+1h，仍 no-op）、update 成功 | 同上 |
| t4 | running 已就绪，`SaveTimeout({PauseTime: t0+30s})` 成功 | wait running | Paused=false, T_pause=t0+30s, T_shutdown=now+max |
| **t5** | 返回 200 给客户端 A | retryUpdate 之前并未冲突，但 B 后续的 wait+SaveTimeout 仍在执行 | 同上 |
| **t6** | | `WaitForSandboxSatisfied` 完成（running 已就绪），`SaveTimeout({PauseTime: t1+30s})` 成功 | Paused=false, T_pause=t1+30s, T_shutdown=now+max |
| t7 | | 返回 200 给客户端 B | 持久化结果由 B 的请求决定 |

最终落库的是 B 的 `t1+30s`，而 A 已经收到 200。客户端 A 拿到的承诺与持久化状态不一致。

更糟的二级场景：在 A 已经 SaveTimeout 之后才到达的 B 请求，如果 B 的入口 `getSandboxOfUser` 命中的 cache 仍然是"未消化 A 那次 update"的旧版本（Paused=true），B 会再次进入 `if Spec.Paused { retryUpdate }`，触发 modifier。modifier 内 `bumpResumeTimeoutProtection` 看到 `T_pause = t0+30s < now+1h`，把它**改回 `B.now+1h`**。直到 B 的 `SaveTimeout(t1+30s)` 才把 `T_pause` 拉回 30s 量级。这个窗口内 controller 看到的是 1 小时窗口，等价于实际 timeout 被静悄悄地放宽。

如果 B 的后续步骤（wait/SaveTimeout）任意一步失败：

- `Spec.Paused=false`、`T_pause = B.now+1h` 已经 commit；
- B 的 `SaveTimeout` 没有发生；
- A 之前持久化的 `T_pause = t0+30s` 已经被 B 覆写；
- sandbox 实际生命周期变成 1 小时，远超用户请求的 30 秒。

## 根因

1. **bumpResumeTimeoutProtection 是无意识的"floor 操作"**：它不知道 `T_pause` 当前的取值是历史 PauseSandbox 写入的、是 A 刚 SaveTimeout 的、还是 controller 触发的，统一只看"是否早于 `now+1h`"。这让"非首次 Resume"和"首次 Resume"在 modifier 视角上完全等价。
2. **retryUpdate 的 modifier 每次都执行**：哪怕本轮 fetch 出来的对象 `Spec.Paused` 已经是 `false`，modifier 仍会调用 `bumpResumeTimeoutProtection`，因为 modifier 把 `Spec.Paused=false` 与 bump 写在了同一个 closure 里。
3. **Resume 没有"已经在 resuming 中"的去重**：`manager.ResumeSandbox` 没有锁、没有 single-flight、没有基于 sandboxID 的串行化，多请求并发时只能依赖 etcd 的 resourceVersion 冲突 + RetryOnConflict。但因为两边 modifier 在 etcd 视角上不冲突（都在写 Paused=false + 时间戳），retry 不会触发，两个请求各自完整跑完一轮。
4. **`Spec.Paused=false` + 时间戳 bump 写在同一个 closure 里**：上面三点的合力。如果"取消暂停"和"上 floor"是两次独立的、可以独立判断幂等性的写入，单点上还能补救；现在它们必须一起被覆盖，导致整体不幂等。
5. **e2b API 层无幂等键**：`ConnectSandbox` 是面向客户端的接口，理论上 SDK 重试 / 用户多窗口 / 进程崩溃后再 connect 都会落到同一 sandboxID 上。当前没有机制去识别"这是同一份逻辑请求的重试"。

## 影响

- 客户端 A 与 etcd 持久化状态不一致：A 收到的 `EndAt` 跟 sandbox 实际寿命可能差到一个 `protectUntil` 量级。
- 在 B 中途失败的子场景里，sandbox 寿命会被静默延长到 1 小时，浪费资源、违反 user-facing timeout 协议。
- 增大 controller 与 API 层之间的认知不一致：controller 看到的 `ShutdownTime` 是真实生效时间，API 层 `convertToE2BSandbox` 返回的 `EndAt` 来自最近一次 `sbx.GetTimeout()`，二者在并发期间会短暂偏差。

## 不在本 PR 范围

本 PR 的目标是修"Resume 报错后 sandbox 进入 never-timeout"的状态污染，已经处理 H1（推迟 timeout）/ H2（异常状态保留为设计预期）。M1 暴露的是 pause/resume 接口本身的幂等性缺陷，单独修复，避免与 H1/H2 改动耦合。

## 后续整改建议（按从轻到重）

1. **modifier 内做幂等短路**：在 `Resume` 里把
   ```go
   if s.Sandbox.Spec.Paused { ... retryUpdate(modifier) ... }
   ```
   的 modifier 改成
   ```go
   func(sbx *agentsv1alpha1.Sandbox) {
       if !sbx.Spec.Paused {
           return // 别人已经 unpaused，本次重试不要再 bump
       }
       sbx.Spec.Paused = false
       bumpResumeTimeoutProtection(sbx, time.Now().Add(time.Hour))
   }
   ```
   即使 retryUpdate 本轮 fetch 到的是已经 unpaused 的对象，也直接 no-op 退出。这一步代价最小、能堵 80% 并发覆盖问题。

2. **bumpResumeTimeoutProtection 加意图判定**：只有"`Spec.Paused` 由本次 modifier 从 true→false"才允许 bump，其他情况一律不动 timeout。需要 modifier 持有"前一次值"信息。

3. **manager.ResumeSandbox 加 single-flight**：基于 sandboxID 用 `singleflight.Group` 合并并发请求；并发请求复用同一个 in-flight 任务的结果，并将各自的 `request.TimeoutSeconds` 折算成"取最大的那个"或"取最近一个"再统一 SaveTimeout。需要明确合并语义。

4. **Resume 协议层 idempotency-key**：在 e2b API 入口接受 `Idempotency-Key`，对相同 key 的并发请求在网关层去重。E2B 上层 SDK 是否能配合提供需要先确认。

5. **状态机层面区分 Resuming**：把"Resuming"显式建模成 sandbox 一个独立 phase，让 controller 在 Resuming 期间不要响应外部 Pause/Connect 请求；API 层看到 `Phase==Resuming` 直接返回 409 让客户端等待。需要联动 sandbox-controller，改动面最大。

短期内推荐先做 (1)，只改 modifier 闭包，回归测试加一个"两个 goroutine 同时 Resume，校验最终 `Spec.PauseTime` 与最后一次 SaveTimeout 一致"的并发用例即可。

## 复现验证（待补充）

`pkg/sandbox-manager/infra/sandboxcr/pause_resume_test.go` 的 `TestSandbox_ResumeConcurrent` 现在只断言三个 goroutine 都 nil error，没有验证最终 `Spec.PauseTime`。修复 M1 时建议在该用例中：

1. 让三个并发 Resume 各自传入不同的 `infra.ResumeOptions{Timeout: ...}`。
2. 在所有 goroutine 完成后断言 `updatedSbx.Spec.PauseTime` 严格等于其中**某一个** Resume 的 SaveTimeout 值（last-write-wins），且没有出现"卡在 `now+1h` 保护值"的中间态残留。
