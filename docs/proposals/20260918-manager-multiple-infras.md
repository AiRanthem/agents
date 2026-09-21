# Sandbox Manager 多 Infra 支持设计

## 摘要

本设计让同一 SandboxManager 在构建时注册多个 Infra，并显式指定唯一默认项。入口默认使用 `sandboxcr`，Substrate 的连接配置不改变默认选择。Manager 通过统一的 `InfraOptions` 选择后端；一次操作始终使用同一后端，返回的 Sandbox 对象保留归属，后续操作沿用该绑定。

E2B 对已有 Sandbox 从 Route 恢复 Infra，再显式传给 Manager，客户端仍可只提供 Sandbox ID。创建、列表、模板及无法从 Sandbox Route 确定归属的快照操作，通过 `x-e2b-kruise-infra` 选择后端，省略时使用默认 Infra；列表不跨后端聚合。内置标识严格为 `sandboxcr`、`substrate`，无效选择或归属冲突均失败，不回退其他后端。

Substrate 的公共 Sandbox ID 直接采用服务端返回的完整 Actor `metadata.uid`，不使用 name、namespace 拼接值或短 ID。同一 Actor 在创建、列表、生命周期操作和 Manager 重启恢复后保持同一公共 ID；短 ID 开关仅影响 SandboxCR。

Route 携带 Infra 信息，更新、删除与版本比较按来源隔离，并将信息传递到 Gateway。启用共享 API-key 配额时，任一已注册 Infra 缺少完整配额观测能力即拒绝启动；本次不补齐 Substrate 的该项能力。本次不设计 Gateway 转发、跨 Infra 公共 ID 唯一性机制或旧 Route 兼容，保持现有授权与 Route 可见性边界，不据此宣称具备完整上线条件。

## 背景

OpenKruise Agents 为调用方提供 Sandbox 的创建、查询、暂停、恢复和释放能力。E2B 兼容 API 负责协议解释与访问控制，Manager 负责与协议和后端无关的业务编排，Infra 负责具体后端上的资源操作。SandboxCR 使用 Kubernetes 资源及其控制器管理 Sandbox；Substrate 则通过自身的控制服务管理执行环境。

单个 Manager 绑定单个 Infra 时，每次请求无需区分资源来自哪个后端。支持多个 Infra 后，仅允许同时注册后端还不够：创建时的资源查找与执行必须落在同一后端，后续操作必须找回原后端，路由更新和删除也不能影响其他后端的同名资源。

E2B 客户端通常通过 Sandbox ID 发起后续请求。E2B 已通过 Manager 读取 Route 中的归属信息来检查访问权限，因此可以复用这份记录恢复 Infra 归属。这样既能向 Manager 显式传递选择，也无需要求客户端在每次 Sandbox 操作中记住后端，更不需要另建一份持久化的 ID 到 Infra 映射。

Substrate 的 Actor name 与 UID 是不同的身份信息。name 由调用方在创建时指定，用于后端资源定位；UID 由 Substrate 服务端分配并持久保存，在同一 Actor 的生命周期内保持不变。将 UID 直接作为公共 Sandbox ID，可以让 Manager 从后端观测恢复原有公共身份，避免仅保存在进程内的另一个 ID 在重启后丢失。

## 设计终态

### 职责与交互边界

依赖方向保持为 API → Manager → Infra。E2B 解释请求头、执行协议层认证与授权、转换请求及错误；Manager 解析中立的 Infra 选择，执行生命周期、准入和配额等业务规则；Infra 提供后端能力与观测信息。E2B 不直接选择后端客户端执行资源操作，Manager 和 Infra 也不解释 HTTP 请求头。

Sandbox 对象代表已经绑定具体 Infra 的操作对象。Route 则记录 Sandbox 的公共 ID、资源身份、状态、目标信息及访问控制信息，并新增 Infra 归属。二者共同使单次操作内的委派和跨请求的归属恢复保持一致。

### 多 Infra 注册与默认选择

SandboxManager 在构建阶段通过 Builder 的 `WithInfra` 注册多个 Infra，并在注册时显式指定该项是否为默认 Infra。注册另一个后端不覆盖已注册的后端。构建完成时必须恰好有一个注册项被指定为默认值；没有默认值或指定多个默认值，均构建失败。默认值不由注册顺序、后端类型或连接配置推导。

