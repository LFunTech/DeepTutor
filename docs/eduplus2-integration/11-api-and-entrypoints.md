# 11. API 与入口适配方案

## 阶段边界

A1/A2 保留现有入口/产品协议并替换固定 tenant 的 PG/S3/scratch，A3 集成验收；B1 验证首租户 EduPlus2 接入和权限，B2 开放多租户及租户管理；C1/C2 新增运营入口和治理视图。服务端-to-服务端调用同样不能绕过 scope 和权限。

## 企业应用外壳与核心入口

企业启动器/应用 factory 位于独立 `deeptutor_enterprise` 包，优先复用容器注入、TurnRuntimeManager/SessionStore、Tool/Capability 协议；缺失处通过通用核心 seam 补齐。产品继续使用既有 HTTP 与 `/api/v1/ws` 语义，不把 Plugin API 或直接 `DeepTutorApp()` 默认初始化当作企业入口的等价替代。

装配时显式选择已接入企业 Store/scope/权限的原路由，注册企业新增路由并校验无重复冲突。相同路径不能靠先后注册偷偷覆盖，原生未适配入口不对外暴露；必需行为必须改造接通而不是简单禁用。启动任务、SDK/CLI、后台容器也使用同一企业 profile，缺 provider/兼容版本拒绝启动。详见 [13](13-deployment-and-upstream-sync.md)。

## 现有入口

DeepTutor 当前主要入口：

| 入口 | 文件 | 说明 |
| --- | --- | --- |
| WebSocket | `deeptutor/api/routers/unified_ws.py` | `/api/v1/ws`，产品主聊天入口 |
| HTTP API | `deeptutor/api/main.py` 注册的 routers | knowledge、sessions、settings、memory 等 |
| Python SDK | `deeptutor/app/facade.py` | `DeepTutorApp` |
| CLI | `deeptutor_cli/main.py` | 本地开发/命令行 |
| Plugin API | `deeptutor/api/routers/plugins_api.py` | playground-style tool/capability execution |

生产对接 EduPlus2 时，主入口应是 HTTP + `/api/v1/ws`。Plugin API 不建议作为生产会话入口。

## WebSocket `/api/v1/ws`

当前 WebSocket 支持：

- `start_turn` / `message`
- `subscribe_turn`
- `subscribe_session`
- `resume_from`
- `cancel_turn`
- `submit_user_reply`
- `regenerate`
- `check_active_turn`
- `ping`

多租户适配要求：

1. `ws_require_auth()` 必须安装带 `tenant_id` 的 `CurrentUser`。
2. `TurnRuntimeManager.start_turn()` 异步任务必须继承当前 user context。
3. `session_id` 只能在当前 tenant/user scope 内解析。
4. `knowledge_bases` 引用必须通过租户感知的 `resolve_kb()`。
5. stream event 持久化到 PG 当前 tenant/turn，按 seq 重放；取消/回复在多副本下必须到达正确执行者，不能只访问本 Pod 内存。

## HTTP API

所有受保护 router 当前通过 `Depends(require_auth)` 安装用户上下文。需要确保：

- `require_auth()` 解码 DeepTutor `dt_token` 后恢复 `tenant_id/eui/eit`。
- 管理类 API 不再统一使用旧 `require_admin()`，而是拆成 platform / tenant 管理权限。
- 持久化调用统一使用 tenant/owner-scoped Store；`get_current_path_service()` 只用于 scratch 或独立本地模式。

## EduPlus2 新增 API

建议新增 router：

```text
extensions/enterprise/src/deeptutor_enterprise/api/eduplus2.py
```

接口草案：

| Method | Path | 说明 |
| --- | --- | --- |
| `GET` | `/api/v1/eduplus2/handoff/callback` | EduPlus2 工作台回跳，换 token 并设置 `dt_token` |
| `POST` | `/api/v1/eduplus2/logout` | 清理 DeepTutor session，可选跳转 EduPlus2 logout |
| `GET` | `/api/v1/eduplus2/session` | 返回当前 EduPlus2/DeepTutor session 摘要 |
| `POST` | `/api/v1/eduplus2/webhooks` | EduPlus2 Webhook 接收入口 |
| `POST` | `/api/v1/eduplus2/sync/{tenant_id}` | 平台/租户管理员触发同步，需权限保护 |

