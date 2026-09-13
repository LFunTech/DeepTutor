# 07. 资源存储替换与租户隔离

## 阶段职责

- **M1 / A1–A3**：A1 结构化状态、A2 文件/检索分别闭环，A3 集成验收；固定 tenant、多用户所有权生效。
- **M2 / B1–B2**：B1 先验证首租户最终接入/权限，B2 完成多租户、租户管理 UI、配额及后台隔离。
- **M3 / C1–C2**：C1 运营管理闭环，C2 查询/任务治理完善，不再换存储。

本方案不再提供新的租户文件目录作为企业部署模式。已有 local 模式仅保留给独立本地运行/导入来源。

## 替换清单

| 资源 | 最终持久化 | 阶段一必须覆盖的调用 | 阶段二追加隔离 |
| --- | --- | --- | --- |
| sessions/messages/turns/events | PostgreSQL | HTTP、WS、SDK、历史、resume/regenerate/cancel、后台清理 | tenant + owner；跨 Pod 状态归 H，启用多执行者前验收 |
| memory/notebook | PG 内容/metadata；大附件 S3 | agent 读写工具、管理 API、快照/搜索 | tenant + owner；共享需 grant |
| settings/model catalog | PG metadata + Secret 引用 | 页面保存、运行时加载、缓存失效 | 平台默认、租户策略、用户偏好分层 |
| identities/grants/audit | PostgreSQL | 登录、授权读取与写入、管理审计 | 外部映射、tenant scoped grants/审计 |
| KB | 应用 PG metadata/binding/job + S3 原文/解析物 + LightRAG Server PG 全索引 | 企业文档服务接通上传/索引/检索/读源文/删除/恢复，非托管连接只解绑 | 个人/共享 KB、检索前授权、workspace 及数据库防线 |
| attachments/workspace/生成物 | S3 + PG object_assets | 上传、工具文件输入输出、引用、预览/下载、过期清理 | tenant + owner/grant；无任意 key |
| 可编辑 skills/personas | PG metadata + S3 正文 | 编辑、加载、版本与执行读取 | 平台只读模板、租户分发/用户授权 |
| partners/MCP/cron/exec/subagents | 启用时 metadata/job 入 PG，文件 S3，凭证 Secret | 所有回调、执行和调度路径 | tenant context、沙箱、配额、网络权限 |

仓库内随镜像分发的只读 prompts、内置 tools/skills 不属于用户可变状态，可以继续随镜像发布。生产资源/Store 实现位于独立企业包，核心服务、API、agent 工具和后台任务通过通用 seam 调用，禁止只替换页面请求而遗漏工具直写；职责清单见 [13](13-deployment-and-upstream-sync.md)。

## 配置与模型

```text
用户偏好（仅允许覆盖的字段） > 租户配置 > 平台默认值 > 内置默认值
```

安全策略与配额不能用上述偏好覆盖规则提权：最终权限是平台上限、租户策略和用户 grants 的交集。平台模型凭证存 Secret 系统，PG 存引用、可用模型与版本；租户管理员只管理已分配模型的使用授权，不读取/导出 provider key。

第一阶段必须把原 settings JSON/model catalog 的管理写入和 runtime 读取一起替换。多副本启用前补版本化缓存失效，不能页面显示已修改而 agent 仍读旧文件。

## S3-compatible ObjectStore

目标实现 `S3ObjectStore` 支持所选服务商的 endpoint、region、path-style、TLS、签名及加密配置。所谓兼容不能只靠配置名判断：必须在实际目标端完成 put/get/head/delete、multipart（如启用）、presigned URL、生命周期和恢复验证。

```text
tenants/{tenant_id}/users/{user_id}/attachments/{object_id}
tenants/{tenant_id}/shared/kb/{kb_id}/source/{object_id}
tenants/{tenant_id}/turns/{turn_id}/outputs/{object_id}
```

规则：

1. 后端从可信内部 scope 生成 key，查 PG 归属并授权；前缀不是安全边界本身。
2. 私有 bucket、TLS、Secret/工作负载身份、不向用户暴露长期存储凭证。
3. PG 预建 pending 记录→上传唯一 key→校验大小/hash/MIME→ready；消费者只读 ready，失败/超时有补偿清理。
4. 直传需先预留配额、完成时重新确认权限/大小/hash；多副本下同一额度不能重复消费。
5. 删除先 tombstone/标记，再异步删除并可重试；源文件删除联动解析物和向量索引。
6. 预签名 URL 是 bearer 凭证，短 TTL、日志脱敏；需要即时撤权时走后端代理。

## 不可忽略的文件路径依赖

`PathService` 不能仅把 `/data/...` 改成 `s3://...`。解析器、RAG 工具、exec、可视化等可能需要真实文件路径：

```text
授权 → 下载到隔离 scratch → 本地处理 → 上传结果至 S3 → 提交 PG 引用/状态 → 发布成功事件 → 清理 scratch
```

下载/上传超时、Pod 中断、重复任务、磁盘空间不足均要显式失败；结果未持久化不能返回成功。scratch 可重建但不能成为唯一副本。不采用挂载 S3 模拟 POSIX 来逃避接口替换。

## KB、向量与共享资源

默认继续使用 `lightrag-server`，不是将本地 pipeline 改写为另一套检索引擎。阶段一由企业 RagDocumentService/RagGateway 完成 PG/Secret binding、固定 workspace Server 路由、S3 原文/解析物及全部 PG 索引状态。具体实现/版本/数据库防线与所有权规则以 [06](06-postgresql-native-store-plan.md) 为准。

建立“原文→解析→索引→召回→授权源文→删除→重建”契约测试；远端接收成功不等于索引 ready，file_path 不等于可下载对象。托管删除联动远端索引和缓存；旧非托管连接只解除绑定，移交托管前不得删除其服务器数据。

阶段一固定租户也须个人/共享 KB 授权；阶段二复验多个租户。每次召回先校验整个 KB 的可见性，再路由到正确 workspace 的 Server，结果引用再次授权；不能把不同可见范围混成一个图再过滤 top-k。缓存、去重、KV、vector、doc_status、graph namespace 都带 tenant/KB/index-version；同 URL 下不同 KB 别名、静态 API key 或仅网关过滤不构成完整隔离。

共享 KB 是租户资源，不是租户管理员个人目录。管理员变更不会改变 KB 所有权。普通用户只有显式授权后才能读取，写入需独立权限。不得把旧全局 `admin:kb:*` 自动分享给全部新租户。

## 高风险能力

partners/MCP/cron/exec/subagents 默认关闭外部访问。启用前必须覆盖：租户所有权、Secret 引用、显式授权、执行时 scope 校验、任务幂等/恢复、沙箱与网络限制、资源配额及审计。

这是能力发布开关，不是额外的第四/第五实施阶段。已有必需功能不得默默删除；如果首发必须使用，就在阶段一完成持久化与安全替换，多租户开放前在阶段二完成隔离。cron 的计划和执行状态写 PG/受控调度系统，不建设租户 `jobs.json` 后端。

## 验收

存储故障/Pod 重建属于 [G1](02-rollout-testing-and-migration.md)，跨租户/跨用户及治理配额属于 G2；跨 Pod 协调属于启用多执行模式前的 G-H，运营界面变更真实影响资源策略属于 G3。所有 API、agent 工具、后台任务和文件下载都在验证范围内。
