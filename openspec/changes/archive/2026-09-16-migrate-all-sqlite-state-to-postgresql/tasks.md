# 全量 PostgreSQL-only 实施任务（实施中）

用户已确认取消 local/SQLite 兼容；[proposal](proposal.md)、[design](design.md) 与三个 [specs](specs/) 是本 change 的完整验收范围。[inventory](inventory.md) 登记所有已知直接/间接路径。任务是实施检查点，不是减少范围；不得在仅默认 chat 或某个 Store 通过后停止。

2026-09-14 用户批准在当前 master 工作区实施，保留已有修改、不提交或推送。设计/规范已评审；先失败测试再实现并接通真实调用，实际验证后才勾选。数据库变更使用现有版本化 runner 和隔离 PG；不对用户原库运行、不读取模型密钥、不提交/归档，除非另获相应授权。

真实模型验收授权补充：用户已指定 `.secrets` 内配置，并明确本次最高调用次数与供应商费用“暂时不设上限”。到 2.5 阶段按必要验收用例执行并逐调用记录用量，不输出密钥；本授权不包含真实数据 cutover、发布、提交或归档。

## 1. A1：全量 SQLite 状态退出与默认 PG-only

### 基线与通用底座

- [x] 1.1 冻结直接/间接 SQLite 与调用方 inventory、默认页面/API/WS/CLI/SDK/工具/后台能力矩阵；加入 Matrix 普通/E2EE、只读探针和可选 SDK，登记准确源码/依赖版本，不以首切片白名单缩小基线。
- [x] 1.2 建立真实 PG 测试 fixture 与逐域行为契约；记录现有 SQLite 行为作为迁移基线，业务 PG 测试禁止用 SQLite/内存库替身，保留旧格式 fixture 在独立导入测试。
- [x] 1.3 将现有 PG 连接/事务/scope 提取到 core 通用模块，补同步/异步池的有界执行及显式 scope；真实 PG 验证复用、错误权限、超时/取消回滚和线程隔离。
- [x] 1.4 下沉 schema runner/SQL 资源并保留 schema 1 字节/checksum/历史与所有 ID；验证空库和已有首切片数据升级、并发、真实 catalog 漂移与失败回滚，无第二套身份/会话库。
- [x] 1.5 复用 PG identity、会话和执行生命周期，企业模块改为消费同一 core 实现；旧 import 仅兼容转发，测试 core 无企业反向依赖及组合版本/hook/schema 不兼容拒绝。
- [x] 1.6 实现默认 PG 配置/Secret 引用、canonical 字段及企业显式适配；验证冲突 DSN、缺配置、SQLite/PocketBase/backend 值拒绝、错误脱敏、无 .env 自动发现或隐式数据库生成。

### 默认身份与入口

- [x] 1.7 将默认认证/用户上下文接到 PG 身份，接通原登录/状态/退出及受控账号/bootstrap CLI；验证无认证 admin 关闭、密码/撤权/世代、重复初始化不覆盖/提权、当前角色和个人 owner 边界。
- [x] 1.8 默认 Web/API lifespan 和启动器装配完整业务 provider；移除自动旧库迁移，缺 PG/schema/执行权先于模型/后台副作用失败，原 API/WS 路由及已有 capability 不缩为 chat-only。
- [x] 1.9 默认 CLI 业务命令接通 PG 配置和可信主体，保留 run/chat/其它子命令及受控远程控制；验证帮助/版本无连接、业务必需 PG、已有服务执行锁竞争和认证/退出清理。
- [x] 1.10 SDK 默认容器、显式 provider 与惰性服务接通 PG，支持受控独立执行/远程服务模式；验证上下文退出/残留对象不回退、缺身份拒绝、与 HTTP/CLI 数据及权限一致。

### 会话与题库全链路