## LightRAG Server 接口适配

保留已有 `lightrag-server` 选择与检索响应形状，企业 binding/client provider 从 PG/Secret 和可信当前身份构造内部调用；现有 `base_url/api_key` 客户端没有动态 workspace 或最终用户身份契约，须真实接入而非只配 URL。企业 KB 管理 API 接通 RagDocumentService 托管导入/状态/删除/重建，不能声称原版检索专用连接已有这些能力。

客户端提交逻辑 KB/document ID，服务端验证归属/操作并解析固定 workspace 的受控 endpoint；不开放任意 Server URL、远端文档路径、workspace 或 key。原文引用经 source object_id 映射再次授权；非托管外部连接仍仅解绑。服务间身份、错误与恢复契约见 [06](06-postgresql-native-store-plan.md)。

## Turn payload metadata

现有 `UnifiedContext.metadata` 可承载租户元信息，但不应让前端直接传入决定性 tenant 信息。建议由服务端填充：

```python
metadata={
    "tenant_id": current_user.tenant_id,
    "user_id": current_user.id,
    "eduplus_user_id": current_user.eduplus_user_id,
    "identity_type": current_user.identity_type,
    "auth_provider": "eduplus2",
}
```

禁止信任客户端 payload 中的 `tenant_id` 来切换租户。

## SDK

Python SDK 主要用于本地或服务端集成。EduPlus2 模式下建议：

1. 保持本地 SDK 行为不变。
2. 若 SDK 调远端 DeepTutor API，应使用 `Authorization: Bearer <dt_token>`。
3. 不建议 SDK 直接传 `tenant_id` 覆盖服务端 auth context。
4. 服务端-to-服务端场景使用单独 M2M token，并显式限制可访问租户。

## CLI

CLI 保持本地开发语义。可选增强：

```bash
deeptutor eduplus2 sync --tenant <tid>
deeptutor eduplus2 tenant list
```

阶段一不依赖这些命令；阶段二必须提供受保护管理 API 和可审计运维入口用于开通/绑定/停用/配额，不手工改库，也不等阶段三 UI。上面命令为拟定接口，不是当前可执行命令。

## Plugin API

当前 plugin API 的 capability execute-stream 更偏 playground transport，不走完整 `TurnRuntimeManager` persistence。EduPlus2 生产场景建议：

- 默认不开放给普通用户。
- 如需开放，必须安装 tenant context，且能力输出/持久化路径必须受 scope 限制。
- 不作为主聊天入口。

## API 安全清单

1. 所有入口都必须先 auth，再解析 path/resource。
2. 不允许 query/body 中的 `tenant_id` 覆盖 token 中 tenant。
3. 管理接口区分 `platform_admin` 与 `tenant_admin`。
4. WebSocket token 过期时要关闭连接或拒绝新 turn。
5. 错误响应不泄露路径、secret、token、signature。

## 两级管理入口

阶段二 `/admin` 复用当前页面，只操作当前租户；阶段三拟新增 `/ops` 与 `/api/v1/ops/*` 管理所有租户。租户 ID 出现在运营路由时，必须先校验平台具体能力再绑定目标租户；普通 API 不获得任意 tenant override。租户管理与运营 API 共用业务服务，不共用全局放行依赖。完整权限/菜单矩阵见 [12](12-platform-operations-admin.md)。

## 不同运行模式的发布约束

B1/B2 所有入口都必须使用可信 scope，不以是否多副本为条件。跨 Pod 订阅/重放/cancel/reply 按独立 H 工作线实现并通过 G-H 后才启用多执行者；单租户的 HA 需求也会触发，多租户本身不强制 replicas=2。