内置 Infra 的公开标识固定为 `sandboxcr` 和 `substrate`，分别表示 SandboxCR 与 Substrate。注册、操作选项、Sandbox 绑定及 Route 使用相同标识，值区分大小写，不做大小写归一化，也不接受 `sandbox-cr`、`kubernetes` 等别名。标识用于稳定表达后端归属，不是地址或凭据；标识合法但对应 Infra 未注册时，仍不能选择它。

`sandbox-manager` 入口显式将 `sandboxcr` 注册为默认 Infra；双注册时，`substrate` 是非默认项。`--substrate-addr` 只提供构建 Substrate Infra 所需的连接信息，不承担全局后端切换或默认值选择职责。构建 Substrate Infra 时缺少必要连接信息，构建失败，不能以切换默认值或替换后端消解该错误。入口负责显式组装注册项，本次不新增默认值 flag。

Manager 管控接口通过嵌入操作选项的统一 `InfraOptions` 接收选择；需要选择 Infra 而未指定时，使用构建时的默认值。某次请求的显式选择不改变其他请求的默认值。

创建、按 ID 查询和列表等 Manager 入口使用相同的选择规则。列表只查询选中的 Infra；省略选择时只查询默认 Infra，不聚合其他后端。这样调用方能够明确控制查询范围，而不会因注册了更多后端就改变原请求的含义。

### 单次操作与 Sandbox 归属

一次操作中的资源查找、能力检查和实际执行必须使用同一 Infra。例如，在 SandboxCR 中找到模板，不能证明 Substrate 可以用该模板创建 Sandbox。模板、快照及其他后端资源的查找必须与实际创建保持同一选择。

Manager 从选定后端取得 Sandbox 后，返回的对象保留该 Infra 归属。创建结果、列表结果以及从后端观测重建的对象都遵循这一规则；重建时的归属来自提供观测的已注册后端。归属是操作对象身份的一部分，不能由用户可编辑的 metadata 改写。

暂停、恢复、删除及其他 Sandbox 对象操作沿用绑定的后端。需要额外 Infra 能力的操作，例如后端原生 Fork，也从源 Sandbox 所属的 Infra 取得该能力。如果操作同时携带 Sandbox 对象和显式 Infra 选择，两者必须一致，不能据此把已有对象改派到其他后端。

未知 Infra、归属冲突、选定后端查找失败或不具备所需能力时，操作失败，不转查或改派其他后端。Sandbox ID 保持不透明，不通过解析 ID 来推断 Infra。

默认值用于尚未取得绑定对象时的 Infra 选择。改变构建时的默认值，会改变直接调用 Manager 且省略选择的请求所查询的后端，但不会迁移已有 Sandbox。E2B 对已有 Sandbox 始终显式传入其 Route 中的 Infra，因此不受这种默认值变化影响。

### Substrate Sandbox 的公共身份

Substrate Infra 对外提供的 Sandbox ID 必须等于该 Actor 的完整 `metadata.uid`。不截断 UID，不增加 namespace 或其他前缀，也不以 `metadata.name`、调用方生成的 UUID 或 Manager 生成的短 ID 替代。只有取得有效的服务端 UID 后，才能对外交付该 Sandbox 的公共身份；缺少 UID 的观测不能用 name 补全身份或发布为有效 Route。

Substrate 不使用短 ID。`--enable-short-sandbox-id` 及短 ID 前缀配置仅影响 SandboxCR；双注册时，无论这些配置如何取值，Substrate 的公共 ID 都保持为 Actor UID。身份分配策略仍由 Manager 按后端能力协调，E2B 只透传已确定的公共 ID。

创建结果、列表结果、Sandbox 对象及其 Route 对同一 Actor 使用同一个 UID。暂停、恢复和 Manager 重启后的成功恢复不改变该值。从快照创建新 Actor 时，返回新 Actor 自己的 UID，不沿用源 Sandbox 的 UID。快照中表达源 Sandbox 身份的字段也使用源 Actor UID，不从源 Actor name 推导公共 ID。

公共身份与后端操作地址分别保留。Substrate Infra 仍使用 Actor 的 `atespace + name` 调用后端资源操作，但不能将 name 当作 UID，也不能从公共 UID 反解析出 namespace 或 name。UID 不替代既有 owner、namespace 授权检查；后端归属仍通过 Route 的 Infra 字段恢复。

