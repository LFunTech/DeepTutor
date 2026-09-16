# enterprise-local-identity Specification

## Purpose
规定 M1 企业子切片的固定租户本地身份和会话认证行为，使账号初始化、真实登录、退出、失效和私有会话授权形成可验证闭环，同时保留未来外部身份绑定空间而不提前开放多租户或全局管理员旁路。

## Requirements

### Requirement: 固定租户来源与分源准入

企业本地入口 MUST 从可信部署获得固定内部 tenant，客户端不得更改。系统 SHALL 独立保存外部资格、本地启停和初始化状态及来源版本，准入取交集；`not_required` 仅允许受控固定租户本地模式使用，不豁免用户有效性或资源授权。

#### Scenario: 客户端伪造 tenant
- **WHEN** 请求或 token 的 tenant 与可信固定租户不符，或 metadata/header/query 试图覆盖它
- **THEN** 拒绝访问，不能切到其他 tenant 或使用默认管理员 scope

#### Scenario: 本地暂停或初始化失败
- **WHEN** 外部资格为本地模式的 not_required，但 local_enabled 为 false 或必要基础资源未就绪
- **THEN** 登录、新 turn 和受保护访问仍被拒绝，不从单一 active 标志推断可用

### Requirement: 受控账号初始化与维护

系统 SHALL 通过可审计运维入口初始化固定租户、首位租户管理员及普通用户，并支持密码更新、禁用/启用和认证会话撤销。初始化 MUST 幂等且不因重复执行覆盖密码、恢复被禁用账号或自动提升同名用户；数据库只持久化安全凭证 hash。

#### Scenario: 首次及重复初始化
- **WHEN** 经授权部署维护者使用一次性 bootstrap 凭证初始化并再次执行
- **THEN** 只产生一个稳定身份及对应权限，重复操作可追踪，不产生多个管理员或重置已有凭证

#### Scenario: 无权限创建管理员
- **WHEN** 普通用户、匿名请求或无维护凭证的调用试图初始化/提升角色
- **THEN** 操作拒绝，不暴露公共首用户抢注入口，不通过用户名或请求字段自行授予管理员

### Requirement: 本地认证使用 PG 身份与受控 Secret

有效本地账号 SHALL 通过现有登录路径获得只包含必要可信字段的 `dt_token`；签名和模型凭证 MUST 由受控 Secret 获取，不写业务文件或明文 token 表。企业认证 MUST 验证 issuer/audience、时效、内部身份、认证会话及当前身份版本，不接受本地兼容模式 token 作为企业授权。

#### Scenario: 有效普通用户登录
- **WHEN** 固定租户内有效账号提交正确密码
- **THEN** 建立可撤销认证会话，返回正确 cookie/必要身份信息，后续 HTTP/WS 使用同一内部 tenant/user

#### Scenario: 无效或旧模式 token
- **WHEN** token 过期、issuer/audience 不符、签名错误、缺必要 scope 或来自旧 local 模式
- **THEN** 返回认证失败且不访问业务数据，不回退匿名 admin

### Requirement: 退出和账号变化实际撤销访问

退出 SHALL 撤销当前认证会话并清理同属性 cookie；账号停用、密码变更或受控撤销 SHALL 使对应旧凭证失效。HTTP 敏感操作、WS 新命令/订阅/重放及后台用户派发 MUST 重验当前状态，不能仅在握手时认证。

#### Scenario: 退出后重放 token
- **WHEN** 已退出用户重用原 bearer/cookie 或继续通过旧 WS 发命令
- **THEN** 认证拒绝，不能读取新事件或提交新 turn

#### Scenario: 管理员停用或用户密码改变
- **WHEN** 受控维护操作更新身份状态而旧连接尚未断开
- **THEN** 后续受保护操作和输出授权检查拒绝旧身份版本，在途任务按可见中断语义结束，不自动重派

### Requirement: 租户角色不授予他人私有内容

所有个人会话操作 MUST 同时验证有效成员、可信 tenant/user、记录 owner 和具体操作；tenant_admin、运维用途或相同租户身份不得自动获得他人历史/消息/事件。本切片不新增个人会话共享功能或平台私有内容访问权。

#### Scenario: 同租户管理员猜测会话 ID
- **WHEN** tenant_admin 或另一普通用户读取、订阅、删除或控制非本人 session/turn
- **THEN** 返回统一的未授权/不存在结果，不泄露正文、记录数量或有效 ID 信息

#### Scenario: 本人跨入口使用资源
- **WHEN** 本人通过 HTTP/WS/SDK/企业 CLI 访问其会话
- **THEN** 得到一致授权结果，用户名重命名或缓存复用不改变资源所有权

### Requirement: 数据库恢复不得复活旧授权

数据库备份恢复 SHALL 在关闭普通登录/执行的维护状态下完成；恢复的认证会话 MUST 全部失效，认证恢复世代不得随同一快照回退。账号/租户的禁用和凭证变化 SHALL 经受控核对及必要重置后才重新放行，未知状态保持禁用，不能因旧快照包含 enabled 或旧 hash 重新授予访问。

#### Scenario: 撤销之后恢复旧快照
- **WHEN** 备份完成后发生退出、账号禁用或密码更改，再恢复该旧备份
- **THEN** 旧 token 与已失效密码仍不能访问，恢复期间无普通业务流量；仅经授权核对及必要重置后的身份可重新登录，记录恢复审计

#### Scenario: 普通进程重启
- **WHEN** 仅重启应用而没有恢复或回退数据库
- **THEN** 继续使用 PG 当前有效认证状态，不要求全量密码重置，也不恢复已经撤销的会话

### Requirement: 认证传输保护与最小审计

认证入口 SHALL 限制失败尝试并避免账号枚举，cookie 写操作具备 Origin/CSRF 防护，WebSocket 校验受控 Origin。账号维护、撤销、权限拒绝及本切片资源管理 SHALL 记录脱敏持久审计；日志/响应不得包含密码、token、密钥或私有聊天正文。

#### Scenario: 跨站或暴力登录请求
- **WHEN** cookie 写请求/WS Origin 不可信，或凭证失败超出配置限额
- **THEN** 拒绝请求并给出不泄露账号存在性的错误，不创建身份或 turn

#### Scenario: 审查身份维护结果
- **WHEN** 检查账号初始化、禁用、撤销或失败操作的记录
- **THEN** 可关联 actor、目标、tenant、request ID、结果和时间，且无密码/token/正文；关键维护审计写入失败不虚报维护成功
