# 面向普通运营人员的 OMS 界面

> **重订已获单独批准（2026-09-26）**：本版替换旧只读 Provider、Token 费用/欠费界面目标；以 `add-c1-oms-operations-prototype` 的五类资源、列表→详情 IA 及 `add-enterprise-oms-business-logic` 为准。用户批准按现版实施；真实 API/权限未就绪前不得把原型当生产界面。

## Why
当前本地 `/oms` 是规划/原型路径，不是独立生产 OMS。完成可信平台身份和数据面后，普通运营人员需要按资源→服务→供给→租户授权/额度→实际使用→核对逐级操作，不必理解底层 LLM/PG/RLS，也不能越权进入 EduPlus2 租户控制或 TMS 私有内容。

## What Changes
- 在独立部署 OMS 前端接真实平台 API，形成五类平台资源、全服务配置与执行者状态、供给、租户服务授权/统一赠送与充值额度、真实原生单位用量、待核对/更正、OMS-only 有证据成本及审计/任务的列表→详情工作流；原型路径生产保持 404。
- 使用后端 display descriptor 呈现“当前状态、影响对象、下一步”，技术字段默认折叠/脱敏；支持加载、空结果、待核算、同步延迟、失败与无权限状态。
- 用量页按租户→用户/应用→service/provider/model→operation/attempt 显示可信原生单位、预留/已结算/待核对及证据；不生成租户售价、费用、账单或欠费。供应商采购/成本仅有 `ops.cost.read` 可见，缺成本契约显示未核定。
- OMS 按动作权限管理 Provider/Secret 引用、供给和租户权益/核对；仍无 EduPlus2 租户开停、TMS client/成员、私有正文管理入口。TMS 是独立部署，只复用安全组件与 DTO，不继承 OMS 专有数据。

## Capabilities
### New Capabilities
- `enterprise-oms-operator-interface`: 普通运营人员可用的 OMS 工作台及前后端权限一致的业务呈现。
### Modified Capabilities
无；如需修改正式 web 路由/导航 spec，实施前补 delta。

## Impact
依赖平台权限、租户生命周期、全服务配置、可信 attempt 用量与 OMS 供给/权益总账的稳定 API；**不依赖**被退役的 Token billing/欠费 change。影响 `extensions/enterprise/frontends/` 独立 OMS app、企业前端客户端、共享安全组件、E2E 与权限测试；本地 `web/app/oms/` 原型不作为生产入口。真实 API/权限就绪前页面明确未启用，不填假数据。
