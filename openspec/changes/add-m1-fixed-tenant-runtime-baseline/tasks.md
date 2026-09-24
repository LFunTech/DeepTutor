# 实施任务

范围以 [proposal](proposal.md)、[design](design.md)、`enterprise-m1-fixed-tenant-runtime-baseline` 和 `enterprise-eduplus2-fronting-auth-demo` delta spec 为准。本 proposal 只交付 M1 固定租户 runtime/smoke/evidence 边界；Woodpecker/K8s 发布闭环已拆到 `add-g1-woodpecker-k8s-release-baseline`。历史完成情况从原 `add-m1-g1-single-tenant-production-baseline` 迁入，未真实验证项不得勾选。

## A1 结构化状态替换收敛

- [x] A1.1 迁移/配置：盘点已归档 PG-only、身份、会话、turn、audit specs 与执行证据，列出仍会阻断 production runtime 的 SQLite/local `data/`/文件权威路径；产出 M1 差距清单和切换证据要求。
- [x] A1.2 真实入口：在企业组合入口下验证固定租户登录/status、HTTP session list/detail、WebSocket `start_turn`、SDK/CLI 受控路径均使用应用 PG，不触发默认 local profile 或原生未适配入口。
- [x] A1.3 权限/异常测试：覆盖同租户跨 owner、管理员旁路、未知 session 接管、过期/撤销 token、WS refresh 身份不匹配、迁移版本缺失/漂移的 fail-closed 负例。
- [x] A1.4 切换证据：记录 schema version、固定 tenant/user bootstrap、RLS/owner guard、auth/session audit 与 upstream-neutral core seam 清单；未覆盖入口不得标记 runtime baseline 通过。

## A2 文件、资源与检索替换收敛

- [x] A2.1 迁移/配置：定义 DeepTutor 业务 ObjectStore、pre-signed upload/resource binding、Secret/Settings provider、LightRAG API binding、KB/index-version binding 和模型 profile 的 production 配置契约；只记录 Secret ref，不记录明文。
- [x] A2.2 真实入口：通过真实 API/WS 或维护命令验证创建上传意图、pre-signed URL 直传 ObjectStore、上传完成确认、HTTP 与 WebSocket `start_turn` 提交 `prompt + resource_id/key` 清单、后端读取资源、对象写读删/授权下载、KB 原文或样本资源登记、LightRAG service readiness、引用返回与 audit 关联。
- [x] A2.3 权限/异常测试：覆盖 ObjectStore bucket/权限、过期上传 URL、未完成上传、WebSocket raw binary/URL/base64 payload、非法 resource key、跨 owner/tenant/session 引用、MIME/大小超限、hash/checksum mismatch、Secret 缺失、LightRAG unavailable、未授权 KB/私有资源、服务派生副本状态不一致、删除补偿失败等负例。
- [x] A2.4 切换证据：保存 ObjectStore/LightRAG binding 版本、pre-signed upload policy 摘要、resource id/key 绑定摘要、manifest/hash、对象前缀、服务状态、清理/补偿结果；若目标环境未具备 LightRAG 样本检索，记录为后续 G1 阻断依赖而非放行。

## B1 EduPlus2 固定租户接入边界回归

- [x] B1.1 迁移/配置：复用已归档 EduPlus2 exchange/fronting contract 的 local/test 配置，明确生产基线中 EduPlus2 只作为 M1 smoke 输入，不启用 Handoff/OIDC callback 或周期合法性调度。
- [x] B1.2 真实入口：在可用环境 smoke 中完成 EduPlus2 user JWT exchange、HTTP bearer 调用、WebSocket `auth_refresh` 和一轮真实对话；前置 demo/测试 token 页面与 dry-run smoke 必须体现 pre-signed upload → `prompt + resource_ids`，且只输出脱敏摘要。
- [x] B1.3 权限/异常测试：覆盖 client inactive、tenant mismatch、app status disabled、expired JWT、resolve/profile/permission unavailable、rate limit、owner guard denied、WS identity change denied。
- [x] B1.4 切换证据：记录 client_id/tenant/user 的 hash、request id、exchange/audit event、refresh 结果；不记录 JWT/`dt_token`/client secret；不标记 B1 功能完成。

