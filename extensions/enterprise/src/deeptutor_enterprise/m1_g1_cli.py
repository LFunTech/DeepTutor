"""M1/G1 release evidence 命令行工具。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .configuration import DeploymentConfig
from .m1_g1 import (
    ReleaseEvidence,
    TargetDeploymentContract,
    build_governance_projection,
    build_resource_binding_evidence,
    deployment_contract_inventory,
)


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name, default).strip()
    if not value:
        raise RuntimeError(f"required environment variable is missing: {name}")
    return value


def _evidence(args: argparse.Namespace) -> dict[str, str]:
    image_digest = Path(args.image_digest_file).read_text(encoding="utf8").strip()
    release = ReleaseEvidence(
        release_id=args.release_id,
        source_sha=_env("CI_COMMIT_SHA", args.release_id),
        upstream_sha=_env("M1_G1_UPSTREAM_SHA"),
        backend_image_digest=image_digest,
        frontend_image_digest=_env("M1_G1_FRONTEND_DIGEST"),
        schema_version=_env("M1_G1_SCHEMA_VERSION"),
        runtime_mode=_env("M1_G1_ENVIRONMENT"),
        secret_refs=[
            "env:DT_DATABASE_DSN",
            "env:DT_MIGRATION_DATABASE_DSN",
            "env:DT_MODEL_API_KEY",
            "env:DT_OBJECTSTORE_ACCESS_KEY",
            "env:DT_OBJECTSTORE_SECRET_KEY",
            "env:DT_LIGHTRAG_API_KEY",
            "env:DT_EDUPLUS2_CLIENT_SECRET",
        ],
        smoke_run_id=_env("M1_G1_SMOKE_RUN_ID", "pending-smoke-run-id"),
        approval=_env("M1_G1_APPROVAL_ID"),
        unresolved=[item for item in os.environ.get("M1_G1_UNRESOLVED", "").split(",") if item],
    )
    output = release.write(
        args.output,
        extra={
            "woodpecker_run": os.environ.get("CI_PIPELINE_NUMBER", ""),
            "environment": os.environ.get("M1_G1_ENVIRONMENT", ""),
        },
    )
    return {"evidence": str(output)}


def _contract(args: argparse.Namespace) -> dict[str, str]:
    payload = json.loads(Path(args.input).read_text(encoding="utf8"))
    payload = {key: value for key, value in payload.items() if not str(key).startswith("x_")}
    contract = TargetDeploymentContract.model_validate(payload)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "deployment-contract.json"
    output.write_text(
        json.dumps(
            deployment_contract_inventory(contract),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf8",
    )
    return {"deployment_contract": str(output)}


def _load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf8"))


def _governance(args: argparse.Namespace) -> dict[str, str]:
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "governance-projection.json"
    audit_export = _load_json(args.audit_export) if args.audit_export else {}
    projection = build_governance_projection(
        release_evidence=_load_json(args.release_evidence),
        deployment_contract=_load_json(args.deployment_contract),
        audit_export=audit_export,
    )
    output.write_text(
        json.dumps(projection, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf8",
    )
    return {"governance_projection": str(output)}


def _resources(args: argparse.Namespace) -> dict[str, str]:
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "resource-binding.json"
    config = DeploymentConfig.model_validate(_load_json(args.deployment))
    payload = build_resource_binding_evidence(
        config,
        object_manifest_hash=args.object_manifest_hash,
        lightrag_service_status=args.lightrag_service_status,
        cleanup_result=args.cleanup_result,
        lightrag_sample_ready=args.lightrag_sample_ready,
    )
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf8",
    )
    return {"resource_binding": str(output)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    sub = parser.add_subparsers(dest="command", required=True)
    evidence = sub.add_parser("evidence", allow_abbrev=False)
    evidence.add_argument("--release-id", required=True)
    evidence.add_argument("--image-digest-file", required=True)
    evidence.add_argument("--output", required=True)
    contract = sub.add_parser("contract", allow_abbrev=False)
    contract.add_argument("--input", required=True)
    contract.add_argument("--output", required=True)
    governance = sub.add_parser("governance", allow_abbrev=False)
    governance.add_argument("--release-evidence", required=True)
    governance.add_argument("--deployment-contract", required=True)
    governance.add_argument("--audit-export")
    governance.add_argument("--output", required=True)
    resources = sub.add_parser("resources", allow_abbrev=False)
    resources.add_argument("--deployment", required=True)
    resources.add_argument("--object-manifest-hash", required=True)
    resources.add_argument("--lightrag-service-status", required=True)
    resources.add_argument("--cleanup-result", required=True)
    resources.add_argument("--lightrag-sample-ready", action="store_true")
    resources.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    if args.command == "evidence":
        print(json.dumps(_evidence(args), ensure_ascii=False))
        return 0
    if args.command == "contract":
        print(json.dumps(_contract(args), ensure_ascii=False))
        return 0
    if args.command == "governance":
        print(json.dumps(_governance(args), ensure_ascii=False))
        return 0
    if args.command == "resources":
        print(json.dumps(_resources(args), ensure_ascii=False))
        return 0
    raise RuntimeError("unsupported command")


if __name__ == "__main__":
    raise SystemExit(main())
