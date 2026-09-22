# 实施任务

范围以 [proposal](proposal.md)、[design](design.md) 和 `enterprise-m1-g1-single-tenant-baseline` delta spec 为准。本 proposal 交付 M1/G1 单租户生产基线；B1/B2/C1/C2 只做边界与兼容回归，不交付对应业务功能。所有任务当前均未实施，获批后逐项执行并补充证据。

## A1 结构化状态替换收敛

- [x] A1.1 迁移/配置：盘点已归档 PG-only、身份、会话、turn、audit specs 与执行证据，列出仍会阻断 production runtime 的 SQLite/local `data/`/文件权威路径；产出 M1 差距清单和切换证据要求。
- [x] A1.2 真实入口：在企业组合入口下验证固定租户登录/status、HTTP session list/detail、WebSocket `start_turn`、SDK/CLI 受控路径均使用应用 PG，不触发默认 local profile 或原生未适配入口。
- [x] A1.3 权限/异常测试：覆盖同租户跨 owner、管理员旁路、未知 session 接管、过期/撤销 token、WS refresh 身份不匹配、迁移版本缺失/漂移的 fail-closed 负例。
- [x] A1.4 切换证据：记录 schema version、固定 tenant/user bootstrap、RLS/owner guard、auth/session audit 与 upstream-neutral core seam 清单；未覆盖入口不得标记 G1 通过。

## A2 文件、资源与检索替换收敛

- [x] A2.1 迁移/配置：定义 DeepTutor 业务 ObjectStore、pre-signed upload/resource binding、Secret/Settings provider、LightRAG API binding、KB/index-version binding 和模型 profile 的 production 配置契约；只记录 Secret ref，不记录明文。
- [x] A2.2 真实入口：通过真实 API/WS 或维护命令验证创建上传意图、pre-signed URL 直传 ObjectStore、上传完成确认、HTTP 与 WebSocket `start_turn` 提交 `prompt + resource_id/key` 清单、后端读取资源、对象写读删/授权下载、KB 原文或样本资源登记、LightRAG service readiness、引用返回与 audit 关联。
- [x] A2.3 权限/异常测试：覆盖 ObjectStore bucket/权限、过期上传 URL、未完成上传、WebSocket raw binary/URL/base64 payload、非法 resource key、跨 owner/tenant/session 引用、MIME/大小超限、hash/checksum mismatch、Secret 缺失、LightRAG unavailable、未授权 KB/私有资源、服务派生副本状态不一致、删除补偿失败等负例。
- [x] A2.4 切换证据：保存 ObjectStore/LightRAG binding 版本、pre-signed upload policy 摘要、resource id/key 绑定摘要、manifest/hash、对象前缀、服务状态、清理/补偿结果；若目标环境未具备 LightRAG 样本检索，记录为 G1 阻断依赖而非放行。

## A3 单租户生产验收与 Woodpecker

- [ ] A3.1 迁移/配置：先登记目标 K8s 部署契约（namespace、Ingress/TLS、SecretStore、RBAC、NetworkPolicy、registry、发布锁、回退和 evidence 存放位置），再新增或补齐部署源（backend/frontend/Job/Service/Ingress/ConfigMap/Secret ref/NetworkPolicy/ServiceAccount/probes/resources），声明单执行 rollout 策略和禁止本地权威 fallback；不得用“单租户”推导出的通用 YAML 标记完成。
- [ ] A3.2 真实入口：先确认目标 Woodpecker 契约（server/agent 版本、agent backend、受保护 ref、审批/Secret 边界、registry 凭证、目标 Ingress/TLS 路径），再实现 build/push/migration/deploy/smoke/rollback/evidence 阶段，使用镜像 digest、环境锁和批准门禁；不得用未接入目标环境的占位 pipeline 标记完成。
- [ ] A3.3 权限/异常测试：实测 PR/未批准 tag/过期批准/环境不匹配/旧构建覆盖/Secret 越权/迁移失败/rollout 失败/smoke 失败/agent 中断/并发发布竞争均被拒绝或进入受控恢复。
- [ ] A3.4 切换证据：归档 release evidence（源码 SHA、upstream SHA、digest、schema、配置/Secret ref、smoke run ID、批准人、rollback 结果），并运行 `openspec validate --all --strict`。

## B1 EduPlus2 单租户接入边界回归