例如，某 Actor 的 name 为 `worker-a`、UID 为 `u`，则创建响应、列表响应和 Route 的公共 Sandbox ID 均为 `u`。Manager 重启并成功恢复该 Actor 后，客户端继续使用 `u` 查询或恢复 Sandbox；启用 SandboxCR 的短 ID 开关不会改变这一结果。

### E2B 跨请求维护 Infra 归属

对于已有 Sandbox，E2B 从 Route 恢复其 Infra，再通过 `InfraOptions` 显式传给 Manager。客户端只需提供 Sandbox ID，无需提供 Infra 请求头。

对于无法从 Sandbox Route 确定归属的请求，E2B 使用统一扩展请求头 `x-e2b-kruise-infra`。请求头的值遵循上述严格标识规则，并且必须对应已注册的 Infra。只有省略请求头才使用 Manager 的默认值；显式空值、未知值或未注册的 Infra 均导致请求失败，不回退默认值。原生 E2B 路径与定制路径采用相同规则。

| 操作 | Infra 的来源 |
| --- | --- |
| 从模板或快照创建 Sandbox | 扩展请求头；省略时使用默认 Infra |
| 列出 Sandbox | 扩展请求头；省略时只查询默认 Infra，不聚合 |
| 查询、删除、暂停、恢复、连接或修改已有 Sandbox | 该 Sandbox 的 Route |
| 为已有 Sandbox 创建快照或执行 Fork | 源 Sandbox 的 Route 及取得的绑定对象 |
| 模板操作、快照列表及其他没有源 Sandbox Route 的资源操作 | 扩展请求头；省略时使用默认 Infra |

快照可以在源 Sandbox 删除后继续存在，模板也不一定对应某个已有 Sandbox。因此这些资源的操作不能依赖源 Sandbox 的 Route。调用方必须在关联请求中保持同一 Infra 选择，例如模板构建的发起与结果查询，以及使用快照创建 Sandbox。

处理已有 Sandbox 时，E2B 先认证调用方，再通过 Manager 的既有 Route 查询边界，从同一份记录取得 owner、namespace 和 Infra。E2B 使用这份记录执行现有访问检查，并在本次请求中保持其 Infra 选择，随后显式调用 Manager。Manager 从该 Infra 取得 Sandbox 后，仍执行实际资源的归属与生命周期状态检查。选择到后端不等于获得资源操作权限。

如果请求同时携带 Infra 请求头，该值只用于检查是否有效且与 Route 一致。完成调用方的访问检查后，若请求头无效或两者冲突，则拒绝请求，不执行 Sandbox 操作。省略请求头时仍使用 Route 归属，不使用默认 Infra。Route 上的 Infra 缺失、为空、未知或未注册时同样失败，不能借助请求头补全，也不能回退到默认值。用户 metadata 和 Sandbox ID 的形式都不是归属来源。

例如，默认 Infra 为 SandboxCR，客户端显式选择 Substrate 创建 Sandbox。后续另一客户端仅提供该 Sandbox ID 发起连接，E2B 从 Route 恢复 Substrate 并显式传给 Manager，取得的对象也绑定 Substrate。同一客户端不带请求头列出 Sandbox 时，列表仍只包含默认 SandboxCR 的结果。

入口默认 `sandboxcr` 意味着，无头创建、列表、模板及无源 Sandbox Route 的快照请求均选择 SandboxCR，即使已经注册 Substrate 并配置其地址。需要访问 Substrate 的这些请求必须显式携带 `x-e2b-kruise-infra: substrate`。本设计不保留“配置 Substrate 地址便使无头请求选择 Substrate”的行为。例如，两后端存在同名模板时，无头创建只使用 SandboxCR 的模板；只有 Substrate 存在该模板时，请求失败，不转查 Substrate。

### Route 身份、生命周期与传播

Manager 接收每个已注册 Infra 的观测，并在发布 Route 时保留来源归属。Infra 信息必须在 Route 分发过程中保留，直到 Gateway 接收到它。所有 Route 生产者都遵循相同标识契约，包括 Gateway 本地 informer 产生的 SandboxCR 更新和删除，其归属明确为 `sandboxcr`。这是根据已知观测来源写入身份，不是为空字段补默认值。本次只规定信息契约，不设计 Gateway 据此如何解析目标地址、选择传输方式或转发流量。

