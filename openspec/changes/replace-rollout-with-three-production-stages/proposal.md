## Why

现有三阶段业务目标合理，但直接用作研发任务会把 PG/S3/RAG 替换、EduPlus2 对接、多租户治理和分布式运行风险集中在少数大项。用户已确认保留三个业务里程碑、拆成七个实施工作包，并把多副本从租户数量中解耦，继续直接替换最终组件而非建设过渡系统。

用户追加 Woodpecker 构建与 Kubernetes 部署流水线开发要求：作为首发交付的一部分，而非上线后的手工补充。

此前已按执行顺序重排领域编号、readme 索引与 A3 包内任务。本轮按用户批准的可行性结论调整实现策略：企业逻辑独立成包/外壳，核心仅补必要通用 seam 并收敛旁路；默认保留 LightRAG Server 而非重写检索。三个里程碑、七工作包和完整业务验收范围不删减，只修订规划，未实施。

## What Changes

- **M1**：A1 结构化状态替换、A2 文件与检索替换、A3 单租户生产验收；PG/S3、认证与恢复完整通过后上线，不以单个 Store 完成代表产品可发布。
- **M2**：B1 先验证一个真实 EduPlus2 租户的最终登录/身份/权限/撤权闭环；B2 再开放多租户、治理后端及基于现有页面微调的各租户管理界面。
- **M3**：C1 运营管理闭环、C2 运营治理完善；C1 可先发布，C2 仍属于完整交付，不取消租户界面或重建 EduPlus2 主数据后台。
- Woodpecker 流水线纳入 M1/A3 必交付子环节，从 A1 并行开发；包括生产镜像/配置适配、质量检查、可信制品、受控晋级、迁移/部署/smoke 与安全回退，后续里程碑复用。
- K8s 同构集成环境和 EduPlus2 注册/测试账号/权限契约准备从 A1 并行；准备工作不成为额外过渡项目。
- H 作为跨里程碑可用性/容量工作线：单执行模式需确认限制；实际启用多执行者/发布要求 HA 前强制 G-H，不与 M2 或第二租户绑定。
- 将大任务拆成含适用数据迁移、真实入口、权限/异常/并发测试和切换证据的行为闭环；工作包验收不等于七次生产上线。
- 配置、现有 Tool/Capability/容器与 Store 注入优先；企业逻辑/Store/RAG adapter 位于独立 `deeptutor_enterprise` 包，core 仅补 provider/scope/权限/生命周期和旁路收敛，不以源码零 diff 为目标，不使用大规模 monkey patch。
- 默认复用 `lightrag-server` 检索契约和固定 workspace 原版服务，经企业授权路由管理受控实例池；不复制整套租户 DeepTutor，不将多个 KB 别名指向同一语料库冒充隔离。
- 企业文档服务补齐 PG/Secret binding、S3 原文/解析物、导入/状态/引用/删除/重建，LightRAG 的 KV/vector/doc_status/graph 全部进入受管 PG；锁定版本并验证图后端、低权启动和数据库防线，workspace 不当作 RLS。
- 非托管外部连接只解除绑定；移交企业托管需核对归属，不静默删除外部数据。组合制品、备份恢复和 upstream 回归包含企业包与检索服务。
- 保留不双写、不静默 fallback、不建设租户文件后端、稳定内部 ID、Store 收敛和 upstream 可更新性约束；现有租户 UI 必要微调，运营模块可包外构建但共用治理服务。

## Capabilities

### New Capabilities

- `production-rollout`: 三个业务里程碑、模块化企业扩展、PG/S3/LightRAG 完整资源链路、安全切换及独立可靠性门禁。
- `tenant-administration`: 首租户最终接入验证、多租户隔离、现有租户管理界面和治理闭环。
- `platform-operations`: 基础运营与治理完善分批交付、权限矩阵、生命周期、用量及审计。
- `kubernetes-delivery-pipeline`: Woodpecker 首发交付、制品/批准/凭证边界、迁移编排、发布互斥、业务验证与安全回退。

### Modified Capabilities

无已归档正式 capability；本次修改同一活动 change 的规划 delta，不另建平行规范。

## Impact

仅调整本 change 和 `docs/eduplus2-integration/` 领域方案，需求与任务以 OpenSpec 为主，readme.md 保持索引入口。未修改业务代码、真实 DB/OpenFGA/Keycloak 状态或集群；未提交/部署/执行迁移。本轮未创建或触发实际流水线。后续实施新增独立企业包/启动器、受管 RAG adapter、CI workflow、脚本、生产镜像与 K8s 清单；必要通用核心变更仍涉及存储、auth/scope、HTTP/WS/SDK/worker 和租户前端，不默认改写上游教学或检索内核。业务任务保持未完成，未触发的多副本任务不能因单执行模式发布而虚勾。