- [x] B1.1 迁移/配置：复用已归档 EduPlus2 exchange/fronting contract 的 local/test 配置，明确生产基线中 EduPlus2 只作为 M1 smoke 输入，不启用 Handoff/OIDC callback 或周期合法性调度。
- [x] B1.2 真实入口：在目标环境 smoke 中完成 EduPlus2 user JWT exchange、HTTP bearer 调用、WebSocket `auth_refresh` 和一轮真实对话；前置 demo/测试 token 页面与 dry-run smoke 必须体现 pre-signed upload → `prompt + resource_ids`，且只输出脱敏摘要。
- [x] B1.3 权限/异常测试：覆盖 client inactive、tenant mismatch、app status disabled、expired JWT、resolve/profile/permission unavailable、rate limit、owner guard denied、WS identity change denied。
- [x] B1.4 切换证据：记录 client_id/tenant/user 的 hash、request id、exchange/audit event、refresh 结果；不记录 JWT/`dt_token`/client secret；不标记 B1 功能完成。

## B2 多租户与租户自管理边界保护

- [x] B2.1 迁移/配置：确认 M1 固定租户 schema、tenant_id、RLS、resource prefix 和 LightRAG binding 不阻断后续多租户扩展，但不创建真实多租户治理 UI 或自助注册。
- [x] B2.2 真实入口：验证 `/tms`、`/api/v1/tms/*` 若未纳入 M1 则不被误暴露；如已有固定租户只读/维护入口，必须明确能力、角色和审计边界。
- [ ] B2.3 权限/异常测试：覆盖伪造 tenant header/body/query、跨租户资源 ID、client/app registry 未授权写入、同租户私有 KB/会话越权等负例。
- [x] B2.4 切换证据：保存“B2 未开放”边界记录、后续迁移前提、保留的 API/DB 兼容约束；不得把 M1/G1 evidence 记为 G2。

## C1 运营管理闭环边界保护

- [x] C1.1 迁移/配置：确认 M1 release evidence、audit/export、pipeline 记录能为未来 OMS 提供输入，但不新增 OMS 业务状态或运维决策 UI。
- [x] C1.2 真实入口：验证 `/oms`、`/api/v1/oms/*` 在 M1 未授权时不可用；现有 audit 页面只按已授权企业审计能力开放，不冒充统一运营后台。
- [x] C1.3 权限/异常测试：覆盖 tenant_admin 访问平台级 ops 能力、普通用户访问 audit/export、伪造 ops.* scope、越权查看跨租户 release evidence 的拒绝路径。
- [x] C1.4 切换证据：记录审计导出权限、证据保留位置和脱敏策略，标明 C1 未交付且后续需另立 proposal。

## C2 运营治理完善边界保护

- [x] C2.1 迁移/配置：保留配额、用量、SLA、client 治理、周期撤权和全局策略的后续扩展点，不把它们硬编码进 M1 单租户发布逻辑。
- [x] C2.2 真实入口：验证 M1 pipeline/evidence 能输出后续治理所需的脱敏指标字段，但不提供在线策略修改或跨租户治理入口。
- [x] C2.3 权限/异常测试：覆盖用量缺失、LightRAG 远端未确认结束、撤权窗口未实现、策略 source 不一致时的 fail-closed 或“不可用”表达。
- [x] C2.4 切换证据：记录 C2 缺口清单和后续 proposal 依赖，不因 G1 通过而删除治理待办。

## H 可用性/容量条件性任务

- [x] H.1 迁移/配置：确认 M1 目标拓扑为单执行模式，设置明确的容量/恢复目标和非 HA 声明；若目标要求多执行者/HA，则阻断并先立 G-H proposal。
- [x] H.2 真实入口：验证发布期间排空、停止接新 turn、旧执行者终止、新执行者启动和不重叠证据；frontend/无执行权组件可单独滚动但不能放宽 backend 执行限制。
- [x] H.3 权限/异常测试：覆盖锁/DB 连通丢失、agent 中断、Pod 重启、旧 running/waiting turn 恢复、重复 cancel/reply、WS 重连 replay 等非 HA 故障边界。
- [x] H.4 切换证据：保存单执行限制、容量假设、恢复窗口、未通过 G-H 的限制说明；不得宣称高可用或多执行者安全。

## 验证与归档准备

- [x] V.1 运行 `openspec validate add-m1-g1-single-tenant-production-baseline --strict`。
- [x] V.2 运行 `openspec validate --all --strict`。
- [ ] V.3 运行目标环境 Woodpecker + K8s smoke，并将脱敏命令、退出码、run ID、资源 upload/reference demo 证据、未验证项写入 execution evidence。
- [x] V.4 对新增/修改文档、脚本、manifest、pipeline 做 secret leakage scan，确认不包含 `.secrets` 明文、JWT、`dt_token` 或用户隐私。
- [x] V.5 完成 upstream mergeability review，记录 core patch 清单、通用 seam 目的、风险和回归命令。
- [ ] V.6 获得用户对实施完成、证据和归档的明确确认后，再按 OpenSpec 归档；未合并/未验证项不得勾选或归档。
