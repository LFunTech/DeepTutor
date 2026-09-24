# add-g1-woodpecker-k8s-release-baseline

规划 G1 Woodpecker/K8s 发布流水线基线：在环境 registry 与目标部署契约确认后，通过受保护 deployment tag 解析 `target_env_id`，并按该环境交付构建、推送、digest 锁定、迁移、K8s 部署、业务 smoke、回退、release evidence 和 Secret 脱敏检查闭环；支持多个不同生产环境逐一审批、部署和留证。

本 change 从原 `add-m1-g1-single-tenant-production-baseline` 的 A3/V.3 拆出。固定租户 runtime、resource binding、EduPlus2 demo 和 HTTP/WS smoke harness 由 `add-m1-fixed-tenant-runtime-baseline` 提供。


同时，本 change 明确 Woodpecker secrets 清单：registry、K8s deploy、SecretStore、migration、runtime secret refs、smoke、evidence、tag/approval 校验等 secret 必须按 `target_env_id` 分环境登记、最小权限授权和脱敏留证。
