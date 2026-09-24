#!/usr/bin/env bash
set -euo pipefail

TARGET_ENV_ID="${1:-}"
if [[ ! "$TARGET_ENV_ID" =~ ^[a-z][a-z0-9-]{1,40}$ ]]; then
  echo "target env id is required" >&2
  exit 2
fi

"${PYTHON:-python3}" - "$TARGET_ENV_ID" <<'PY'
from __future__ import annotations

import json
import os
import sys

TARGET_ENV_ID = sys.argv[1]
PURPOSES = {
    "REGISTRY_PUSH_TOKEN": "registry_push",
    "KUBE_DEPLOY_TOKEN": "k8s_deploy",
    "SECRETSTORE_ROLE": "secret_store",
    "PG_MIGRATOR_DSN": "pg_migrator",
    "APP_DB_SECRET_REF": "runtime_secret_ref",
    "OBJECTSTORE_SECRET_REF": "runtime_secret_ref",
    "LIGHTRAG_API_SECRET_REF": "runtime_secret_ref",
    "EDUPLUS2_CLIENT_SECRET_REF": "runtime_secret_ref",
    "SMOKE_TOKEN_ISSUER_SECRET": "smoke_credentials",
    "EVIDENCE_STORE_WRITE_TOKEN": "evidence_store",
    "VCS_TAG_VERIFY_TOKEN": "tag_approval_verify",
}

payload = {}
for name, purpose in PURPOSES.items():
    payload[name] = {
        "present": bool(os.environ.get(name)),
        "scope_env_id": os.environ.get(name + "_SCOPE_ENV_ID", ""),
        "least_privilege": os.environ.get(name + "_LEAST_PRIVILEGE", "false").lower() == "true",
        "rotation_state": os.environ.get(name + "_ROTATION_STATE", "unknown"),
        "permission_summary": os.environ.get(name + "_PERMISSION_SUMMARY", ""),
    }
metadata_raw = os.environ.get("SECRET_PREFLIGHT_METADATA_JSON")
if metadata_raw:
    try:
        metadata = json.loads(metadata_raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"SECRET_PREFLIGHT_METADATA_JSON is not valid JSON: {exc}") from exc
    if not isinstance(metadata, dict):
        raise SystemExit("SECRET_PREFLIGHT_METADATA_JSON must be a JSON object")
    allowed_fields = {
        "scope_env_id",
        "least_privilege",
        "rotation_state",
        "permission_summary",
    }
    for name, fields in metadata.items():
        if name not in payload or not isinstance(fields, dict):
            continue
        for field in allowed_fields:
            if field in fields:
                value = fields[field]
                if field == "least_privilege":
                    if isinstance(value, bool):
                        payload[name][field] = value
                    elif isinstance(value, str):
                        payload[name][field] = value.lower() == "true"
                    else:
                        payload[name][field] = False
                else:
                    payload[name][field] = str(value)
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
PY
