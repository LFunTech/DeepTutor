## Context

动机与批准范围见 [proposal](proposal.md)，当前调用依据见 [inventory](inventory.md)。首个切片使用 `psycopg` 异步池、受限身份、`enterprise` schema 1、迁移 checksum/catalog 校验、固定 tenant、PG 身份/会话和执行锁；默认 core 仍有 SQLite/PocketBase factory，企业仅提供文本 chat 路径。

此前“默认 local 不需要 PG”的要求已被用户明确撤销。旧零配置用法不能作为本次回归的通过标准；原功能与数据语义仍是基线。本 change 是全仓数据库运行契约调整，不是把所有入口转到现有 chat-only 企业外壳。

## Goals / Non-Goals

**Goals：**
- 所有由本仓库支持的 SQLite 业务状态及间接渠道状态退出运行；默认 Web/CLI/SDK 与后台同一 PG 数据与可信身份边界。
- 原业务能力完整可用；版本、幂等、并发、事件、权限和恢复不因 SQLite 到 PG 的语法替换而降级。
- 不复制已验收 PG 基础；提供可重跑且默认不接触用户存量的迁移、切换、验证和回退制品。

**Non-Goals：**
- 不取消本机部署、CLI、SDK、已有高级能力或 Matrix E2EE；取消的是 SQLite profile。
- 不在 PG 保存整份 `.db`，不把 SQL 转成文件/JSON/内存权威以绕过检查。
- 不迁移外部独立服务内部数据库、不重写图/检索引擎。S3/图与尚未涉及 SQLite 的 JSON/Markdown 全量替换仍在 A1/A2，不以“本 change 完成”宣称全量无本地文件或 G1 通过。
- 不自动对真实旧数据执行导入，不启动模型计费/共享基础设施变更，不在本次规划归档旧 change。

## Decisions

### 1. 一个 PG 实现，下沉通用基础而非反向依赖企业包

推荐把已经存在的连接/事务、scope、schema runner、PG 身份/会话及可复用执行生命周期提取到 **`deeptutor/persistence/postgres/`**，业务接口保持原领域模块/provider；企业包消费此核心实现，附加固定部署/外部身份/治理策略。core 默认发行依赖 PG driver，CLI-only 包同样包含。源码 import 和 `--help` 不创建连接池；生命周期启动时建立并关闭池。

保留现有 `enterprise` schema 和 schema_history、表/角色/ID；命名是兼容细节，不因模块迁移重命名整个库。已有 `0001` SQL 字节/checksum不变；新领域走追加迁移，旧企业 import 路径仅允许转发到同一实现，不能保留副本。core hook/企业版本组合显式升级并实测；旧构建遇到新 schema 按兼容窗口拒绝，而非通过伪造版本运行。

考虑但不采用：
1. core 默认依赖 `deeptutor_enterprise`：产生反向职责/循环打包耦合，并把默认产品锁死在 chat-only profile。
2. core 新写另一套 PG 库、企业保留旧库：复制身份、schema 和语义，跨入口数据分裂。
3. 长期保留可切换 SQLite/PocketBase：与用户明确要求冲突；仅允许离线源工具读取旧格式。

### 2. 默认组合根与配置契约

建立 core PG composition：接入现有 ApplicationContainer/provider/领域协议，提供完整默认路由和能力目录，而不是直接调用企业白名单 router。默认 Web/API lifespan、启动器、CLI 和 SDK 工厂必须消费同一配置契约：

- 服务进程使用显式只读配置对象/文件中的 PG 配置和 Secret 环境变量引用；canonical DSN 引用为 `DEEPTUTOR_DATABASE_URL`，迁移单独使用 `DEEPTUTOR_MIGRATION_DATABASE_URL`。两者的值均由环境/Secret 提供，不写入 settings 或日志。现有企业 `DT_DATABASE_DSN` 等经显式适配解析；同时配置且不一致时拒绝，不能按导入顺序选库。
- 必需项包括 deployment tenant、受限数据库身份、可信身份签名/恢复世代与池/超时参数。保留 schema 1 的 tenant UUID、用户 ID 与账号准入逻辑；无默认全局 admin、无 `AUTH_ENABLED=false` 旁路。原本地登录换成 PG 认证，页面/CLI 通过受控 bootstrap 建立主体，不公开抢注管理员。
- `DEEPTUTOR_STORAGE_BACKEND` 若保留兼容字段，只接受 `postgres`；SQLite、PocketBase 或旧目录-only 配置报告可操作的升级错误。SDK 允许显式注入 PG provider，不允许文件型生产 provider。
- CLI/SDK 可在独立进程直接装配 PG 执行者，须取得原执行锁；当已有服务执行者时使用认证远程控制方式，不擅自起第二 writer。CLI 控制台不返回 DSN/token；远程模式实际数据库连接由服务持有，客户端不需要数据库凭证，但不存在无 PG 的业务模式。
- `--help`/`--version`、纯 import、schema plan 和离线只读源检查可在无业务运行连接时使用。纯静态前端不连接数据库；所有业务 API/WS 在 PG 预检通过后提供服务。