- [x] 1.11 追加 PG notebook_entries/categories/entry_categories 及会话领域所需约束迁移，覆盖原字段/搜索/排序/去重/引用；真实 PG 验证复合 FK/RLS、同 ID/owner 和失败回滚。
- [x] 1.12 实现 PG 条目/分类增删改查、过滤/分页/统计/搜索、答题写入与导出，保留整数 ID/DTO/冲突语义；验证并发修改与删除引用。
- [x] 1.13 收敛 question_notebook/quiz-results/imports 路由、question_bank 工具、question history 和工具自动装配到 PG provider；从原前端/API/真实工具入口跑正负例，不返回假空数据。
- [x] 1.14 收敛 book inputs/router、courses_state、topic_materials、mastery tools 和 cron 会话消费者；覆盖图书/课程/学习引用、计数/导出与相应文件载荷，移除直接 SQLite 工厂。
- [x] 1.15 补齐首切片未开放的现有会话资源/课程关联与删除 provider，恢复默认完整行为；验证删除/新派发/跨域关联互斥、外部载荷失败语义及无悬空可读记录，保留纯会话全部回归。

### 学习与阅读

- [x] 1.16 追加 PG mastery path/session/interaction/event/lease/topic meta/source 迁移和领域 Store；真实 PG 验证 schema/索引、CAS、事件顺序/租约和 owner 隔离。
- [x] 1.17 接通 mastery/learning 的 API/工具/事件 hub/后台恢复和课程关联；验证交错回复、断线重放、删除、进程退出/恢复无旧交互重跑，旧 v1/v2 数据迁移不再由运行构造器触发。
- [x] 1.18 追加 PG reading materials/workspaces/tabs/sessions/links 迁移与目录接口；覆盖唯一/排序、外部材料引用、并发版本和跨 owner FK 拒绝。
- [x] 1.19 接通 reading API/SDK/工具、reading/store 的直接读取及工作区恢复；以原页面/业务入口验证材料与标签页保存/删除/重开、引用载荷完整，无 `_catalog.sqlite3` 读写。

### 调度与渠道

- [x] 1.20 追加 PG cron schedule/meta/execution 状态迁移并实现 repository，保留 at/every/cron 时区与启停/下次执行；验证原子领取、时间边界、CAS/幂等和任务 owner。
- [x] 1.21 接通 cron service/executor/API/CLI/tool/后台，移除运行期 jobs.json→SQLite 初始化；覆盖暂停/删除与派发竞争、重启、不确定外部结果待核对及不盲目重发。
- [x] 1.22 追加并接通 PG Partners runtime status，显式 partner/tenant/owner/worker/version/TTL；验证 leader/reader、过期状态、旧 worker 写拒绝、跨用户查询和后台重建。
- [x] 1.23 锁定实际 Matrix nio/libolm 精确版本并实测完整存储协议/线程模型；列出账户/会话/设备信任/房间/同步 token/密钥字段与加密边界，不只测试 next_batch。本项通过是 1.24–1.26/1.36 的硬前置，未通过不得冻结 schema 或宣称适配可行。
- [x] 1.24 实现 Matrix PG schema/store adapter、独立 Secret 加密与设备归属；验证加密序列化、密钥/信任保存加载、坏密钥/权限/版本失败、无默认 pickle key/SQLiteMemoryStore。
- [x] 1.25 接通 Matrix 客户端专属 worker 与 runtime 事件交接，处理同步存储边界和提交后游标；验证主循环不阻塞、线程归属、取消/关闭、PG 故障停止同步而非吞错。
- [x] 1.26 在隔离受控 Matrix 服务验证普通和 E2EE 收发/重启/设备信任/旧消息解密/防重复；所有存储走真实 PG 且禁用 SQLite，不以取消 E2EE 或新设备重配通过。

### MarginNote 与只读消费者

- [x] 1.27 追加 PG MarginNote objects/devices/cursors/tombstones 迁移和 Store；覆盖 tenant/owner/KB/device 复合约束、token hash、搜索/批次与游标原子性。
- [x] 1.28 接通配对/同步/搜索/撤销/删除 API、知识库与能力入口，退出运行 db_path 参数；验证重复/失败批次、旧游标、撤销设备、同 ID/跨 KB 及载荷/引用一致。
- [x] 1.29 将 Memory read_chat/read_quiz/probe 与后台快照/增量消费者改用 PG 查询，移除文件时间戳驱动和只读 SQLite；验证版本/删除、授权、稳定分页及新 PG 数据不漏读。

