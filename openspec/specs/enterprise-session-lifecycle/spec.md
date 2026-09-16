# enterprise-session-lifecycle Specification

## Purpose
规定企业身份子切片中纯文本会话的持久化、历史、分支、交互命令和单执行恢复语义，要求真实 HTTP、WebSocket 与 SDK 链路一致，既不遗漏现有 SQLite 会话旁路，也不把尚未交付的文件及学习领域伪装为可用。

## Requirements

### Requirement: 创建和继续真实会话

已认证用户 SHALL 经原聊天入口创建或继续本人的文本会话，由真实聊天执行链产生消息/事件并写入 PG；消息、turn、事件序号和最终消息关联 MUST 满足事务、归属及并发约束，保留原事件信封和真实 `cost_summary`。

#### Scenario: 创建后继续聊天
- **WHEN** 用户通过 `/api/v1/ws` 完成一次文本 turn 后继续同一会话
- **THEN** 新 turn 使用已提交历史并持久化新消息/事件；HTTP/SDK 能读取相同结果，不依赖原进程文件

#### Scenario: 最终提交失败
- **WHEN** 模型已有输出但最终消息或 turn 终态事务未成功
- **THEN** 不发出表示持久化成功的终态，错误和已提交事件可追踪，不以本地文件缓存冒充成功

### Requirement: 请求重试和事件顺序可解释

提供 operation ID 的请求 SHALL 在已公布保留期内按 tenant/user、请求指纹及操作 ID 去重，重复提交返回原结果而不重复调用模型或写消息；同 key 不同内容 MUST 冲突。原请求登记必须先于模型派发；中断后的相同 key 不自动重跑，已删除请求不因重放而复活。事件序号 SHALL 按 turn 单调唯一。未提供 key 的兼容请求或超出保留期的重试不承诺跨断线重复提交的去重。

#### Scenario: 重复 start 或并发事件追加
- **WHEN** 同 operation ID 的文本请求重试，或同 turn 并发提交事件批次
- **THEN** 请求只创建一次 turn，批次保留正确唯一顺序，无覆盖/丢失；重试可以定位已提交结果

#### Scenario: 请求 ID 被不同内容复用
- **WHEN** 用户以已存在 operation ID 提交不同消息或目标会话
- **THEN** 返回冲突，不能修改原请求或再次派发模型

#### Scenario: 中断或删除后重放请求
- **WHEN** 用户在保留期内重试已中断或已删除会话的原 operation ID
- **THEN** 返回原中断/删除状态，不重跑模型、不复活会话；重新发起业务执行须由用户显式创建新操作

### Requirement: 历史分支与会话编辑保持原语义

系统 SHALL 支持授权列表/详情/分页、历史 trace、标题/摘要/偏好、置顶归档、分支选择和 regenerate；父子引用只能指向合法同 owner/session 范围。已存在的 provider 私有状态脱敏和展示截断 MUST 保留，不能改变模型上下文内容。

#### Scenario: 编辑分支后 regenerate
- **WHEN** 用户选择合法分支并重新生成最后用户消息
- **THEN** PG 保留原分支及新的正确父子关系，使用所选上下文，不重复原最终消息或错误覆盖另一分支

#### Scenario: 查询历史 trace
- **WHEN** 本人查询消息事件和完整会话
- **THEN** 结果符合原分页/trace 契约，隐藏 provider 私有 metadata，并拒绝属于另一会话/用户的 message ID

### Requirement: 交互控制和重放全入口授权

系统 SHALL 保留 start/subscribe/resume/regenerate/cancel/reply 等适用的原 WS 操作；每次命令、事件订阅与输出访问 MUST 重验身份及 owner。cancel/reply/完成竞争 SHALL 有合法持久状态转换，重复命令不得重复产生副作用。

#### Scenario: 等待用户回复
- **WHEN** 原 `ask_user` 使 turn 等待，用户重新连接后对有效 waiting turn 提交回复
- **THEN** 原执行收到一次正确回复并继续；非 waiting、错误 owner 或重复回复被拒绝或返回已处理结果

#### Scenario: cancel 与完成竞争
- **WHEN** 用户取消的同时模型执行完成
- **THEN** 只有一个合法最终结果，状态与最终消息一致，不出现一边 cancelled 一边成功重复入账

#### Scenario: 带游标重连
- **WHEN** 用户以已提交的事件 seq 重连其 turn
- **THEN** 仅返回游标后的授权事件，已失效身份或他人 turn 不返回内容；不能通过订阅绕过详情授权

### Requirement: 会话删除不得虚报跨领域清理

系统 SHALL 完整支持无外部资源依赖的会话/消息删除，保持原运行中消息删除冲突语义；会话删除与新 turn 派发 MUST 有原子互斥保护，先阻断新派发并确认运行任务停止。删除 SHALL 原子更新对应幂等记录为无正文、无悬空引用的删除结果，旧请求不得暴露或复活被删内容。对含未适配文件/学习等依赖的记录或操作 MUST 在破坏性写入前明确拒绝，不调用 local 清理器或吞掉失败后返回成功。

#### Scenario: 删除纯文本会话
- **WHEN** 本人删除无外部依赖、已停止执行的会话
- **THEN** 关联消息/turn/events 按契约删除，后续列表/详情/重放不可读取，并保留无正文审计

#### Scenario: 删除关联未交付资源
- **WHEN** 目标关联文件、学习状态，或执行尚未确认停止
- **THEN** 返回依赖/状态冲突，保留数据，不先删除 PG 再尝试本地文件清理或宣称完整删除

#### Scenario: 删除与新 turn 并发
- **WHEN** 一个请求删除会话而另一个请求同时尝试继续该会话
- **THEN** 状态与派发原子协调，不启动向已删除会话写入的模型任务，不因检查与提交间隙遗漏新 turn

### Requirement: 单执行者重启恢复不承诺自动续跑

本切片 SHALL 限制一个实际企业执行者并提供排空和故障中断可见性；旧执行者未确认停止时 MUST 不启用竞争恢复。重启后已提交历史/事件可读取，不能恢复的旧 running/waiting turn SHALL 转为明确可重试中断，不自动重复执行模型/工具；不宣称已具备 G-H/HA。

#### Scenario: 进程崩溃后重建
- **WHEN** 已确认旧进程停止后，使用同一 PG 和全新 scratch 启动
- **THEN** 原历史与事件可读，旧在途状态不无限 running，原 waiting 的回复不误送新 turn；重新生成由用户显式发起

#### Scenario: 第二执行者或数据库连接丢失
- **WHEN** 第二个实例试图竞争执行，或当前执行者失去数据库/执行权
- **THEN** 不派发第二份用户任务，停止相应新派发/持久化提交并显式报告；未知旧进程状态保持受控停止，不凭超时宣称可以自动接管