### 3. 全领域 provider 与事务边界

各域保留公开 DTO 和调用语义，新增领域级 PG repository；禁止机械替换 `?` 为 `%s` 后把所有 SQL 拼接成通用代理。tenant/owner/资源复合键、RLS/FORCE、最小权限与实际 catalog 校验沿用首切片。

- SessionStore 补 notebook_entries/category 及附件/课程/学习关联契约；移除 PG 首切片对当前可用关联的临时拒绝，补相应 provider 后接回真实业务。原纯会话安全边界仍保留。
- LearningStore 的路径、交互、事件、topic source 和租约在事务中做版本 CAS；事件发布晚于 commit，恢复不自动执行旧问题或模型。
- ReadingCatalog 的材料/工作区/标签页/会话/链接以 owner+稳定资源 ID 关联；唯一与排序契约逐项保留，`reading/store.py` 不能保留只读 SQLite 查询。
- Cron 用持久 schedule/状态版本和原子领取，基于时区计算下次执行，重启恢复/暂停/删除与运行中变更均回归。PG 原子性不能被宣称为外部副作用 exactly-once；派发结果不确定时记录待核对，不能盲目重发渠道消息。
- Partners runtime status 是可重建投影，但仍存 PG；通过可信 partner owner 映射限制读取，过期明确，不能让旧 worker 覆盖新状态。
- MarginNote 对象/device/token hash/cursor/tombstone 的写入与游标推进同事务；查询、配对、撤销、删除、增量同步全部复验 KB/owner。旧 metadata 的 db_path 只供源解析，不再决定数据库位置或授予归属。
- Memory 快照/quiz probe 改为同一 PG 查询和稳定分页/版本游标。删除在快照中可见，管理员不能借后台枚举读取私人内容。

async 业务使用池内连接和显式事务。确需同步公开方法时，使用有界同步 PG 池并在异步调用端以线程执行完整单位操作；事务/连接不得跨线程、跨任务共享，不在 event loop 阻塞或嵌套 `asyncio.run`。同步/异步池均接受显式不可变 scope，事务结束清理，不能依赖线程残留 ContextVar。

### 4. Matrix 与 SDK 隐式存储

提供符合锁定 nio `MatrixStore` 协议的 PG adapter，覆盖账户/Olm/Megolm 会话、设备信任、房间与同步 token 等实际版本要求；PG记录以 tenant/partner/Matrix user/device 归属。密钥 pickle/敏感数据使用独立 Secret 支持的加密封装和版本，不使用默认 pickle key、不在日志/导出暴露。**task 1.23 的精确版本锁定、协议/线程模型验证是 1.24–1.26 及 Matrix 数据导入的硬前置**，未通过不能冻结其 schema 或声称适配已可行；存储协议与线程方案若实测冲突，先修订设计评审，不静默换算法/禁用加密。

nio 的同步存储回调由专属有界客户端 worker 执行：该 worker 独占客户端和必要事件循环，PG同步接口只阻塞此 worker；向主 runtime 发事件通过线程安全队列并在确认业务持久化后推进已处理游标。业务回调不得在错误线程执行共享 runtime。不能以禁用 E2EE、内存 SQLite 或每次重建设备身份作为替代。

PG 存储故障停止同步/派发并报告未确认结果；设备/会话状态恢复和密钥轮转要保持解密及信任正确，不能只恢复 next_batch。版本锁定和受控 Matrix 测试服务是必需验收，当前缺少本机 libolm 不构成删除任务的理由。

### 5. 可信身份、导入 ID 与关系

来源由显式 manifest 标识：source ID/fingerprint、SQLite schema 版本、获授权只读快照、固定目标 tenant、旧用户/资源到目标 owner 的映射。文件路径、用户名相同或管理员角色都不自动产生所有权。无映射或冲突的项目隔离并使整批验证失败；不静默归 admin。