### 离线导入与切换工具

- [x] 1.30 实现 design 固定的源端停写/Backup API 独立快照与 manifest 协议、版本化引用字段注册表和离线 plan/source-check；验证 freeze/哈希/sidecar/只读制品、未知版本/缺映射/坏数据拒绝，manifest 声明必需但缺失 WAL 或快照仍依赖 WAL 时拒绝；源主库/WAL 权威内容不变、SHM 瞬态读协调单独记录且不修源。
- [x] 1.31 追加独立 migration_stage schema、批次/映射/进度账本与维护门禁；运行角色无 staging 权限，实现分块/取消恢复及跨全部领域单事务 promotion、按批清理，真实故障验证无部分可见，所有业务入口维护拒绝。
- [x] 1.32 实现源/目标重复整数与文本 ID 稳定映射、parent DAG 拓扑分配与 GENERATED ALWAYS 导入/sequence 推进；按 inventory 字段图重写结构和 typed JSON 引用，不全文替换；验证两用户同 ID、目标已有数据、重试一致、坏引用/未知机器引用拒绝与旧链接报告。
- [x] 1.33 实现会话/消息/事件/题库/分类 SQLite 导入与各域验证；保留分支/摘要锚点/metadata/时间/排序，旧 token 不导入，未知用户保持禁用/受控映射，源字节不变。
- [x] 1.34 实现 mastery v1/v2、阅读目录与跨域链接导入，统一走已有映射/批次；验证正文/source/工作区排序/CAS 版本、坏引用及不同来源重复库的拒绝或去重。
- [x] 1.35 实现 cron/Partners 状态和 MarginNote 导入/可重建投影策略；验证时区/启停、运行中任务不自动重发、设备撤销、游标/删除标记和目标已有更新不覆盖。
- [x] 1.36 实现 Matrix 旧 store 的离线迁移与独立 Secret 映射，完整保留加密状态/设备信任/同步位置；测试错误密钥、源变化、目标设备冲突与旧快照恢复后撤销核对。
- [x] 1.37 实现 PocketBase 受控只读 exporter/manifest，覆盖本应用实际 collection/schema 与文件清单；验证停写/版本、稳定分页、缺权限/源变化拒绝和凭证不落制品，不改写或删除远端服务。
- [x] 1.38 实现 PocketBase 离线 PG importer，复用 staging/归属与字符串 ID→PG 整数映射；验证 users 映射/凭证重置、会话/事件/文件引用、幂等/坏数据及与 SQLite 来源混合批次无冲突。
- [x] 1.39 实现 verify/report 的每源/owner/域计数、内容摘要、全引用和语义验证；测试行数相同但关系/时区/密钥错误时阻断，失败/未知记录不静默跳过。
- [x] 1.40 实现受控 cutover 与回退检查：停全部 writer、目标维护/批次就绪/外置身份世代确认后开放；分别测试旁路新 PG 与 schema 1 原地升级回退矩阵，PG 新写后禁止回 SQLite/PocketBase、账号/设备撤销不复活及外部动作不自动重发。

### 删除旧运行路径与回归

