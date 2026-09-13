## Purpose

规范 DeepTutor 从单租户 Kubernetes 正式部署到多租户及统一运营管理的连续交付约束，确保每阶段可独立发布、保留既有数据与生产底座，不建设需要另行维护和抛弃的过渡版本。

## ADDED Requirements

### Requirement: 三阶段顺序与交付范围

系统 SHALL 按单租户 Kubernetes、多租户及每租户管理界面、统一运营管理后台三个阶段发布，不要求第一阶段先完成外部多租户认证或新运营后台。

#### Scenario: 发布单租户版本
- **WHEN** 阶段一验收通过但 EduPlus2 或运营后台尚未交付
- **THEN** 已认证用户能使用固定租户下已启用的聊天、历史、知识库、附件和管理功能，且不提供未实现的多租户入口

#### Scenario: 后续阶段复用已有数据
- **WHEN** 阶段二绑定外部身份或阶段三上线运营后台
- **THEN** 第一阶段历史记录、用户资源归属及对象引用保持有效，不因外部 ID 绑定搬迁存储

### Requirement: 分批验收不替代完整产品交付

系统交付 SHALL 保留三个业务里程碑并允许按已确认范围分批验收；结构化状态与文件/检索部分通过，不得宣称完整单租户产品可发布。基础运营可先发布，但 MUST 保留治理完善范围且不得提前标记完整运营交付。

#### Scenario: 部分存储实现已通过
- **WHEN** PG 会话或对象接口单独通过测试，但已启用功能尚未全部接通
- **THEN** 仅记录对应工作包证据，不发布依赖缺失的产品或回退本地生产持久化

#### Scenario: 提前准备集成环境
- **WHEN** 首发存储改造尚未全部完成
- **THEN** 可以准备 K8s 集成环境并持续验证增量，外部应用注册和契约准备也可并行，但不因此开放半替换生产版本

### Requirement: 首发即使用最终生产存储

Kubernetes 生产从阶段一 SHALL 使用 PostgreSQL 保存结构化持久状态、S3-compatible 保存文件，所有已启用能力的真实入口及后台任务 MUST 完成替换，不维护生产双写或自动 SQLite/文件回退。对象上传额度的持久化预留、核算及失败释放 SHALL 在阶段一完成，不依赖阶段二 token/并发治理配额。

#### Scenario: Pod 重建
- **WHEN** 原 Pod 和临时工作目录被删除后重新启动服务
- **THEN** 账号、配置、会话、KB、文件及已成功生成的产物仍可访问，在途失败明确可见而非虚假成功

#### Scenario: 持久化依赖故障
- **WHEN** PG 或必要 S3 配置/服务不可用
- **THEN** 相应就绪检查或操作明确失败，不写入本地替代库，也不返回未持久化的成功结果

### Requirement: 每阶段发布门禁与安全切换

发布 SHALL 分别通过 G1 存储/恢复及 Woodpecker 实际交付、G2 首租户接入及多租户隔离/租户管理、G3 运营权限与执行一致性验证。存在旧数据时 MUST 只读导入、验证归属和备份，停旧写后切换；目标产生新写入后不得直接回退旧 SQLite 丢弃新数据。

#### Scenario: 首发单执行副本
- **WHEN** 经业务/运维确认可接受单执行模式且已验证容量与恢复目标
- **THEN** 发布明确非 HA、排空及故障中断行为，不以共享数据库或 sticky session 宣称分布式正确性

#### Scenario: 旧数据切换后回滚
- **WHEN** PG/S3 已接收新业务写入而应用发布需要回退
- **THEN** 使用兼容当前存储版本的应用，或停写后按经演练的成套备份恢复并明确损失窗口，不恢复旧库继续双轨写入

#### Scenario: 首发缺少自动交付
- **WHEN** 业务功能已验证但 Woodpecker 构建、迁移、部署、smoke 或受控晋级未完成实跑验收
- **THEN** G1 仍未完成，不能用手工启动 Pod 或 YAML 校验替代流水线交付

### Requirement: 可靠性门禁独立于租户数量

系统 SHALL 根据明确的容量、可用性和恢复目标选择运行模式；启用多执行者或发布要求 HA 前 MUST 通过 G-H 协调、故障/容量及依赖验证。多租户本身不得被视作必须开启第二 Pod 的充分理由，单租户也不得被视作免除 HA 目标的理由。

#### Scenario: 单租户首发要求高可用
- **WHEN** 第一阶段的已确认发布目标要求高可用
- **THEN** G-H 成为 G1 前置，未通过不得以单副本达到上线日期为由宣称满足目标

