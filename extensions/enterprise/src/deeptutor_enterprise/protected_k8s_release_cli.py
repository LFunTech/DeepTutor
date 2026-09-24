"""Protected K8s release pipeline command helpers."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from .protected_k8s_release import (
    load_registry,
    scan_secret_leakage,
    secret_preflight,
    validate_release_trigger,
)


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


def _trusted_trigger_report(args: argparse.Namespace):
    registry = load_registry(args.registry)
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
    report = validate_release_trigger(
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
    registry = load_registry(args.registry)
    output = Path(args.output) / "environment-matrix.json"
    _write_json(output, registry.redacted_matrix())
    return {"matrix": str(output)}


def _preflight(args: argparse.Namespace) -> dict[str, str]:
    registry = load_registry(args.registry)
    available = _load_json(args.available_secrets)
    output = Path(args.output) / "secret-preflight.json"
    _write_json(output, secret_preflight(registry, args.target_env_id, available))
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
    env = registry.find_env(target_env_id)
    if env is None:
        raise SystemExit("release target environment is not registered")
    release_id = _safe_kubernetes_name_token(f"{target_env_id}-{version}")
    image_tag = _safe_release_token(tag)
    autoscaling = env.kubernetes.autoscaling
    execution_mode = (
        "replicated"
        if env.kubernetes.backend_executor_replicas > 1 or autoscaling.enabled
        else "single"
    )
    return {
        "DEEPTUTOR_TARGET_ENV_ID": target_env_id,
        "DEEPTUTOR_RELEASE_VERSION": version,
        "DEEPTUTOR_RELEASE_TAG": tag,
        "DEEPTUTOR_IMAGE_TAG": image_tag,
        "DEEPTUTOR_RELEASE_ID": release_id,
        "DEEPTUTOR_REGISTRY_REPOSITORY": env.registry.repository.rstrip("/"),
        "DEEPTUTOR_EVIDENCE_DIR": str(Path(env.evidence.prefix) / version),
        "DEEPTUTOR_K8S_NAMESPACE": env.kubernetes.namespace,
        "DEEPTUTOR_INGRESS_HOST": env.kubernetes.ingress_host,
        "DEEPTUTOR_TLS_SECRET_NAME": env.kubernetes.tls_secret_ref.rsplit("/", 1)[-1],
        "DEEPTUTOR_RELEASE_LOCK_REF": env.release_control.release_lock_ref,
        "DEEPTUTOR_MIGRATION_LOCK_REF": env.release_control.migration_lock_ref,
        "DEEPTUTOR_BACKEND_EXECUTOR_REPLICAS": str(env.kubernetes.backend_executor_replicas),
        "DEEPTUTOR_EXECUTION_MODE": execution_mode,
        "DEEPTUTOR_TURN_COORDINATION_BACKEND": env.kubernetes.runtime_coordination.backend,
        "DEEPTUTOR_REDIS_KEY_PREFIX": _safe_release_token(f"deeptutor-{target_env_id}"),
        "DEEPTUTOR_HPA_ENABLED": "true" if autoscaling.enabled else "false",
        "DEEPTUTOR_HPA_MIN_REPLICAS": str(autoscaling.min_replicas),
        "DEEPTUTOR_HPA_MAX_REPLICAS": str(autoscaling.max_replicas),
        "DEEPTUTOR_HPA_TARGET_CPU_UTILIZATION_PERCENTAGE": str(
            autoscaling.target_cpu_utilization_percentage or 70
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
    report = scan_secret_leakage(args.path)
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
