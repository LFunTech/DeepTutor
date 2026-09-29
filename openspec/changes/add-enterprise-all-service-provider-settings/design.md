# 设计：OMS 配置管理复用现有设置语义

> 2026-09-29 执行版：当前修订版已获批准，descriptor/执行者矩阵、PG 配置事实迁移与 OMS 后端配置 API 已完成。云端 OMS 是唯一平台配置写入口，本地 `/settings` 继续工作；供给/额度/用量以 `add-enterprise-oms-business-logic` 为唯一权威；正式前端接入归 `add-c1-c2-oms-operator-interface`。

## 服务覆盖矩阵

| 服务组 | 现有设置入口 | 交付必须验证 |
| --- | --- | --- |
| 连接与模型 | connections、llm、task、embedding、search、tts、stt、imagegen、videogen | catalog/profile/model/active selection、Secret ref、测试、逐服务发布、真实执行者读取 |
| 文档解析/RAG | knowledge/document-parsing；LightRAG 受控检索 profile | 引擎或远端服务测试、desired/active、解析/检索执行者生效确认；不在 DeepTutor 操纵 LightRAG 内部队列/图 |
| 外部 Agent 与视频学习 | agents、video-learning | 可用性、凭据/endpoint、测试与真实调用；仅 provider 相关字段进入平台配置 |
| 工具与能力 | tools、capabilities、attachments 等 | 不是一律 provider；归策略/租户配置，运行时边界仍要生效 |
| 个人偏好 | appearance、learner-profile、guardian、memory 等 | 保持个人作用域，不提升为平台 provider 凭据 |

以现有 SettingsStore/catalog shape、backend provider descriptors 和真实执行者为语义源；企业 `ProviderConfigRepository` 适配统一 PG 的不可变配置版本与 Secret ref。平台默认目录 → 租户允许范围/可选覆盖 → 用户选择，后级不能扩大前级授权。云端只在独立 OMS 提供管理写 API；企业 app 不挂核心完整 settings/governance router，CLI/SDK/后台也不能直写 PG/本地 JSON 绕过版本与审计。本地 DeepTutor Web 设置不变。平台凭据只由受控 Secret provider 解析，租户和普通用户 API 只返回可选 profile 标识/安全展示信息。连接复用不能复制明文 key 到多个 service profile。网络/部署参数另走运维配置，不由普通运营或租户随意改。

配置使用 expected_version 乐观锁：`draft → validated/tested → publishing → active`，失败为 `failed`，回退写新版本；每服务单独发布并固定目标执行者集合。每个执行者实际装载后回报 active_version/observed_at，全体确认前不整体 active；部分确认、超时保持旧 active，未确认实例不接新流量，新实例装载旧 active 后才 ready。不能保证一致读取的服务 fail closed，并由后端 display descriptor 说明影响。模型、embedding 维度、语音、图像/视频等各自参数验证不可被 LLM 通用表单抹平。search 无模型列表、task 未独立配置时按 LLM 回退、embedding endpoint 为完整地址。provider 不支持某设置/用量能力则明确 capability flag 与不可用原因，不静默成功。LightRAG 通过受控 API 确认，不能只更新本地 JSON 或单 Pod。

权限：EduPlus2 **已验证身份**须由 DeepTutor Enterprise 程序按本地 PG 事实判定具备 `ops.oms.access`、`ops.providers.read/manage` 或 `ops.credentials.manage` 等当前动作与 `platform` 范围授权；只有具备具体写能力的主体可写，operator/auditor 仅按显式读能力查看，`tenant_admin` 不继承。需要企业扩展版本化 PG migration（配置版本、service kind、profile/model、scope、Secret ref、目标确认、审计）及 OMS 应用权限迁移，并对历史 JSON catalog 做显式 owner/版本映射 dry-run，不能自动覆盖 active；运行态不双写 JSON。不修改 EduPlus2/OpenFGA/Keycloak；外部身份在线状态不可用时写入 fail closed。OMS API Secret 始终脱敏，TMS 只获本租户安全服务状态而无 Secret ref/采购/成本。测试需每服务至少一个真实执行者读取/健康检查和失败回退，不能以 LLM 测试替代；会发供应商请求的配置测试须显式选择经权威绑定且操作人有 `school` 范围的目标学校，以该学校已授权服务、额度、供给和受控测试服务主体 grant 准入、预留并逐 attempt 核对；仅做本地格式/连通性静态校验不得发供应商可计费请求。无目标学校或授权/额度不足时拒绝可计费测试，不设隐式平台免费额度。

服务额度不足不妨碍登录、查看获授权的配置状态或管理历史，但会发出该服务新供应商请求的配置测试同样受准入限制；`active` 仅表示目标执行者技术装载完成，不代表某租户有服务授权或可用额度。无可信硬上界或供给时不得把测试调用当作免费健康检查。正式验收还须覆盖本地设置正例、云端旧管理路由 404、独立 OMS 权限正负例、CLI/HTTP/WS/SDK/后台与当前 upstream 兼容。