- [x] 1.41 删除默认 SQLite/PocketBase backend 选择、直连工厂、构造器 DDL/旧自动迁移与运行路径依赖；SQLite 代码仅隔离于离线 importer/旧格式 fixture，提供明确弃用错误而非静默路径兼容。
- [x] 1.42 移除本应用不再需要的 aiosqlite 直接依赖与运行配置，核查 SDK/plugin 的传递默认存储、C/native 和子进程路径；每一残余 SQLite 引用分类并证明不在业务运行图。
- [x] 1.43 增加新进程/子进程零 SQLite 访问测试，覆盖完整默认入口、全部清单域和 Matrix 普通/E2EE；文件与 `:memory:` 都拒绝，离线导入测试不扩大业务白名单。
- [x] 1.44 重跑首切片全部 PG/身份/会话/恢复与已受影响 core 功能测试，将旧 local 无 PG 预期改为新契约；记录删改测试理由，不通过略过功能测试实现“全绿”。
- [x] 1.45 对各域执行双租户、同租户普通用户/管理员全入口矩阵与数据库直接越权负例，验证 cache/连接复用、后台/导出、撤权和审计脱敏；不宣称正式多租户已开放。
- [x] 1.46 在隔离 PG 演练完整导入中断重跑、pg_dump/restore、进程/scratch 重建与受控恢复，验证引用/身份/设备/计划/不确定副作用，记录实际范围与耗时而非假定 RPO/RTO。
- [x] 1.47 按 [K12 容量评估 v1](capacity-assessment.md) 的 P1（3,000 学生/7,800 账号/一学年存量）及重度尾部验证查询/导入批量、p95/p99、池等待、内存与维护窗口；区分目标与实测，不用无界 fetch-all、缩小数据集或 SQLite fixture 掩盖 PG 退化。

## 2. A3：默认制品与全量验收交接（不是完整 G1）

- [x] 2.1 更新 root 与 CLI-only 打包、requirements/SQL 资源、core/企业兼容版本，构建并在新环境安装两个 wheel；验证未安装企业包的默认 PG 业务与企业组合入口。
- [x] 2.2 更新默认 README/CLI/SDK 示例、数据库/身份 bootstrap 与 schema/import runbook、开发/测试/容器入口；明确无 PG 业务不可运行，DSN 只在后端/受控进程，不把密钥写入前端或示例。
- [x] 2.3 将受影响 CI 业务测试改为临时受限 PG，保留独立只读迁移 fixture；验证失败数据库/schema/权限/默认配置均不回退，测试任务不连接用户共享库。
- [x] 2.4 从最终安装制品启动默认 Web，执行页面/API/WS 的会话/题库/学习/阅读/导入/删除业务 smoke；同时验证 CLI、CLI-only、SDK 和后台读到一致 PG 状态及权限，不能仅测试企业专用入口。
- [x] 2.5 在明确授权 Secret、调用数和供应商预算后执行默认 Web/WS、CLI/SDK 真实模型与受影响教学工具 smoke；逐调用先落盘 usage/失败/缺失记录，不以 mock 或 max_tokens 估算代替完整费用证据。
- [x] 2.6 完成最终范围/依赖/代码审查及适用单元/集成/格式/类型/构建检查；逐 inventory 和 spec 核对功能无缺失，无 SQLite 旁路或假数据，真实服务未验证项保持未完成。
- [x] 2.7 记录迁移 manifest/report、版本/制品、实际入口/正负例、容量/恢复与模型/Matrix 验收证据；同步企业文档和规范替代清单，运行 change/all strict，不因本 change 完成勾选剩余 A1/A2/G1。
- [x] 2.8 提供可审核切换/回退手册及规范收敛顺序，明确默认启动兼容破坏与旧 local 要求已被替代；真实数据 cutover、发布、commit 和 archive 继续需要各自授权，本项仅验收制品与操作说明。

## 3. H 与其它工作包交接

本 change 不新增 H 多副本交付。所有 CLI/SDK、cron、Partners/Matrix writer 复用当前单执行登记，未完成 G-H 不启用多执行者；测试并发正确不等于 HA。A2/S3/LightRAG/HugeGraph、B1/B2、C1/C2 和完整 A3 流水线仍按总纲独立推进，不变成完成本清单的隐式已交付项。

## 4. 规划与实施状态

本清单共 55 项实现/验收任务，当前已进入实施，进度仅以实际勾选及[验证证据](execution-evidence.md)为准。原首切片 34/34 保留为旧范围事实，总纲 90 项编号/checkbox 不变。规划完成只表示文档可评审，不代表默认应用已经取消 SQLite。
