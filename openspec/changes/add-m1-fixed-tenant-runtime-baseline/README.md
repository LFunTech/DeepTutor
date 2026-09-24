# add-m1-fixed-tenant-runtime-baseline

规划 M1 固定租户运行基线：把已完成或正在收敛的 PG-only、固定 tenant 身份/会话、ObjectStore 资源绑定、LightRAG API binding、EduPlus2 API-only/前置 demo、HTTP/WS/SDK 入口和 TMS/OMS 未开放边界，整理为可被发布流水线调用的 runtime/smoke/evidence 契约。

本 change 从原 `add-m1-g1-single-tenant-production-baseline` 拆出。Woodpecker/K8s 构建、部署、迁移、smoke、回退和 release evidence 闭环已迁移到独立 change `add-g1-woodpecker-k8s-release-baseline`。
