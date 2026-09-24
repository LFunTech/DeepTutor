"""Protected K8s release pipeline command helpers.

The CI helper must be able to execute inside Woodpecker's small utility image
before project dependencies are installed.  When pydantic is available it uses
``protected_k8s_release`` so local tests keep exercising the full contract
models.  When pydantic is absent it falls back to a stdlib-only implementation
for the small gate operations needed by the release pipeline.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
from pathlib import Path
import re
from typing import Any

try:  # pragma: no cover - exercised through the subprocess fallback test.
    from . import protected_k8s_release as _release
except ModuleNotFoundError as exc:  # pragma: no cover - depends on runner image deps.
    if exc.name != "pydantic":
        raise
    _release = None

_CANONICAL_TAG_RE = re.compile(
    r"^deploy/(?P<env_id>[a-z][a-z0-9-]{1,40})/"
    r"(?P<version>v[0-9]+\.[0-9]+\.[0-9]+(-(rc|hotfix)\.[0-9]+)?)$"
)
_SHA_RE = re.compile(r"^[a-fA-F0-9]{40}$")
_LEAK_PATTERNS: dict[str, re.Pattern[str]] = {
    "dot_secrets": re.compile(r"\.secrets"),
    "jwt": re.compile(r"\b(jwt|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.)", re.IGNORECASE),
    "dt_token": re.compile(r"\bdt_token\b|\bdt_[A-Za-z0-9_-]{12,}", re.IGNORECASE),
    "client_secret": re.compile(r"[\"']?client[_-]?secret[\"']?\s*[:=]", re.IGNORECASE),
    "model_key": re.compile(
        r"[\"']?(model|openai|dashscope|bailian)[_-]?api[_-]?key[\"']?\s*[:=]",
        re.IGNORECASE,
    ),
    "kubeconfig": re.compile(r"\b(apiVersion:\s*v1\s+clusters:|KUBECONFIG=)", re.IGNORECASE),
    "private_key": re.compile(r"BEGIN [A-Z ]*PRIVATE KEY"),
    "woodpecker_secret": re.compile(r"WOODPECKER[_-]?SECRET\s*[:=]", re.IGNORECASE),
}
_SENSITIVE_JSON_KEY_RE = re.compile(
    r"(^|_)(client_secret|api_key|password|authorization|bearer|kubeconfig|secret_value)$",
    re.IGNORECASE,
)
_MISSING = object()


def _load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf8"))


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf8",
    )


def _shell_single_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _safe_release_token(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "release"


def _safe_kubernetes_name_token(value: str, *, max_length: int = 52) -> str:
    token = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    token = re.sub(r"-+", "-", token) or "release"
    if len(token) <= max_length:
        return token
    suffix = hashlib.sha256(token.encode("utf8")).hexdigest()[:8]
    return token[: max_length - len(suffix) - 1].rstrip("-") + "-" + suffix


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf8")).hexdigest()[:12]


def _value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _nested(item: Any, keys: tuple[str, ...], default: Any = None) -> Any:
    current = item
    for key in keys:
        current = _value(current, key, _MISSING)
        if current is _MISSING or current is None:
            return default
    return current


def _environments(registry: Any) -> list[Any]:
    return list(_value(registry, "environments", []) or [])


def _find_env(registry: Any, env_id: str) -> Any | None:
    finder = getattr(registry, "find_env", None)
    if callable(finder):
        return finder(env_id)
    for env in _environments(registry):
        if _value(env, "env_id") == env_id:
            return env
    return None


def _ref_summary(value: str | None) -> dict[str, str | None]:
    kind, _, identifier = str(value or "").partition(":")
    return {"kind": kind or None, "id_hash": _hash_text(identifier) if identifier else None}


def _load_registry(path: str):
    if _release is not None:
        return _release.load_registry(path)
    return _load_json(path)


def _secret_redacted_summary(secret: Any) -> dict[str, Any]:
    return {
        "logical_name": str(_value(secret, "logical_name", "")),
        "purpose": str(_value(secret, "purpose", "")),
        "scope_env_id": str(_value(secret, "scope_env_id", "")),
        "ref": _ref_summary(str(_value(secret, "ref", ""))),
        "permission_hash": _hash_text(str(_value(secret, "permission_summary", ""))),
        "rotation_state": str(_value(secret, "rotation_state", "unknown")),
        "least_privilege": bool(_value(secret, "least_privilege", False)),
        "required": bool(_value(secret, "required", True)),
    }


def _redacted_matrix(registry: Any) -> dict[str, Any]:
    redacted_matrix = getattr(registry, "redacted_matrix", None)
    if callable(redacted_matrix):
        return redacted_matrix()
    environments = _environments(registry)
    production_env_ids = [
        str(_value(env, "env_id")) for env in environments if _value(env, "env_class") == "prod"
    ]
    return {
        "registry_version": _value(registry, "registry_version", "unknown"),
        "canonical_tag_regex": _value(registry, "canonical_tag_regex", _CANONICAL_TAG_RE.pattern),
        "production_env_ids": production_env_ids,
        "environments": {
            str(_value(env, "env_id")): {
                "env_id": _value(env, "env_id"),
                "env_class": _value(env, "env_class"),
                "prod_group": _value(env, "prod_group"),
                "verification_status": _value(env, "verification_status", "unverified"),
                "tag_pattern": _value(env, "tag_pattern"),
                "allowed_ref": _value(env, "allowed_ref"),
                "woodpecker": {
                    "server": {"host_hash": _hash_text(str(_nested(env, ("woodpecker", "server_url"), "")))},
                    "server_version": _nested(env, ("woodpecker", "server_version"), ""),
                    "agent_version": _nested(env, ("woodpecker", "agent_version"), ""),
                    "agent_backend": _nested(env, ("woodpecker", "agent_backend"), ""),
                    "protected_refs": list(_nested(env, ("woodpecker", "protected_refs"), []) or []),
                    "approval_required": bool(
                        _nested(env, ("woodpecker", "approval_policy", "required"), False)
                    ),
                    "secret_resolution_mode": _nested(
                        env, ("woodpecker", "secret_resolution_mode"), "unknown"
                    ),
                    "secrets": [
                        _secret_redacted_summary(secret)
                        for secret in _nested(env, ("woodpecker", "secrets"), []) or []
                    ],
                },
                "registry": {
                    "repository_hash": _hash_text(str(_nested(env, ("registry", "repository"), ""))),
                    "credentials_ref": _ref_summary(
                        str(_nested(env, ("registry", "credentials_ref"), ""))
                    ),
                    "immutable_tags": bool(_nested(env, ("registry", "immutable_tags"), True)),
                },
                "kubernetes": {
                    "namespace_hash": _hash_text(str(_nested(env, ("kubernetes", "namespace"), ""))),
                    "backend_executor_replicas": int(
                        _nested(env, ("kubernetes", "backend_executor_replicas"), 1) or 1
                    ),
                    "rollout_strategy": _nested(env, ("kubernetes", "rollout_strategy"), ""),
                    "runtime_coordination": {
                        "backend": _nested(
                            env, ("kubernetes", "runtime_coordination", "backend"), "memory"
                        ),
                    },
                    "autoscaling": _nested(env, ("kubernetes", "autoscaling"), {}) or {},
                },
                "evidence_prefix": _nested(env, ("evidence", "prefix"), ""),
            }
            for env in environments
        },
        "promotion_path": [
            str(_value(env, "env_id"))
            for env in environments
            if _value(env, "env_class") in {"test", "pre", "staging", "prod"}
        ],
        "multi_prod_rule": "each production env requires its own deployment tag, approval, smoke and evidence",
    }


def _ref_matches(pattern: str, ref: str) -> bool:
    return fnmatch.fnmatch(ref, pattern.replace("**", "*"))


def _parse_deployment_tag(tag: str) -> dict[str, str]:
    match = _CANONICAL_TAG_RE.fullmatch(str(tag or "").strip())
    if not match:
        raise ValueError("deployment_tag_invalid")
    return {"env_id": match.group("env_id"), "version": match.group("version"), "raw": tag}


def _validate_release_trigger(
    registry: Any,
    *,
    event: str,
    ref: str,
    tag: str,
    protected_ref: bool,
    approved: bool,
    approval_id: str,
    actor: str,
    tag_object_sha: str,
    commit_sha: str,
    previous_evidence: dict[str, Any] | None = None,
    manual_target_env_id: str | None = None,
    trust_source: str | None = None,
) -> dict[str, Any]:
    if _release is not None:
        return _release.validate_release_trigger(
            registry,
            event=event,
            ref=ref,
            tag=tag,
            protected_ref=protected_ref,
            approved=approved,
            approval_id=approval_id,
            actor=actor,
            tag_object_sha=tag_object_sha,
            commit_sha=commit_sha,
            previous_evidence=previous_evidence,
            manual_target_env_id=manual_target_env_id,
            trust_source=trust_source,
        )

    error_codes: list[str] = []
    parsed: dict[str, str] | None = None
    if event != "tag":
        error_codes.append("event_not_tag")
    try:
        parsed = _parse_deployment_tag(tag)
    except ValueError:
        error_codes.append("deployment_tag_invalid")
    if manual_target_env_id:
        error_codes.append("manual_environment_override_forbidden")

    env = _find_env(registry, parsed["env_id"]) if parsed else None
    if parsed and env is None:
        error_codes.append("environment_not_registered")
    if parsed and parsed["env_id"] in {"prod", "production", "latest", "stable"}:
        error_codes.append("ambiguous_environment_alias")
    if parsed and env is not None and not _ref_matches(str(_value(env, "allowed_ref", "")), ref):
        error_codes.append("ref_environment_mismatch")
    if not protected_ref:
        error_codes.append("tag_not_protected")
    if env is not None and _value(env, "env_class") == "prod":
        approval_policy = _nested(env, ("woodpecker", "approval_policy"), {}) or {}
        if bool(_value(approval_policy, "required", False)):
            if not approved or not approval_id:
                error_codes.append("prod_approval_missing")
            approvers = tuple(_value(approval_policy, "approvers", ()) or ())
            if approvers and actor not in approvers:
                error_codes.append("prod_approval_actor_unauthorized")

    if previous_evidence and parsed:
        historical = {
            "target_env_id": previous_evidence.get("target_env_id"),
            "version": previous_evidence.get("version"),
            "tag_object_sha": previous_evidence.get("tag_object_sha"),
            "commit_sha": previous_evidence.get("commit_sha"),
        }
        current = {
            "target_env_id": parsed["env_id"],
            "version": parsed["version"],
            "tag_object_sha": tag_object_sha,
            "commit_sha": commit_sha,
        }
        if historical != current:
            error_codes.append("deployment_tag_reused_or_moved")

    for name, value in {"tag_object_sha": tag_object_sha, "commit_sha": commit_sha}.items():
        if not _SHA_RE.fullmatch(str(value or "")):
            error_codes.append(name + "_invalid")

    return {
        "ready": not error_codes,
        "error_codes": sorted(set(error_codes)),
        "event": event,
        "ref_hash": _hash_text(ref),
        "tag": parsed["raw"] if parsed else tag,
        "target_env_id": parsed["env_id"] if parsed else None,
        "version": parsed["version"] if parsed else None,
        "tag_object_sha": tag_object_sha,
        "commit_sha": commit_sha,
        "approval": {
            "approved": approved,
            "approval_id_hash": _hash_text(approval_id) if approval_id else None,
        },
        "actor_hash": _hash_text(actor),
        "trust_source": trust_source or "caller-supplied",
    }


def _secret_preflight(
    registry: Any,
    target_env_id: str,
    available_secrets: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if _release is not None:
        return _release.secret_preflight(registry, target_env_id, available_secrets)

    env = _find_env(registry, target_env_id)
    if env is None:
        return {
            "ready": False,
            "target_env_id": target_env_id,
            "error_codes": ["environment_not_registered"],
        }
    error_codes: list[str] = []
    summaries: list[dict[str, Any]] = []
    for secret in _nested(env, ("woodpecker", "secrets"), []) or []:
        if not bool(_value(secret, "required", True)):
            continue
        logical_name = str(_value(secret, "logical_name", ""))
        observed = available_secrets.get(logical_name)
        if not observed or observed.get("present") is False:
            error_codes.append("secret_missing:" + logical_name)
            summaries.append({**_secret_redacted_summary(secret), "status": "missing"})
            continue
        scope = str(observed.get("scope_env_id") or "")
        least_privilege = bool(observed.get("least_privilege"))
        rotation_state = str(observed.get("rotation_state") or "unknown")
        permission_summary = str(observed.get("permission_summary") or "")
        if scope != target_env_id:
            error_codes.append("secret_scope_mismatch:" + logical_name)
        lowered_permission = permission_summary.lower()
        if (
            not least_privilege
            or "superuser" in lowered_permission
            or "root" in lowered_permission
            or lowered_permission.endswith(":*")
        ):
            error_codes.append("secret_over_privileged:" + logical_name)
        if rotation_state != "current":
            error_codes.append("secret_rotation_not_current:" + logical_name)
        summaries.append(
            {
                **_secret_redacted_summary(secret),
                "status": "available",
                "observed_scope_env_id": scope,
                "observed_permission_hash": _hash_text(permission_summary),
                "observed_rotation_state": rotation_state,
                "observed_least_privilege": least_privilege,
            }
        )
    return {
        "ready": not error_codes,
        "target_env_id": target_env_id,
        "secret_resolution_mode": _nested(env, ("woodpecker", "secret_resolution_mode"), "unknown"),
        "error_codes": sorted(set(error_codes)),
        "secrets": summaries,
    }


def _json_secret_key_leaks(value: Any) -> list[str]:
    leaks: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            if _SENSITIVE_JSON_KEY_RE.search(key_text) and item not in (None, "", "[REDACTED]"):
                leaks.append("json_sensitive_key:" + key_text)
            leaks.extend(_json_secret_key_leaks(item))
    elif isinstance(value, list):
        for item in value:
            leaks.extend(_json_secret_key_leaks(item))
    return leaks


def _scan_secret_leakage(path: str | Path) -> dict[str, Any]:
    if _release is not None:
        return _release.scan_secret_leakage(path)

    root = Path(path)
    leaks: list[dict[str, str]] = []
    files = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
    for file_path in files:
        try:
            text = file_path.read_text(encoding="utf8")
        except UnicodeDecodeError:
            continue
        relative = str(file_path.relative_to(root if root.is_dir() else root.parent))
        for code, pattern in _LEAK_PATTERNS.items():
            if pattern.search(text):
                leaks.append({"file": relative, "code": code})
        if file_path.suffix.lower() in {".json", ".jsonl"}:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if parsed is not None:
                for code in _json_secret_key_leaks(parsed):
                    leaks.append({"file": relative, "code": code})
    return {
        "ready": not leaks,
        "error_codes": [] if not leaks else ["secret_leak_detected"],
        "leaks": leaks,
    }


def _trusted_trigger_report(args: argparse.Namespace):
    registry = _load_registry(args.registry)
    metadata = _load_json(args.trusted_metadata)
    missing = [
        name
        for name in (
            "protected_ref",
            "approved",
            "approval_id",
            "actor",
            "tag_object_sha",
            "commit_sha",
            "trust_source",
        )
        if name not in metadata
    ]
    if missing:
        raise SystemExit("trusted metadata missing fields: " + ",".join(sorted(missing)))
    report = _validate_release_trigger(
        registry,
        event=args.event,
        ref=args.ref,
        tag=args.tag,
        protected_ref=bool(metadata.get("protected_ref")),
        approved=bool(metadata.get("approved")),
        approval_id=str(metadata.get("approval_id") or ""),
        actor=str(metadata.get("actor") or ""),
        tag_object_sha=str(metadata.get("tag_object_sha") or ""),
        commit_sha=str(metadata.get("commit_sha") or ""),
        manual_target_env_id=args.manual_target_env_id,
        previous_evidence=_load_json(args.previous_evidence) if args.previous_evidence else None,
        trust_source=str(metadata.get("trust_source") or ""),
    )
    return registry, report


def _matrix(args: argparse.Namespace) -> dict[str, str]:
    registry = _load_registry(args.registry)
    output = Path(args.output) / "environment-matrix.json"
    _write_json(output, _redacted_matrix(registry))
    return {"matrix": str(output)}


def _preflight(args: argparse.Namespace) -> dict[str, str]:
    registry = _load_registry(args.registry)
    available = _load_json(args.available_secrets)
    output = Path(args.output) / "secret-preflight.json"
    _write_json(output, _secret_preflight(registry, args.target_env_id, available))
    return {"secret_preflight": str(output)}


def _trigger(args: argparse.Namespace) -> dict[str, str]:
    _registry, report = _trusted_trigger_report(args)
    output = Path(args.output) / "trigger-gate.json"
    _write_json(output, report)
    return {"trigger_gate": str(output)}


def _release_env_values(registry, report: dict) -> dict[str, str]:
    target_env_id = str(report.get("target_env_id") or "")
    version = str(report.get("version") or "")
    tag = str(report.get("tag") or "")
    env = _find_env(registry, target_env_id)
    if env is None:
        raise SystemExit("release target environment is not registered")
    release_id = _safe_kubernetes_name_token(f"{target_env_id}-{version}")
    image_tag = _safe_release_token(tag)
    autoscaling = _nested(env, ("kubernetes", "autoscaling"), {}) or {}
    backend_replicas = int(_nested(env, ("kubernetes", "backend_executor_replicas"), 1) or 1)
    autoscaling_enabled = bool(_value(autoscaling, "enabled", False))
    execution_mode = "replicated" if backend_replicas > 1 or autoscaling_enabled else "single"
    return {
        "DEEPTUTOR_TARGET_ENV_ID": target_env_id,
        "DEEPTUTOR_RELEASE_VERSION": version,
        "DEEPTUTOR_RELEASE_TAG": tag,
        "DEEPTUTOR_IMAGE_TAG": image_tag,
        "DEEPTUTOR_RELEASE_ID": release_id,
        "DEEPTUTOR_REGISTRY_REPOSITORY": str(_nested(env, ("registry", "repository"), "")).rstrip("/"),
        "DEEPTUTOR_EVIDENCE_DIR": str(Path(str(_nested(env, ("evidence", "prefix"), ""))) / version),
        "DEEPTUTOR_K8S_NAMESPACE": str(_nested(env, ("kubernetes", "namespace"), "")),
        "DEEPTUTOR_INGRESS_HOST": str(_nested(env, ("kubernetes", "ingress_host"), "")),
        "DEEPTUTOR_TLS_SECRET_NAME": str(
            _nested(env, ("kubernetes", "tls_secret_ref"), "")
        ).rsplit("/", 1)[-1],
        "DEEPTUTOR_RELEASE_LOCK_REF": str(_nested(env, ("release_control", "release_lock_ref"), "")),
        "DEEPTUTOR_MIGRATION_LOCK_REF": str(
            _nested(env, ("release_control", "migration_lock_ref"), "")
        ),
        "DEEPTUTOR_BACKEND_EXECUTOR_REPLICAS": str(backend_replicas),
        "DEEPTUTOR_EXECUTION_MODE": execution_mode,
        "DEEPTUTOR_TURN_COORDINATION_BACKEND": str(
            _nested(env, ("kubernetes", "runtime_coordination", "backend"), "memory")
        ),
        "DEEPTUTOR_REDIS_KEY_PREFIX": _safe_release_token(f"deeptutor-{target_env_id}"),
        "DEEPTUTOR_HPA_ENABLED": "true" if autoscaling_enabled else "false",
        "DEEPTUTOR_HPA_MIN_REPLICAS": str(_value(autoscaling, "min_replicas", 1)),
        "DEEPTUTOR_HPA_MAX_REPLICAS": str(_value(autoscaling, "max_replicas", 1)),
        "DEEPTUTOR_HPA_TARGET_CPU_UTILIZATION_PERCENTAGE": str(
            _value(autoscaling, "target_cpu_utilization_percentage", None) or 70
        ),
    }


def _write_env_file(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Generated by protected-k8s-release prepare-metadata; source this file in CI.\n"]
    for key in sorted(values):
        lines.append(f"export {key}={_shell_single_quote(values[key])}\n")
    path.write_text("".join(lines), encoding="utf8")


def _prepare_metadata(args: argparse.Namespace) -> dict[str, str]:
    registry, report = _trusted_trigger_report(args)
    output = Path(args.output)
    gate_path = output / "trigger-gate.json"
    _write_json(gate_path, report)
    if not report.get("ready"):
        raise SystemExit("release trigger not ready: " + ",".join(report.get("error_codes", [])))
    env_path = Path(args.output_env_file)
    _write_env_file(env_path, _release_env_values(registry, report))
    return {"trigger_gate": str(gate_path), "release_env": str(env_path)}


def _scan(args: argparse.Namespace) -> dict[str, str]:
    report = _scan_secret_leakage(args.path)
    output = Path(args.output) / "secret-leakage-scan.json"
    _write_json(output, report)
    return {"secret_leakage_scan": str(output)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    sub = parser.add_subparsers(dest="command", required=True)

    matrix = sub.add_parser("matrix", allow_abbrev=False)
    matrix.add_argument("--registry", required=True)
    matrix.add_argument("--output", required=True)

    preflight = sub.add_parser("preflight", allow_abbrev=False)
    preflight.add_argument("--registry", required=True)
    preflight.add_argument("--target-env-id", required=True)
    preflight.add_argument("--available-secrets", required=True)
    preflight.add_argument("--output", required=True)

    trigger = sub.add_parser("trigger", allow_abbrev=False)
    trigger.add_argument("--registry", required=True)
    trigger.add_argument("--event", required=True)
    trigger.add_argument("--ref", required=True)
    trigger.add_argument("--tag", required=True)
    trigger.add_argument(
        "--trusted-metadata",
        required=True,
        help="JSON from a trusted VCS/Woodpecker approval verifier; not PR-editable YAML.",
    )
    trigger.add_argument("--manual-target-env-id")
    trigger.add_argument("--previous-evidence")
    trigger.add_argument("--output", required=True)

    prepare = sub.add_parser("prepare-metadata", allow_abbrev=False)
    prepare.add_argument("--registry", required=True)
    prepare.add_argument("--event", required=True)
    prepare.add_argument("--ref", required=True)
    prepare.add_argument("--tag", required=True)
    prepare.add_argument(
        "--trusted-metadata",
        required=True,
        help="JSON from a trusted VCS/Woodpecker approval verifier; not PR-editable YAML.",
    )
    prepare.add_argument("--manual-target-env-id")
    prepare.add_argument("--previous-evidence")
    prepare.add_argument("--output-env-file", required=True)
    prepare.add_argument("--output", required=True)

    scan = sub.add_parser("scan-evidence", allow_abbrev=False)
    scan.add_argument("--path", required=True)
    scan.add_argument("--output", required=True)

    args = parser.parse_args(argv)
    if args.command == "matrix":
        print(json.dumps(_matrix(args), ensure_ascii=False))
        return 0
    if args.command == "preflight":
        print(json.dumps(_preflight(args), ensure_ascii=False))
        return 0
    if args.command == "trigger":
        print(json.dumps(_trigger(args), ensure_ascii=False))
        return 0
    if args.command == "prepare-metadata":
        print(json.dumps(_prepare_metadata(args), ensure_ascii=False))
        return 0
    if args.command == "scan-evidence":
        print(json.dumps(_scan(args), ensure_ascii=False))
        return 0
    raise RuntimeError("unsupported command")


if __name__ == "__main__":
    raise SystemExit(main())