已有 PG tenant/user/session ID 不重写。旧 SQLite message/notebook ID 在不同用户库中可重复；在导入 staging 中生成一次性稳定映射，保留整数接口，所有 parent/summary/turn/notebook/reading/learning/图书等引用整体重写。文本 session ID 冲突也使用账本映射，不覆盖现有 PG 数据。迁移报告列出旧→新标识；实际旧链接需要通过受认证的源映射解析或明确迁移告知，不能把多个来源相同 ID 随机路由到一个用户。

PG sequence 在导入后推进并做新写冲突测试。首切片存在 `parent_message_id < id` 与 `GENERATED ALWAYS AS IDENTITY`：消息 ID 按 parent DAG 拓扑分配，稳定排序以原创建时间/原 ID 打破同层并列；有环/缺父拒绝。在目标维护锁内先预留不冲突 sequence ID，迁移角色以 `OVERRIDING SYSTEM VALUE` 显式导入，空洞允许但不能重复，最终将 sequence 推进到已占用上界。不能按各源旧数字大小直接混排破坏 parent 约束。

字段级引用分类见 [inventory](inventory.md#6-导入引用图与重写规则)。结构字段/已定义 JSON 路径通过版本化解析器重写；未知自定义 metadata 与普通文字保持原样，疑似未分类机器引用标为待核对并阻断受影响批次，不做全文 ID 字符串替换。原创建时间/排序、JSON含义与事件序号保留；坏记录逐项报告。账号仅经可信 manifest 映射或受控创建；不导入旧 token/认证会话，凭证默认重置/禁用后再确认启用，沿用外置认证世代。

### 6. 迁移与运行两条入口，保留一条历史

schema `plan/apply/verify` 复用现有 runner，迁移角色和运行角色分离；版本互斥、checksum和实际表/索引/RLS/FK/触发器校验必须覆盖新增域。启动仅 verify，不在构造函数 DDL，也不调用旧 mastery/session/cron 自动搬文件逻辑。

离线导入提供 `plan/import/verify/report`（具体 CLI 子命令在实施中按现有 Typer 层级接入），与业务服务/后台进程隔离。**采用独立 `migration_stage` schema + 最终单事务 promotion**，不让每个业务表各自发明可见性规则：

- 独立迁移角色创建/使用 staging 表与 batch/source manifest/ID映射/进度；运行角色没有此 schema 的 USAGE/SELECT/DML。staging 每行带 batch ID、目标 scope，包含所有领域的目标形态；支持分块导入并校验对应约束/引用。
- 目标先停业务并进入数据库持久维护态，导入/执行互斥覆盖默认/企业/CLI/SDK/后台。获准操作者不能用原地 schema 1 旧进程绕过门禁，必须确认所有原 writer 已停止。
- 全量验证后，在同一目标 PG 事务中按依赖顺序 `INSERT … SELECT`，仅对声明可延期的循环 FK 延后检查；跨域引用与目标冲突复验，最后原子更新 batch 为 published。事务失败全部回滚，业务角色既看不到 staging，也看不到部分正式记录。promotion 不分多个发布事务；有界分块用于准备数据，不能牺牲原子可见性。
- published 不等于自动开放登录：核验身份/渠道安全与最终报告后，单独受控 cutover 释放维护态。清理只按 batch 删除已结束 staging，失败账本保留；不删除正式目标或其它已完成批次。

大批量 promotion 是明确的维护窗口/PG WAL 成本，先记录数据量/时长/磁盘阈值；无法在获批容量内完成须调整窗口或经设计评审，不静默改成部分可见。相同源重试复用结果，不覆盖切换后的 PG 更新；源改变须新审核批次。

**支持的 SQLite 快照协议固定为独立备份制品，不接受直接把活动 `.db` 路径当导入源：**

1. 由获授权源端操作者停止全部 writer，并生成统一 freeze ID（部署/进程停止证明、时间、源清单）；同一批相关库共享停写窗口。源端工具以只读连接通过 SQLite Backup API 生成新的独立快照；只写新目标制品，不执行源 checkpoint/VACUUM/旧格式升级。无法只读打开或确认停止则失败，不自动修源。
2. 备份目标关闭/完成后检查独立快照没有未归并的 WAL 依赖，记录 producer/SQLite 版本、源库及存在的 WAL/SHM 哈希/大小、快照文件哈希/大小、schema/表计数、完整性结果；快照以只读文件制品交付。源主库/WAL 权威内容前后哈希不变；SHM 作为已登记的非权威读协调 sidecar 记录前后值，不能把正常只读连接的瞬态读标记变化当作业务数据改变，也不允许手工修改/重建它来修复源。backup 不完整、writer重启或权威源变更均拒绝这一批。
3. importer 仅接受该 manifest 对应制品，拒绝符号链接/路径逃逸、未知或缺失文件、未声明 sidecar、哈希变化和直接活动源。验证前后哈希一致，并以 `mode=ro&immutable=1` 读取已确认不可变且无 WAL 依赖的快照；不能用 immutable 绕过活动源的锁。源端停止证据是受信任操作记录，单次 `integrity_check` 不能证明跨库同一恢复点。

在线备份提供一致快照，WAL 也是状态的一部分，因此不能仅 `cp` 主文件或凭能打开判断无损。[SQLite Backup API](https://www.sqlite.org/backup.html)、[WAL 官方说明](https://www.sqlite.org/wal.html)。本轮未实际运行备份。

**PocketBase 同步退出：** `services/session/pocketbase_store.py` 和默认 auth 使用的现有 collection 是本应用旧数据来源。交付单独只读 exporter：获授权源端维护/停写后，经固定 endpoint/API 或其一致备份的隔离只读导出服务，按集合稳定分页导出 schema/版本、users 必要身份映射、sessions/messages/turns/events 与已支持关联/文件清单，生成同一 freeze ID/manifest/摘要。导出账号仅有被批准集合读取权，凭证不落制品；不要求导出不可读取的密码 hash，目标凭证按受控重置处理，不导入旧 token。源变动或无法完整读取即失败，不能边写边分页冒充快照。离线 importer 复用 staging/ID映射（含 PocketBase 字符串 message ID→PG 整数）与验证；业务文件载荷交接按既有资源契约，远端服务不被删除或改写。新增任意外部 collection 不属于本应用自动迁移范围，但本应用已支持的 collection 不能遗漏。

### 7. 验收定义，不用 grep 清零冒充完成

1. 迁移 inventory 所有域，受支持可选 Matrix 普通/E2EE 也包括；逐 API/WS/UI/CLI/SDK/工具/后台场景保留功能、引用和错误。
2. 新进程及其子进程禁止 SQLite 文件/内存连接、默认库生成及 SQLite C/native旁路；静态依赖和受控 plugin 加载扫描辅助发现。离线导入 fixture 单独进程允许读，不能给业务测试放宽白名单。
3. 真实 PG：干净安装、schema 1 升级、漂移/并发/取消回滚、双测试租户与同租户用户/管理员、任务/事件/restart、外部故障；不能把 :memory: 测试换个标记当作 PG 验收。
4. 默认 `deeptutor` Web/CLI、CLI-only wheel、SDK、企业入口分别运行安装制品 smoke；无配置/拒绝 SQLite 和 PocketBase、坏权限/断库均先于模型与后台副作用失败。
5. 真实模型验收覆盖默认 Web/WS 聊天、续聊/regenerate/ask_user 和迁移影响的教学工具流程；使用合成内容。另行确认 Secret 引用、调用数及供应商侧费用预算，先落盘逐调用 usage，缺用量标待核算；`max_tokens` 不冒充 reasoning/货币硬上限。
6. 大数据查询/导入采用有界批量和稳定游标；按用户委托评估形成的 [K12 容量基线 v1](capacity-assessment.md) 验证 P1 一学年及重度尾部，记录数据规模、并发、p95/p99、池等待、执行轮数与内存。环境配置和实际量级必须随报告固定，不能把 P0 或外推当作 P1/P2 已通过，不声称架构本身保证性能/HA。

## Migration Plan

1. 先发布兼容的新代码/迁移工具候选制品到隔离验证环境；保留原部署和源备份，不改原库。
2. 完成 schema 1 无数据重建升级、所有领域测试及默认入口兼容；在同一受控变更中开发分片，但不得发布半替换 PG/SQLite 混合运行版本。
3. 获授权后停止原 Web/CLI/SDK/cron/Partners/Matrix writer，确认退出与备份一致；目标进入维护态并阻止第二导入者。
4. plan→schema apply/verify→import→verify/report；核对每源/每owner/每表计数、内容摘要、FK/分支/事件/游标/密钥恢复，用户确认映射；失败保持维护，不开启新写。
5. 使用全新 scratch 启动默认 PG-only 制品，完成入口 smoke，确认禁用/撤权、历史、题库、学习、阅读与渠道正确，再受控放行业务。
6. **旁路迁入新 PG**：若原 SQLite/PocketBase/原 PG 均未改且目标无新业务写，可停止候选版本后经操作者决定恢复原部署；这不是新版 SQLite backend。**schema 1 原地升级**：旧 runner 校验精确 catalog，哪怕尚无新业务写也不能直接启动旧构建；只能使用已验证兼容新 schema 的 PG 构建，或停写后受控恢复完整升级前 PG 备份/匹配制品。PG 已有新写后仅允许兼容 PG 构建回退或经批准 PG/所需资源恢复，不能切旧 SQLite/PocketBase 丢数据。认证世代、渠道密钥/设备信任和调度恢复不能复活撤权或重发不确定副作用。

| 应用/数据库组合 | 放行规则 |
| --- | --- |
| 首切片旧构建 + 原 schema 1 | 原有受控验收范围有效，不表示支持全量业务 |
| 全量新构建 + 未升级 schema 1 | 仅允许迁移工具 plan/apply；业务拒绝 |
| 全量新构建 + 声明兼容的目标 schema 版本集合 | 所有迁移/catalog/身份/批次门禁通过后才可业务运行 |
| 首切片旧构建 + 新 schema | 默认拒绝；不得用跳过 verify/改历史伪造兼容 |
| 兼容回退构建 + 新 schema | 仅 release manifest 中逐版本实测通过的组合允许；没有此制品时只能受控备份恢复 |

新迁移编号在独立 source change 内分配，发布制品必须写出精确可接受版本集合及 checksum，不能以“>=1”代替兼容矩阵。

## 规范替代与总纲映射

- 首切片的 34/34 是旧范围的历史完成状态。本 change 明确取代其 `enterprise-runtime-composition` 中“入口与独立本地模式兼容”的 local 例外，以及 task 1.4/1.17 的无 PG 安装预期；不把旧测试结果改写成新目标已通过。
- 总纲 `production-rollout` 的企业包专属 PG 实现约束调整为：通用 PG 下沉 core，企业专属集成/资源/治理继续独立。S3/RAG、租户安全与依赖方向不变。
- 当前无正式 `openspec/specs`；新规范使用独立名称，避免假设未归档 delta 已成为 formal spec。未来获得 sync/archive 授权时按“总纲→首切片→本 change”收敛；须将旧 local 兼容 requirement 替换为本 change PG-only 契约，而非把矛盾 requirement 同时追加。收敛前后 strict 与语义检查均需通过；本轮不执行归档。
- 工作归属仍为 A1（总纲 1.1/1.3–1.7 及题库/个人内容相关部分），A3 承接制品与默认入口集成。完整 settings/grants/memory 正文和资源 metadata 仍需 A1 其它任务，S3/LightRAG/HugeGraph 由 A2，CI/生产发布 G1 由 A3；不修改总纲 90 个 checkbox。
- H 单执行门禁沿用，Matrix/cron/CLI 不得绕过执行登记；不因使用 PG 宣称任意多副本安全，新增多执行模式必须另过 G-H。

## Risks / Trade-offs

- **安装兼容破坏** → 明确发布说明、默认 PG 配置/本机开发指引、无 PG 快速脱敏失败；不偷偷切回旧库。
- **范围大且有混合文件载荷** → 以 inventory 逐业务验证，依赖的资源 provider 保留真实载荷行为；本 change 不冒充 S3/全 A1 交付，出现新增 SQLite 路径纳入任务而不是删除功能。
- **同步驱动阻塞或跨 scope 泄漏** → 有界同步/异步池、显式 scope、线程所有权和取消回滚专项测试。
- **ID/WAL/跨域关系损坏** → 一致快照、源指纹、稳定映射/staging、维护门禁、全引用验证，未知/坏数据阻断切换。
- **E2EE 数据损失或外部动作重复** → 加密状态完整导入/恢复、独立 Secret、真实协议测试和待核对状态；不得靠重新配对或重新发送掩盖失败。

## 执行时确认的信息

以下不改变设计范围，但未确定不得执行对应真实操作：真实旧库/备份清单及所有权 manifest、目标 DSN/受限角色、停写窗口与回退保留期；隔离 Matrix 测试服务和 libolm 组合；真实模型预算；容量数据集与验收阈值。规划阶段不读取 `.secrets` 或替用户推测这些参数，不阻塞纯代码/隔离 fixture 工作。


### 2026-09-14 执行信息补充

用户已授权使用指定 `.secrets` 模型配置，必要验收调用数/费用暂不设上限，逐物理请求记录仍必需；这不等于供应商配额无限。用户另明确委托我们评估 K12 容量，现采用 [capacity-assessment.md](capacity-assessment.md) 的显式假设与 P1 验收目标，不再等待用户填写数量。上述更新取代规划阶段对应的“预算/容量待用户确认”状态，未放宽真实旧库清单、生产 DSN/停写/cutover 与发布授权。