每次 Route 更新和删除都必须携带 Infra 身份。路由记录以及阻止旧观测重新生效的删除版本记录，均按 Infra 与其后端资源身份共同隔离；版本只在该范围内比较。因此，一个 Infra 中的同名资源更新或删除，不会覆盖另一个 Infra 的记录，也不会跨后端比较没有共同含义的资源版本。

Sandbox 暂停或没有 IP 时，Route 仍须保留 namespace、可用时的 owner 和 Infra 身份。流量是否就绪不决定该 Sandbox 是否仍可被管理。缺失、空或未知 Infra 的 Route 观测无效，不能据此更新或删除有效记录。Route 缺失时，E2B 保持既有 404 查询失败行为，不尝试默认 Infra，也不遍历后端查找。

重启恢复和路由分发需要使承接请求的 Manager 能取得这些信息，但本设计不新增“创建后立即在所有副本可见”或“恢复失败后仍可操作已有 Sandbox”的保证。恢复 Infra 也不会补回后端丢失的 owner；当既有恢复行为无法恢复每用户 owner 时，继续采用既有 namespace 授权回退规则，不将 Infra 归属恢复表述为更强的资源所有权保证。

### 共享策略与进程级依赖

多 Infra 注册不改变 Manager 对生命周期、准入和配额策略的所有权。API-key 配额是 Manager 进程级共享策略，覆盖所有已注册 Infra，不按默认值或请求选择拆分。启用共享配额时，准入计数与基于后端观测的校准必须覆盖全部已注册 Infra；任一后端缺少完整配额观测能力，进程就拒绝启动，并明确指出缺少能力的 Infra。不能静默只观察 SandboxCR，也不能让 Substrate 绕过共享配额。

完整观测是安全校准的前提：若准入已经记录 Substrate 的占用，而校准只观察 SandboxCR，仍被 Substrate 使用的占用会被误判为泄漏并释放。因此即使默认值为 `sandboxcr`，也不能忽略已注册的 Substrate。本次不补齐 Substrate 的配额观测能力，包含 Substrate 的注册组合不能启用共享 API-key 配额。将来只有补齐全部参与后端的观测能力，才能支持该组合下的共享配额。

上述启动约束针对实际启用的 API-key 配额：E2B 启用认证且配置配额 Redis 时适用。认证关闭或未配置配额 Redis 时，沿用配额不执行的既有行为。缺少后端观测能力属于启动配置不成立；运行时 Redis 传输失败继续沿用既有 fail-open 策略，本设计不改变该策略。

Manager 的发现、主实例协调和 SandboxCR 短 ID 分配属于进程级职责，其依赖独立于单次 Sandbox 请求选择的 Infra 组装。选择没有 Kubernetes 缓存的 Substrate，不得因此关闭 Manager 的发现能力或切换进程使用的身份分配器；Substrate 操作本身不使用该短 ID 分配器。这里不规定新的协调服务或具体依赖注入方式。

### 范围、前提与限制

本设计确定多 Infra 注册、默认选择、Sandbox 对象绑定、E2B 归属恢复与 Route 信息传播的行为。不设计 Gateway 转发，不提供跨 Infra 列表聚合，不新增独立 ID 到 Infra 映射，不反解析 Sandbox ID，也不通过失败后的后端切换实现资源迁移。

Substrate 的公共 UID 不包含 namespace 或 Actor name。依赖拆解公共 ID 来定位 Actor 的 Gateway 或其他消费者，需要另行适配这一身份契约；仅完成 Manager 的 UID 交付与 Route 传播，不代表这些消费者已能处理该 ID。本设计不扩展 Gateway 转发范围。

共享同一 Route 查询范围的 Sandbox 公共 ID 必须唯一。E2B 和流量消费者都先按公共 ID 取得 Route，之后才知道 Infra；即使下一步向 Manager 显式传入 Infra，也无法修复前一步的公共 ID 歧义。跨 Infra 的公共 ID 唯一性机制不在本次范围内，适用部署必须自行满足这一前提。

本设计不提供旧 Route 兼容默认值；缺少 Infra 的旧记录按无效归属处理。若部署需要兼容旧组件产生的记录，须另行确定兼容设计，不能据此放宽本合同。本文不宣称任意 ID 产生方或新旧版本组件可以安全混用，也不把已确定的委派机制等同于完整上线条件；适用部署仍须满足公共 ID 唯一性及所需 Route 信息可用的前提。
