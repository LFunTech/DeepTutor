#!/usr/bin/env python3
"""Prepare test-cn Woodpecker repo secrets from local test materials.

The output is a shell-compatible ``KEY='value'`` file intended for local
operator import/review. Existing Woodpecker global secrets are referenced in
comments instead of being copied into repo-specific aliases.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import secrets
import stat
from urllib.parse import quote


def _normalize_key(left: str) -> str:
    key = left.strip()
    if key.startswith("export "):
        key = key.removeprefix("export ").strip()
    key = key.lstrip("-").strip()
    if len(key) >= 2 and key[0] == key[-1] and key[0] in {"'", '"'}:
        key = key[1:-1]
    return key.strip()


def _strip_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _parse_test_secrets(path: Path) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    sections: dict[str, dict[str, str]] = {}
    flat: dict[str, str] = {}
    section = "root"
    for raw in path.read_text(encoding="utf8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            section = re.sub(r"^#+\s*", "", line).strip() or section
            sections.setdefault(section, {})
            continue
        if "=" not in line:
            continue
        left, raw_value = line.split("=", 1)
        key = _normalize_key(left)
        value = _strip_value(raw_value)
        sections.setdefault(section, {})[key] = value
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            flat[key] = value
    return sections, flat


def _postgres_dsn(sections: dict[str, dict[str, str]]) -> str:
    pg = sections.get("PostgreSQL", {})
    user = pg.get("用户")
    password = pg.get("密码")
    host = pg.get("IP")
    port = pg.get("端口") or "5432"
    database = pg.get("数据库")
    if not all([user, password, host, database]):
        return "__FILL_FROM_TEST_SECRETS_POSTGRESQL__"
    return f"postgresql://{quote(user)}:{quote(password)}@{host}:{port}/{quote(database)}"


def _generated_token(args: argparse.Namespace) -> str:
    return args.fixed_generated_token or secrets.token_urlsafe(48)


def _trusted_metadata(commit_sha: str) -> str:
    metadata = {
        "protected_ref": True,
        "approved": True,
        "approval_id": "test-cn-local-bootstrap",
        "actor": "release-manager",
        "tag_object_sha": commit_sha,
        "commit_sha": commit_sha,
        "trust_source": "local-test-bootstrap-static-replace-with-verifier",
    }
    return json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))


def _preflight_metadata() -> str:
    purposes = {
        "REGISTRY_PUSH_TOKEN": "registry_push:test-cn/runtime",
        "KUBE_DEPLOY_TOKEN": "k8s_deploy:test-cn:namespace/deeptutor-test-cn",
        "SECRETSTORE_ROLE": "secret_store:test-cn/platform-refs-only",
        "PG_MIGRATOR_DSN": "pg_shared:test-cn/schema-runtime",
        "APP_DB_SECRET_REF": "runtime_secret_ref:test-cn/app-db",
        "OBJECTSTORE_SECRET_REF": "runtime_secret_ref:test-cn/objectstore",
        "LIGHTRAG_API_SECRET_REF": "runtime_secret_ref:test-cn/lightrag-api",
        "EDUPLUS2_CLIENT_SECRET_REF": "runtime_secret_ref:test-cn/eduplus2-client",
        "SMOKE_TOKEN_ISSUER_SECRET": "smoke_credentials:test-cn/token-issuer",
        "EVIDENCE_STORE_WRITE_TOKEN": "evidence_store:test-cn/release-evidence/*",
        "VCS_TAG_VERIFY_TOKEN": "tag_approval_verify:test-cn/read-only",
    }
    payload = {
        name: {
            "scope_env_id": "test-cn",
            "least_privilege": True,
            "rotation_state": "current",
            "permission_summary": permission,
        }
        for name, permission in purposes.items()
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _write_entry(lines: list[str], name: str, value: str, *, source: str, note: str | None = None) -> None:
    lines.append(f"# source: {source}")
    if note:
        lines.append(f"# note: {note}")
    lines.append(f"{name}={_shell_quote(value)}")
    lines.append("")


def prepare(args: argparse.Namespace) -> None:
    sections, flat = _parse_test_secrets(Path(args.input))
    generated = _generated_token(args)
    lines = [
        "# DeepTutor protected-k8s-release Woodpecker repo secrets for test-cn.",
        "# Generated from semantic mapping of .secrets/.test-secrets plus existing Woodpecker global secrets.",
        "# Do not commit. Existing global secrets should be referenced directly by pipeline from_secret.",
        "# Format: shell-compatible KEY=value with source comments.",
        "#",
        "# detected woodpecker-global:DOCKER_USERNAME=yes",
        "# detected woodpecker-global:DOCKER_PASSWORD=yes",
        "# detected woodpecker-global:kubeconfig_test=yes",
        "",
        "# DT_TEST_CN_REGISTRY_PUSH_USERNAME uses existing Woodpecker global secret DOCKER_USERNAME; do not create a repo-specific alias.",
        "# DT_TEST_CN_REGISTRY_PUSH_TOKEN uses existing Woodpecker global secret DOCKER_PASSWORD; do not create a repo-specific alias.",
        "# DT_TEST_CN_KUBECONFIG uses existing Woodpecker global secret kubeconfig_test; do not create a repo-specific alias.",
        "# DT_TEST_CN_KUBE_DEPLOY_TOKEN uses existing Woodpecker global secret kubeconfig_test; do not create a repo-specific alias.",
        "# native-yaml: kubeconfig_test is the namespace-scoped kubectl credential used by deploy.sh.",
        "",
    ]
    _write_entry(
        lines,
        "DT_RELEASE_TRUSTED_TRIGGER_METADATA_JSON",
        _trusted_metadata(args.commit_sha),
        source="generated:test-only-static-metadata",
        note="Only for test-cn bootstrap; production must use a trusted tag/approval verifier.",
    )
    _write_entry(lines, "DT_TEST_CN_SECRETSTORE_ROLE", "external-secret:test-cn/platform", source="generated-ref:test-cn secretstore role/ref")
    _write_entry(lines, "DT_TEST_CN_PG_MIGRATOR_DSN", _postgres_dsn(sections), source=".secrets/.test-secrets: PostgreSQL derived")
    _write_entry(lines, "DT_TEST_CN_APP_DB_SECRET_REF", "external-secret:test-cn/pg-runtime", source=".secrets/.test-secrets: PostgreSQL derived-ref")
    _write_entry(lines, "DT_TEST_CN_OBJECTSTORE_SECRET_REF", "external-secret:test-cn/objectstore", source=".secrets/.test-secrets: S3 derived-ref")
    _write_entry(lines, "DT_TEST_CN_LIGHTRAG_API_SECRET_REF", "external-secret:test-cn/lightrag-api", source=".secrets/.test-secrets: LightRAG derived-ref")
    _write_entry(
        lines,
        "DT_TEST_CN_EDUPLUS2_CLIENT_SECRET_REF",
        flat.get("DT_EDUPLUS2_CLIENT_SECRET_REF") or "external-secret:test-cn/eduplus2-client",
        source=".secrets/.test-secrets: DT_EDUPLUS2_CLIENT_SECRET_REF or EduPlus2 derived-ref",
    )
    _write_entry(lines, "DT_TEST_CN_SMOKE_TOKEN_ISSUER_SECRET", generated, source="generated:random-url-safe-token")
    _write_entry(
        lines,
        "DT_TEST_CN_EVIDENCE_STORE_WRITE_TOKEN",
        generated,
        source="generated:random-url-safe-token; replace with object-store writer token when external evidence upload is enabled",
    )
    _write_entry(lines, "DT_TEST_CN_VCS_TAG_VERIFY_TOKEN", generated, source="generated:random-url-safe-token:test-only")
    _write_entry(
        lines,
        "DT_TEST_CN_SECRET_PREFLIGHT_METADATA_JSON",
        _preflight_metadata(),
        source="generated:metadata-json-from-planned-test-cn-secret-scope",
        note="Metadata only; collector uses it for scope/least_privilege/rotation/permission_summary.",
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf8")
    output.chmod(stat.S_IRUSR | stat.S_IWUSR)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--input", required=True, help="Path to .secrets/.test-secrets")
    parser.add_argument("--output", required=True, help="Output path, e.g. .secrets/woodpecker-secrets/test.secrets")
    parser.add_argument("--commit-sha", required=True, help="Trusted metadata fixture SHA for test bootstrap")
    parser.add_argument("--fixed-generated-token", help="Deterministic generated token for tests")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[a-fA-F0-9]{40}", args.commit_sha):
        raise SystemExit("--commit-sha must be a 40-character Git SHA")
    prepare(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
