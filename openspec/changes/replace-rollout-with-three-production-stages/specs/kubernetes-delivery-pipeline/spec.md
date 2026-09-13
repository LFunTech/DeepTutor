## Purpose

规定 DeepTutor 通过 Woodpecker 向 Kubernetes 安全交付的能力，作为 M1/A3 必交付子环节从 A1 并行开发，并在后续里程碑和 upstream 更新中复用。不把方案文件存在视为流水线已经实现或集群已经部署。

## ADDED Requirements

### Requirement: 首发包含实际流水线交付

M1 发布 SHALL 完成 Woodpecker 的质量检查、生产镜像构建、推送、迁移、Kubernetes 部署、业务 smoke 和发布记录闭环。准备 MUST 从 A1 并行开始，A1/A2 未完成时仅允许集成验证，不发布半替换生产版本。

#### Scenario: 只有配置文件通过语法检查
- **WHEN** 流水线 YAML 可解析但目标 agent、registry、集群或业务 smoke 尚未实跑
- **THEN** 只能记录配置检查，不标记流水线交付或 G1 完成

#### Scenario: 完整首发交付
- **WHEN** A1/A2 及其他 G1 要求已满足且生产发布获批准
- **THEN** 目标 Woodpecker 从已验证制品完成迁移、生产部署和隔离 smoke，记录证据后才认定完整 G1/M1 并开放普通业务流量；首次部署不以尚不存在的生产成功记录作为前置

### Requirement: 生产镜像与质量门禁匹配真实架构

流水线 SHALL 复用现有必要质量检查并新增真实 PG/S3 及已交付阶段回归；生产镜像 MUST 支持独立前后端启动、受控配置/Secret 与临时 scratch，不依赖本地 JSON/SQLite 权威状态。已启用的沙箱或执行组件 SHALL 纳入制品清单。

#### Scenario: 配置入口未适配
- **WHEN** 镜像仍覆盖所需生产配置或依赖本地 settings 作为权威
- **THEN** 镜像集成验收失败，不因容器能启动就部署正式生产

#### Scenario: 必需检查失败或缺失
- **WHEN** 发布候选缺少必要测试、迁移/PG/S3 集成或受影响范围门禁
- **THEN** 阻止晋级，不能用跳过、可忽略失败或 SQLite fixture 代替生产后端验证

### Requirement: 不可变且可验证的制品晋级

发布 SHALL 构建一次并按 digest 晋级，生成绑定源码/upstream SHA、各镜像、清单/配置版本、schema/对象格式和运行模式的防篡改发布记录。跨 workflow MUST 通过可信制品存储传递记录，不假定共享本地工作目录；生产不得通过 latest 或同 SHA 重新构建替换已验收制品。

#### Scenario: 生产晋级
- **WHEN** 请求将已通过测试的候选发布到生产
- **THEN** 校验可信来源、digest、测试和批准绑定，使用相同制品而非重新构建

#### Scenario: 制品记录被替换
- **WHEN** 发布清单缺失、被篡改或镜像/证据摘要不匹配
- **THEN** 在集群写入前失败，不通过可变 tag 猜测目标版本

### Requirement: 发布授权与凭证隔离

流水线 MUST 在服务端建立可信来源和生产批准边界，绑定执行人、环境、制品与有效期；PR 可修改的 YAML 不能作为唯一授权。PR/非受保护来源 SHALL 无生产或镜像发布凭证；构建、部署、应用与迁移身份 MUST 分离，使用环境最小权限且不得泄露 Secret 或共享个人 cluster-admin 凭证。

#### Scenario: 伪造发布请求
- **WHEN** 非受保护提交、任意 tag、未批准请求或修改后的环境/digest 尝试部署
- **THEN** 在获取生产权限及写集群前拒绝，单独 branch 条件或 manual 事件不能视为已批准

#### Scenario: CI 无法隔离生产权限
- **WHEN** 当前 Woodpecker/托管平台不能防止普通贡献者通过修改 workflow 获得生产凭证
- **THEN** 使用受保护交付仓库或等效服务端授权后才配置生产权限，不能降低信任边界以提前上线

### Requirement: 迁移与发布互斥和中断恢复