## B2 多租户与租户自管理边界保护

- [x] B2.1 迁移/配置：确认 M1 固定租户 schema、tenant_id、RLS、resource prefix 和 LightRAG binding 不阻断后续多租户扩展，但不创建真实多租户治理 UI 或自助注册。
- [x] B2.2 真实入口：验证 `/tms`、`/api/v1/tms/*` 若未纳入 M1 则不被误暴露；如已有固定租户只读/维护入口，必须明确能力、角色和审计边界。
- [x] B2.3 权限/异常测试：补齐固定租户 runtime 下伪造 tenant header/body/query、跨租户资源 ID、client/app registry 未授权写入、同租户私有 KB/会话越权等负例；不要求开放真实多租户。
- [x] B2.4 切换证据：保存“B2 未开放”边界记录、后续迁移前提、保留的 API/DB 兼容约束；不得把 M1 runtime evidence 记为 G2。

## C1/C2/OMS 与治理边界保护

- [x] C1.1 迁移/配置：确认 M1 runtime evidence、audit/export、smoke 摘要能为未来 OMS 提供输入，但不新增 OMS 业务状态或运维决策 UI。
- [x] C1.2 真实入口：验证 `/oms`、`/api/v1/oms/*` 在 M1 未授权时不可用；现有 audit 页面只按已授权企业审计能力开放，不冒充统一运营后台。
- [x] C1.3 权限/异常测试：覆盖 tenant_admin 访问平台级 ops 能力、普通用户访问 audit/export、伪造 `ops.*` scope、越权查看跨租户 release evidence 的拒绝路径。
- [x] C1.4 切换证据：记录审计导出权限、证据保留位置和脱敏策略，标明 C1 未交付且后续需另立 proposal。
- [x] C2.1 迁移/配置：保留配额、用量、SLA、client 治理、周期撤权和全局策略的后续扩展点，不把它们硬编码进 M1 固定租户 runtime。
- [x] C2.2 真实入口：验证 M1 runtime evidence 能输出后续治理所需的脱敏指标字段，但不提供在线策略修改或跨租户治理入口。
- [x] C2.3 权限/异常测试：覆盖用量缺失、LightRAG 远端未确认结束、撤权窗口未实现、策略 source 不一致时的 fail-closed 或“不可用”表达。
- [x] C2.4 切换证据：记录 C2 缺口清单和后续 proposal 依赖，不因 M1 runtime 通过而删除治理待办。

## H 可用性/容量边界

- [x] H.1 迁移/配置：确认 M1 runtime 仅声明单执行能力假设和非 HA 限制；若目标发布要求多执行者/HA，则阻断并先立 G-H proposal。
- [x] H.2 真实入口：验证停止接新 turn、旧 running/waiting turn 恢复、重复 cancel/reply、WS 重连 replay 等 runtime 边界；发布期排空/rollout 编排归 G1 流水线 proposal。
- [x] H.3 权限/异常测试：覆盖锁/DB 连通丢失、agent 中断、Pod 重启等非 HA 故障边界。
- [x] H.4 切换证据：保存单执行限制、容量假设、恢复窗口、未通过 G-H 的限制说明；不得宣称高可用或多执行者安全。

## 验证与归档准备

- [x] V.1 运行 `openspec validate add-m1-fixed-tenant-runtime-baseline --strict`。
- [x] V.2 运行 `openspec validate --all --strict`。
- [x] V.3 对新增/修改文档、脚本、manifest、pipeline 做 secret leakage scan，确认不包含 `.secrets` 明文、JWT、`dt_token` 或用户隐私。
- [x] V.4 完成 upstream mergeability review，记录 core patch 清单、通用 seam 目的、风险和回归命令。
- [ ] V.5 获得用户对实施完成、证据和归档的明确确认后，再按 OpenSpec 归档；未合并/未验证项不得勾选或归档。