#### Scenario: 多租户使用单执行模式
- **WHEN** 多租户容量验证通过且业务/运维明确接受非 HA、维护窗口和恢复语义
- **THEN** 可以按该模式完成 G2，不因租户数量强制增加 Pod，未执行的多副本任务保持未完成并记录扩容前置

#### Scenario: 实际启用多执行者
- **WHEN** 任意里程碑的部署启用多 Pod 或多 worker 竞争执行
- **THEN** 必须先通过跨执行者会话控制、幂等、授权、额度、故障恢复及已确认依赖目标验证，不能仅凭副本数或 sticky session 放行


### Requirement: 企业扩展与通用核心边界

系统 SHALL 优先使用已支持配置、Tool/Capability 和容器/Store 注入，企业集成、PG/S3 与资源服务 MUST 位于独立企业包/应用外壳，缺失处通过必要通用 core provider/scope/权限/lifecycle 及真实调用收敛实现。不得以源码零 diff 为由采用全站运行时 monkey patch、文件/PG 双写或仅代理登录替代完整行为。

#### Scenario: 注入 Store 但存在旁路
- **WHEN** 企业容器已使用 PG，而某启用 API、工具、学习能力或后台任务仍直接访问 SQLite/文件权威状态
- **THEN** 对应验收失败，必须收敛通用调用或接入企业实现，不因聊天主链路通过而完成 A1/G1

#### Scenario: 启动方式或版本绕过企业装配
- **WHEN** 企业部署缺少必需 provider/hook、版本不兼容或使用未装配的默认入口
- **THEN** 启动或接流量前拒绝，不回退 local admin/默认 SQLite；已适配 HTTP/WS/SDK/后台行为仍使用同一权限和存储边界

### Requirement: 保留 LightRAG Server 与完整企业 KB 生命周期

生产默认 SHALL 复用 lightrag-server HTTP 检索和 LightRAG 引擎，企业服务 MUST 补齐 PG/Secret binding、S3 原文/解析物、托管文档导入/状态/引用授权/删除/重建及失败补偿。DeepTutor 保留最终回答职责，不将 only_need_context 当作远端无任何模型成本的保证。

#### Scenario: 连接可用但文档未索引
- **WHEN** Server 探测或导入 HTTP 接收成功，但索引尚未完成或不可查询
- **THEN** 只显示真实连接/任务状态，不能标记 KB 索引 ready 或以此通过 A2/G1；超时先对账远端再幂等重试

#### Scenario: 引用和托管文档删除
- **WHEN** 用户打开检索引用或获授权删除托管文档
- **THEN** 引用通过 PG 映射到 S3 source object 并重新授权；删除先禁止查询，再对远端索引/缓存、对象和 metadata 持久化补偿，完成后不可再召回删除内容

#### Scenario: 解除已有非托管连接
- **WHEN** 用户删除尚未移交企业托管的外部 Server 连接
- **THEN** 仅解除绑定且界面明确语义，不删除远端资料；托管转换先核实所有权/移交，非托管只读连接不代替完整企业 KB 管理验收

#### Scenario: 重建或切换索引
- **WHEN** 更换索引/embedding 版本或从备份重建
- **THEN** 保留稳定 tenant/KB 身份，从 S3/PG 恢复新 index-version 并验证引用/召回后原子切 binding，不依赖原 Pod 路径，也不假定修改后端变量自动迁移旧索引

### Requirement: 检索全状态外置与受管数据库防线

LightRAG 的 KV、vector、doc_status 和 graph MUST 持久化到受管 PostgreSQL，文件 source of truth SHALL 在 S3。系统 MUST 锁定并验证 Server/图后端及其低权启动、迁移、数据库强制隔离和恢复；不得将可变主分支能力视为已部署支持，或将 workspace 参数当作应用 RLS。

#### Scenario: 只有向量使用 PG
- **WHEN** 向量在 PG 但文档状态、KV 或图仍依赖临时 JSON/Nano/NetworkX 文件
- **THEN** G1 不通过，不能通过给 DeepTutor Pod 外置一个仍依赖临时盘的 Server 转移数据丢失风险

#### Scenario: 跨 workspace 数据库访问
- **WHEN** 检索运行身份误读写未授权 workspace，或试图访问 DeepTutor 私有业务表
- **THEN** 受管 RLS/图权限及数据库授权拒绝；应用/检索迁移角色与运行角色分离，不能仅靠网关过滤或高权连接声称隔离

#### Scenario: Server 临时目录丢失或索引服务故障
- **WHEN** Server scratch 被清空、进程重建或必要检索依赖故障
- **THEN** 已持久化资料和引用按确认目标恢复，失败导入可对账；当前查询明确报错，不回退默认 workspace、其他 KB 或本地索引冒充成功