部署与回退 SHALL 共用环境级互斥和当前版本校验，并阻止旧构建覆盖新版本；发布中断后 MUST 对账实际 Job/rollout 才恢复。PG 迁移 SHALL 使用匹配候选版本的独立 Job、专用角色、数据库锁、历史和幂等检查；失败阻断新应用部署，不在每个 Pod 启动时并发迁移。

#### Scenario: 迁移失败或重复请求
- **WHEN** 迁移 Job 失败、超时或被重复触发
- **THEN** 按版本历史确认真实状态并阻断失败发布；已完成版本不重复修改，不自动降库/删除对象或盲目重试副作用

#### Scenario: 并发和旧构建
- **WHEN** 两个请求部署同一环境或旧构建在新发布后到达
- **THEN** 同时只允许一个发布写入，旧构建未经显式回退批准不得覆盖当前版本

#### Scenario: agent 在迁移或部署时失联
- **WHEN** CI 进程结束但实际 Job/rollout 状态不确定
- **THEN** 保留发布记录并对账，未确认旧操作停止前不能仅凭锁超时放行另一次发布

### Requirement: 更新过程遵守实际执行者门禁

流水线 SHALL 根据已确认运行模式验证更新策略。单执行模式 MUST 排空并确认旧执行者终止后才启动新执行者；实际竞争执行或要求 HA 的发布 MUST 先通过适用 G-H，不能只验证稳定时 replicas 数量。

#### Scenario: 单副本更新产生临时重叠
- **WHEN** 未通过 G-H 的配置可能在更新期间同时运行两个执行者
- **THEN** 拒绝该更新方式，采用经验证的停旧启新与维护窗口，不因 replicas 等于一而放行

### Requirement: 业务验证与安全回退

发布 SHALL 通过真实 Ingress 的认证、HTTP/WS turn、持久化资源及当期管理功能 smoke；故障或关键证据缺失不得标记成功。回退 MUST 校验应用与当前 PG/S3/权限状态兼容，复用授权、环境锁及 smoke，不自动回滚数据库或退回旧文件存储。

#### Scenario: rollout 成功但聊天失败
- **WHEN** Pod Ready 但真实 WS turn、文件授权或当期必需业务 smoke 失败
- **THEN** 发布失败，保留证据并按兼容条件受控恢复，不能仅凭健康接口返回成功

#### Scenario: 数据版本不允许旧应用回退
- **WHEN** 应用发布失败且已写入新 schema/对象格式
- **THEN** 无兼容版本时保持受控维护，批准前向修复或经演练的成套恢复并声明损失窗口，不盲目降库或丢弃新写入

### Requirement: 后续里程碑复用并保留完整证据

B1/B2/C1/C2 与 upstream 合并 SHALL 复用同一制品、迁移和发布流程，执行已交付范围与适用 G-H 回归。证据 MUST 可追溯批准人、环境、源码/镜像/存储版本、检查结果和回退状态，失败通知不得覆盖原失败结果。

#### Scenario: 官方更新后的多租户发布
- **WHEN** 已完成 M2 的版本合并官方更新并发布
- **THEN** 原 G1/G2 和适用 G-H 必需验证继续生效，不能只跑上游默认 SQLite 测试或绕过 Woodpecker 发布入口


### Requirement: 企业包和检索服务组合制品与迁移

发布 SHALL 固定并验证 core/通用补丁、企业包/依赖锁、前端/企业 UI、RAG Gateway/文档 worker、LightRAG Server 镜像/API/图后端及 schema/object/binding 版本。应用与检索权限/索引迁移 MUST 受控编排并验证低权运行，不依靠原版 Server 启动时高权自动建表替代版本化 Job。

#### Scenario: 扩展包或检索版本不兼容
- **WHEN** 企业包缺少所需 core seam 或 LightRAG 镜像不包含选定图后端/接口
- **THEN** 组合预检/验收失败并阻止晋级，不动态降级文件后端或以升级 main/latest 临时绕过版本锁

#### Scenario: 组合备份恢复与业务 smoke
- **WHEN** 发布、回退或演练恢复 core/企业包/LightRAG 组合
- **THEN** 核对应用 PG、检索 PG/图、S3 与 binding/index-version 一致，真实通过企业入口的导入/索引 ready/召回/授权引用与隔离资源删除，记录 RPO/RTO 及重建成本限制，而非仅探测 Server 可达
