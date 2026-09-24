# Protected K8s release evidence template

Evidence path MUST be partitioned as:

```text
release-evidence/<target-env-id>/<version>/
  deployment-contract.json
  manifest.json
  migration.json
  deploy.json
  smoke.json
  rollback.json
  upstream-compat.md
  unresolved.md
```

Required fields:

- `target_env_id`, `env_class`, optional `prod_group`, canonical deployment tag and version.
- tag object SHA, source commit SHA, upstream SHA, tag creator hash and approval id hash.
- Woodpecker secret preflight redacted summary; record secret name/ref hashes and permission hashes only.
- backend/frontend image digests; mutable tags are not accepted.
- migration exit code, `schema_history` state, release lock and migration lock evidence.
- deploy/rollout exit code, readiness result and single-executor non-overlap evidence.
- smoke run id, request id short hash, case summary and failure code.
- rollback result or maintenance/forward-fix decision.
- unresolved/unverified items per environment; one prod env cannot substitute another.

脱敏要求：不得包含 JWT、dt_token、client secret、模型 key、Woodpecker secret 明文、Kubeconfig 明文、`.secrets` 内容或用户隐私/业务正文。每次上传前运行 `python -m deeptutor_enterprise.protected_k8s_release_cli scan-evidence`。
