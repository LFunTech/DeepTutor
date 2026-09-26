# Protected K8s release source

This directory is a release-source skeleton consumed by the protected K8s release baseline. It is not a complete cluster bootstrap package.

`deploy.sh` is the pipeline entrypoint for an already approved release. It fails before
calling `kubectl` unless `DEEPTUTOR_DEPLOY_APPROVED=yes` is set, renders the
digest-pinned migration/backend manifests, waits for the migration Job, and then waits
for the backend rollout. `status.sh` prints the namespace-scoped rollout snapshot for
redacted release evidence.

`backend_executor_replicas` is rendered from the target environment contract via
`DEEPTUTOR_BACKEND_EXECUTOR_REPLICAS`; `DEEPTUTOR_EXECUTION_MODE` is rendered as
`single` or `replicated` from the same contract. A value greater than `1` is supported only when
the runtime coordination contract selects Redis (`DEEPTUTOR_TURN_COORDINATION_BACKEND=redis`):
the application uses shared turn leases, fencing tokens, Redis event/command streams and
worker-lost recovery to prevent one session from being executed concurrently by multiple
backend pods. Without that coordination mode, `deploy.sh` fails before calling `kubectl`.

The namespace baseline NetworkPolicy is applied from `networkpolicy.yaml` before migration and
allows only DNS, PostgreSQL, HTTPS service calls and Redis coordination egress for the selected
release pods. Environment-specific ingress-controller, SecretStore, database, object-store,
LightRAG and EduPlus2 allow-listing remains part of the target environment contract.

Optional HPA is a native Kubernetes YAML overlay at `patches/autoscaling/hpa.yaml`. It is
applied only when the release metadata sets `DEEPTUTOR_HPA_ENABLED=true`; no Helm or chart
templating is used.

The following objects are intentionally **pre-provisioned by the target environment contract** and validated by environment registry / Secret preflight before `kubectl apply`:

- `deeptutor-runtime` ServiceAccount and namespace-scoped runtime RBAC.
- `deeptutor-migrator` ServiceAccount and namespace-scoped migration RBAC.
- `deeptutor-runtime-secrets` from the target environment SecretStore / ExternalSecret binding.
- For `test-cn` only, the tag preflight/deploy steps receive Woodpecker's
  `dt_test_cn_eduplus2_webhook_secret`; deploy synchronizes only
  `DT_EDUPLUS2_WEBHOOK_SECRET` in the pre-provisioned runtime Secret before
  rollout. The sync is idempotent, namespace-locked, and never prints the value;
  other runtime Secret keys remain under the target environment's ownership.
- `deeptutor-migrator-secrets` with migrator-only PostgreSQL credentials.
- `deeptutor-deployment-config` ConfigMap projected from the redacted target deployment contract.
- Ingress/TLS issuer, imagePullSecrets and any stricter NetworkPolicy exceptions for the target namespace.
- `DEEPTUTOR_REDIS_URL` in `deeptutor-runtime-secrets` when the environment enables multiple
  backend replicas or HPA.

Do not reuse these names across environments unless the environment registry maps them to the same `target_env_id`. Cross-environment Secret, namespace, Ingress, lock or evidence paths must fail closed in preflight.
