"""Protected K8s release pipeline gates."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_SHA_A = "a" * 40
_SHA_B = "b" * 40
_TAG_SHA = "c" * 40


def _secret(env_id: str, name: str, purpose: str, *, ref_suffix: str | None = None) -> dict:
    env_key = env_id.upper().replace("-", "_")
    return {
        "logical_name": name,
        "ref": f"woodpecker:DT_{env_key}_{ref_suffix or name}",
        "purpose": purpose,
        "scope_env_id": env_id,
        "permission_summary": f"{purpose}:{env_id}",
        "rotation_state": "current",
        "least_privilege": True,
        "required": True,
    }


def _runtime_coordination(env_id: str, backend: str = "memory") -> dict:
    if backend == "redis":
        return {
            "backend": "redis",
            "redis_secret_ref": f"external-secret:{env_id}/runtime-redis",
            "shared_turn_leases": True,
            "shared_event_stream": True,
            "fencing_tokens": True,
            "worker_recovery": True,
            "consistency_evidence_ref": f"release-evidence/{env_id}/runtime-coordination",
        }
    return {
        "backend": "memory",
        "redis_secret_ref": None,
        "shared_turn_leases": False,
        "shared_event_stream": False,
        "fencing_tokens": True,
        "worker_recovery": False,
        "consistency_evidence_ref": "",
    }


def _autoscaling(
    *,
    enabled: bool = False,
    min_replicas: int = 1,
    max_replicas: int = 1,
    target_cpu_utilization_percentage: int | None = None,
) -> dict:
    return {
        "enabled": enabled,
        "min_replicas": min_replicas,
        "max_replicas": max_replicas,
        "target_cpu_utilization_percentage": target_cpu_utilization_percentage,
    }


def _environment(
    env_id: str,
    env_class: str,
    *,
    prod_group: str | None = None,
    backend_executor_replicas: int = 1,
    rollout_strategy: str = "single-executor-drain",
    runtime_coordination: dict | None = None,
    autoscaling: dict | None = None,
) -> dict:
    required = [
        ("REGISTRY_PUSH_TOKEN", "registry_push"),
        ("KUBE_DEPLOY_TOKEN", "k8s_deploy"),
        ("SECRETSTORE_ROLE", "secret_store"),
        ("PG_MIGRATOR_DSN", "pg_migrator"),
        ("APP_DB_SECRET_REF", "runtime_secret_ref"),
        ("OBJECTSTORE_SECRET_REF", "runtime_secret_ref"),
        ("LIGHTRAG_API_SECRET_REF", "runtime_secret_ref"),
        ("EDUPLUS2_CLIENT_SECRET_REF", "runtime_secret_ref"),
        ("SMOKE_TOKEN_ISSUER_SECRET", "smoke_credentials"),
        ("EVIDENCE_STORE_WRITE_TOKEN", "evidence_store"),
        ("VCS_TAG_VERIFY_TOKEN", "tag_approval_verify"),
    ]
    return {
        "env_id": env_id,
        "env_class": env_class,
        "prod_group": prod_group,
        "verification_status": "unverified",
        "tag_pattern": f"deploy/{env_id}/v*",
        "allowed_ref": f"refs/tags/deploy/{env_id}/**",
        "woodpecker": {
            "server_url": f"https://woodpecker-{env_id}.example.internal",
            "server_version": "3.18.2",
            "agent_version": "3.18.2",
            "agent_backend": "kubernetes",
            "protected_refs": [f"refs/tags/deploy/{env_id}/**"],
            "approval_policy": {
                "required": env_class == "prod",
                "approvers": ["release-manager"] if env_class == "prod" else [],
                "window": "PT2H" if env_class == "prod" else "not-required",
            },
            "secret_resolution_mode": "secret-extension",
            "secrets": [_secret(env_id, name, purpose) for name, purpose in required],
        },
        "registry": {
            "repository": f"registry.example/deeptutor/{env_id}",
            "credentials_ref": f"woodpecker:DT_{env_id.upper().replace('-', '_')}_REGISTRY_PUSH_TOKEN",
            "immutable_tags": True,
        },
        "kubernetes": {
            "cluster_ref": f"k8s:{env_id}",
            "namespace": f"deeptutor-{env_id}",
            "ingress_host": f"deeptutor-{env_id}.example.internal",
            "tls_secret_ref": f"k8s:{env_id}/deeptutor-tls",
            "secret_store_ref": f"external-secret:{env_id}/platform",
            "rbac_ref": f"k8s:{env_id}/rbac/deeptutor-release",
            "network_policy_ref": f"k8s:{env_id}/networkpolicy/default-deny",
            "service_account": "deeptutor-release",
            "backend_executor_replicas": backend_executor_replicas,
            "rollout_strategy": rollout_strategy,
            "runtime_coordination": runtime_coordination
            if runtime_coordination is not None
            else _runtime_coordination(env_id),
            "autoscaling": autoscaling if autoscaling is not None else _autoscaling(),
        },
        "data_plane": {
            "pg_secret_ref": f"external-secret:{env_id}/pg-runtime",
            "object_store_ref": f"external-secret:{env_id}/objectstore",
            "lightrag_ref": f"external-secret:{env_id}/lightrag",
            "eduplus2_smoke_ref": f"external-secret:{env_id}/eduplus2-smoke",
        },
        "release_control": {
            "release_lock_ref": f"postgres:{env_id}/release_locks",
            "migration_lock_ref": f"postgres:{env_id}/migration_locks",
            "maintenance_mode_ref": f"postgres:{env_id}/maintenance_state",
        },
        "rollback_policy": {
            "compatible_strategy": "previous-digest-if-compatible",
            "incompatible_strategy": "maintenance-forward-fix",
            "previous_release_ref": f"object-store:release-evidence/{env_id}/latest-successful",
            "requires_smoke_after_rollback": True,
        },
        "evidence": {
            "store_ref": "object-store:deeptutor-release-evidence",
            "prefix": f"release-evidence/{env_id}",
            "retention_days": 365,
            "write_scope": f"release-evidence/{env_id}/*",
            "read_scope": f"release-evidence/{env_id}/*",
        },
    }


def _registry() -> dict:
    return {
        "registry_version": "2026-09-protected-k8s-release",
        "canonical_tag_regex": r"^deploy/(?P<env_id>[a-z][a-z0-9-]{1,40})/(?P<version>v[0-9]+\.[0-9]+\.[0-9]+(-(rc|hotfix)\.[0-9]+)?)$",
        "environments": [
            _environment("test-cn", "test"),
            _environment("pre-cn", "pre"),
            _environment("prod-cn-east", "prod", prod_group="cn"),
            _environment("prod-overseas-a", "prod", prod_group="overseas"),
        ],
    }


def _available_from_registry(registry, env_id: str) -> dict[str, dict]:
    env = next(item for item in registry.environments if item.env_id == env_id)
    return {
        secret.logical_name: {
            "present": True,
            "scope_env_id": secret.scope_env_id,
            "least_privilege": True,
            "rotation_state": "current",
            "permission_summary": secret.permission_summary,
        }
        for secret in env.woodpecker.secrets
    }


def _read_shell_exports(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf8").splitlines():
        if not line.startswith("export "):
            continue
        key, _, raw_value = line.removeprefix("export ").partition("=")
        values[key] = raw_value.strip().strip("'")
    return values


def test_environment_registry_parses_deployment_tag_and_keeps_production_envs_isolated():
    from deeptutor_enterprise.protected_k8s_release import EnvironmentRegistry, parse_deployment_tag

    registry = EnvironmentRegistry.model_validate(_registry())
    assert registry.production_env_ids == ("prod-cn-east", "prod-overseas-a")

    parsed = parse_deployment_tag("deploy/prod-cn-east/v1.4.0-hotfix.1")
    assert parsed.env_id == "prod-cn-east"
    assert parsed.version == "v1.4.0-hotfix.1"

    summary = registry.redacted_matrix()
    rendered = json.dumps(summary, ensure_ascii=False)
    assert summary["production_env_ids"] == ["prod-cn-east", "prod-overseas-a"]
    assert summary["environments"]["prod-cn-east"]["evidence_prefix"].endswith("prod-cn-east")
    assert summary["environments"]["prod-overseas-a"]["evidence_prefix"].endswith(
        "prod-overseas-a"
    )
    assert "woodpecker-prod-cn-east.example.internal" not in rendered
    assert "host_hash" in rendered

    with pytest.raises(ValueError, match="deployment_tag_invalid"):
        parse_deployment_tag("prod-cn-east/v1.4.0")
    assert registry.find_env("prod-cn-east").env_id == "prod-cn-east"
    assert registry.find_env("prod") is None


def test_release_trigger_fails_closed_for_untrusted_tags_and_manual_env_override():
    from deeptutor_enterprise.protected_k8s_release import (
        EnvironmentRegistry,
        validate_release_trigger,
    )

    registry = EnvironmentRegistry.model_validate(_registry())

    ok = validate_release_trigger(
        registry,
        event="tag",
        ref="refs/tags/deploy/prod-cn-east/v1.4.0",
        tag="deploy/prod-cn-east/v1.4.0",
        protected_ref=True,
        approved=True,
        approval_id="approval-123",
        actor="release-manager",
        tag_object_sha=_TAG_SHA,
        commit_sha=_SHA_A,
    )
    assert ok["ready"] is True
    assert ok["target_env_id"] == "prod-cn-east"
    assert ok["version"] == "v1.4.0"

    cases = [
        {"event": "pull_request", "tag": "deploy/prod-cn-east/v1.4.0", "code": "event_not_tag"},
        {"event": "tag", "tag": "not-a-deploy-tag", "code": "deployment_tag_invalid"},
        {"event": "tag", "tag": "deploy/prod/v1.4.0", "code": "environment_not_registered"},
        {"event": "tag", "tag": "deploy/missing-env/v1.4.0", "code": "environment_not_registered"},
    ]
    for case in cases:
        result = validate_release_trigger(
            registry,
            event=case["event"],
            ref="refs/tags/" + case["tag"],
            tag=case["tag"],
            protected_ref=True,
            approved=True,
            approval_id="approval-123",
            actor="release-manager",
            tag_object_sha=_TAG_SHA,
            commit_sha=_SHA_A,
        )
        assert result["ready"] is False
        assert case["code"] in result["error_codes"]

    unprotected = validate_release_trigger(
        registry,
        event="tag",
        ref="refs/tags/deploy/prod-cn-east/v1.4.0",
        tag="deploy/prod-cn-east/v1.4.0",
        protected_ref=False,
        approved=True,
        approval_id="approval-123",
        actor="release-manager",
        tag_object_sha=_TAG_SHA,
        commit_sha=_SHA_A,
    )
    assert unprotected["ready"] is False
    assert "tag_not_protected" in unprotected["error_codes"]

    unapproved = validate_release_trigger(
        registry,
        event="tag",
        ref="refs/tags/deploy/prod-cn-east/v1.4.0",
        tag="deploy/prod-cn-east/v1.4.0",
        protected_ref=True,
        approved=False,
        approval_id="",
        actor="developer",
        tag_object_sha=_TAG_SHA,
        commit_sha=_SHA_A,
    )
    assert unapproved["ready"] is False
    assert "prod_approval_missing" in unapproved["error_codes"]

    override = validate_release_trigger(
        registry,
        event="tag",
        ref="refs/tags/deploy/prod-cn-east/v1.4.0",
        tag="deploy/prod-cn-east/v1.4.0",
        protected_ref=True,
        approved=True,
        approval_id="approval-123",
        actor="release-manager",
        tag_object_sha=_TAG_SHA,
        commit_sha=_SHA_A,
        manual_target_env_id="prod-overseas-a",
    )
    assert override["ready"] is False
    assert "manual_environment_override_forbidden" in override["error_codes"]

    moved = validate_release_trigger(
        registry,
        event="tag",
        ref="refs/tags/deploy/prod-cn-east/v1.4.0",
        tag="deploy/prod-cn-east/v1.4.0",
        protected_ref=True,
        approved=True,
        approval_id="approval-123",
        actor="release-manager",
        tag_object_sha=_TAG_SHA,
        commit_sha=_SHA_B,
        previous_evidence={
            "target_env_id": "prod-cn-east",
            "version": "v1.4.0",
            "tag_object_sha": _TAG_SHA,
            "commit_sha": _SHA_A,
        },
    )
    assert moved["ready"] is False
    assert "deployment_tag_reused_or_moved" in moved["error_codes"]


def test_secret_preflight_requires_environment_scoped_least_privilege_refs():
    from deeptutor_enterprise.protected_k8s_release import EnvironmentRegistry, secret_preflight

    registry = EnvironmentRegistry.model_validate(_registry())
    available = _available_from_registry(registry, "prod-cn-east")
    report = secret_preflight(registry, "prod-cn-east", available)
    assert report["ready"] is True
    assert report["target_env_id"] == "prod-cn-east"
    assert "DT_PROD_CN_EAST_REGISTRY_PUSH_TOKEN" not in json.dumps(report, ensure_ascii=False)

    missing = dict(available)
    missing.pop("REGISTRY_PUSH_TOKEN")
    report = secret_preflight(registry, "prod-cn-east", missing)
    assert report["ready"] is False
    assert "secret_missing:REGISTRY_PUSH_TOKEN" in report["error_codes"]

    cross_env = dict(available)
    cross_env["KUBE_DEPLOY_TOKEN"] = {**cross_env["KUBE_DEPLOY_TOKEN"], "scope_env_id": "test-cn"}
    report = secret_preflight(registry, "prod-cn-east", cross_env)
    assert report["ready"] is False
    assert "secret_scope_mismatch:KUBE_DEPLOY_TOKEN" in report["error_codes"]

    overpowered = dict(available)
    overpowered["PG_MIGRATOR_DSN"] = {
        **overpowered["PG_MIGRATOR_DSN"],
        "least_privilege": False,
        "permission_summary": "db:superuser:*",
    }
    report = secret_preflight(registry, "prod-cn-east", overpowered)
    assert report["ready"] is False
    assert "secret_over_privileged:PG_MIGRATOR_DSN" in report["error_codes"]


def test_release_manifest_requires_digests_single_executor_and_environment_paths():
    from deeptutor_enterprise.protected_k8s_release import (
        EnvironmentRegistry,
        build_release_manifest,
    )

    registry = EnvironmentRegistry.model_validate(_registry())
    manifest = build_release_manifest(
        registry,
        target_env_id="prod-cn-east",
        version="v1.4.0",
        tag="deploy/prod-cn-east/v1.4.0",
        tag_object_sha=_TAG_SHA,
        tag_creator="release-manager",
        source_sha=_SHA_A,
        upstream_sha=_SHA_B,
        enterprise_package_version="0.1.0",
        backend_image_digest="registry.example/deeptutor/prod-cn-east/backend@sha256:" + "1" * 64,
        frontend_image_digest="registry.example/deeptutor/prod-cn-east/frontend@sha256:" + "2" * 64,
        build_run_id="woodpecker-100",
        scan_summary={"sbom": "generated", "vulnerabilities": "not-run"},
    )
    assert manifest["target_env_id"] == "prod-cn-east"
    assert manifest["images"]["backend"].endswith("@sha256:" + "1" * 64)
    assert manifest["kubernetes"]["backend_executor_replicas"] == 1
    assert manifest["evidence_prefix"].endswith("prod-cn-east/v1.4.0")

    with pytest.raises(ValueError, match="image_digest_required"):
        build_release_manifest(
            registry,
            target_env_id="prod-cn-east",
            version="v1.4.0",
            tag="deploy/prod-cn-east/v1.4.0",
            tag_object_sha=_TAG_SHA,
            tag_creator="release-manager",
            source_sha=_SHA_A,
            upstream_sha=_SHA_B,
            enterprise_package_version="0.1.0",
            backend_image_digest="registry.example/deeptutor/prod-cn-east/backend:latest",
            frontend_image_digest="registry.example/deeptutor/prod-cn-east/frontend@sha256:" + "2" * 64,
            build_run_id="woodpecker-100",
            scan_summary={},
        )


def test_replicated_backend_contract_requires_redis_coordination_and_records_autoscaling():
    from deeptutor_enterprise.protected_k8s_release import (
        EnvironmentRegistry,
        build_release_manifest,
    )

    registry_payload = _registry()
    registry_payload["environments"][0] = _environment(
        "test-cn",
        "test",
        backend_executor_replicas=3,
        rollout_strategy="rolling-replicated-agent",
        runtime_coordination=_runtime_coordination("test-cn", "redis"),
        autoscaling=_autoscaling(
            enabled=True,
            min_replicas=3,
            max_replicas=12,
            target_cpu_utilization_percentage=70,
        ),
    )
    registry = EnvironmentRegistry.model_validate(registry_payload)
    env = registry.find_env("test-cn")
    assert env is not None
    assert env.kubernetes.backend_executor_replicas == 3
    assert env.kubernetes.runtime_coordination.backend == "redis"
    assert env.kubernetes.autoscaling.enabled is True

    manifest = build_release_manifest(
        registry,
        target_env_id="test-cn",
        version="v1.4.0",
        tag="deploy/test-cn/v1.4.0",
        tag_object_sha=_TAG_SHA,
        tag_creator="release-manager",
        source_sha=_SHA_A,
        upstream_sha=_SHA_B,
        enterprise_package_version="0.1.0",
        backend_image_digest="registry.example/deeptutor/test-cn/backend@sha256:" + "1" * 64,
        frontend_image_digest="registry.example/deeptutor/test-cn/frontend@sha256:" + "2" * 64,
        build_run_id="woodpecker-100",
        scan_summary={},
    )
    assert manifest["kubernetes"]["backend_executor_replicas"] == 3
    assert manifest["kubernetes"]["runtime_coordination"]["backend"] == "redis"
    assert manifest["kubernetes"]["autoscaling"]["max_replicas"] == 12

    unsafe = _registry()
    unsafe["environments"][0] = _environment(
        "test-cn",
        "test",
        backend_executor_replicas=3,
        rollout_strategy="rolling-replicated-agent",
        runtime_coordination=_runtime_coordination("test-cn", "memory"),
    )
    with pytest.raises(Exception, match="multi_replica_requires_redis_coordination"):
        EnvironmentRegistry.model_validate(unsafe)


def test_rollback_decision_and_release_evidence_are_partitioned_and_leak_scanned(tmp_path):
    from deeptutor_enterprise.protected_k8s_release import (
        EnvironmentRegistry,
        build_release_manifest,
        decide_rollback,
        scan_secret_leakage,
        write_release_evidence,
    )

    registry = EnvironmentRegistry.model_validate(_registry())
    manifest = build_release_manifest(
        registry,
        target_env_id="prod-overseas-a",
        version="v1.4.0-hotfix.1",
        tag="deploy/prod-overseas-a/v1.4.0-hotfix.1",
        tag_object_sha=_TAG_SHA,
        tag_creator="release-manager",
        source_sha=_SHA_A,
        upstream_sha=_SHA_B,
        enterprise_package_version="0.1.0",
        backend_image_digest="registry.example/deeptutor/prod-overseas-a/backend@sha256:" + "3" * 64,
        frontend_image_digest="registry.example/deeptutor/prod-overseas-a/frontend@sha256:" + "4" * 64,
        build_run_id="woodpecker-101",
        scan_summary={"sbom": "generated", "vulnerabilities": "not-run"},
    )
    rollback = decide_rollback(
        registry,
        "prod-overseas-a",
        failure_code="smoke_failed",
        previous_release_compatible=True,
        previous_digest="registry.example/deeptutor/prod-overseas-a/backend@sha256:" + "5" * 64,
        approval_id="rollback-approval-1",
    )
    assert rollback["action"] == "rollback_previous_digest"
    assert rollback["requires_smoke_after_rollback"] is True

    blocked = decide_rollback(
        registry,
        "prod-overseas-a",
        failure_code="schema_incompatible",
        previous_release_compatible=False,
        previous_digest=None,
        approval_id="rollback-approval-2",
    )
    assert blocked["action"] == "maintenance_forward_fix"
    assert blocked["write_state"] == "stopped"

    output = write_release_evidence(
        tmp_path,
        registry,
        manifest,
        deployment_contract=registry.find_env("prod-overseas-a").redacted_summary(),
        migration={"exit_code": 0, "schema_version": "20260924_protected_k8s_release", "release_id": "rel-1"},
        deploy={"exit_code": 0, "rollout": "not-run", "release_lock": "held"},
        smoke={"run_id": "smoke-1", "exit_code": 1, "request_id_hash": "abc123"},
        rollback=rollback,
        upstream_compat={"core_patches": [], "review": "extension-only"},
        unresolved=["real_k8s_not_authorized", "lightrag_sample_not_run"],
    )
    assert output.relative_to(tmp_path).parts[:2] == ("prod-overseas-a", "v1.4.0-hotfix.1")
    assert (output / "deployment-contract.json").exists()
    assert (output / "unresolved.md").read_text(encoding="utf8").count("real_k8s_not_authorized") == 1
    clean = scan_secret_leakage(output)
    assert clean["ready"] is True

    (output / "bad.log").write_text("leaked dt_token=dt_abc client_secret=secret", encoding="utf8")
    leaked = scan_secret_leakage(output)
    assert leaked["ready"] is False
    assert "secret_leak_detected" in leaked["error_codes"]


def test_protected_k8s_release_cli_writes_redacted_matrix_preflight_and_evidence(tmp_path, capsys):
    from deeptutor_enterprise.protected_k8s_release_cli import main

    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(_registry(), ensure_ascii=False), encoding="utf8")
    matrix_dir = tmp_path / "matrix"
    assert main(["matrix", "--registry", str(registry_path), "--output", str(matrix_dir)]) == 0
    captured = json.loads(capsys.readouterr().out)
    matrix_path = Path(captured["matrix"])
    matrix_text = matrix_path.read_text(encoding="utf8")
    assert "prod-cn-east" in matrix_text
    assert "woodpecker-prod-cn-east.example.internal" not in matrix_text

    available = _available_from_registry(
        __import__("deeptutor_enterprise.protected_k8s_release", fromlist=["EnvironmentRegistry"]).EnvironmentRegistry.model_validate(
            _registry()
        ),
        "prod-cn-east",
    )
    available_path = tmp_path / "available.json"
    available_path.write_text(json.dumps(available, ensure_ascii=False), encoding="utf8")
    preflight_dir = tmp_path / "preflight"
    assert (
        main(
            [
                "preflight",
                "--registry",
                str(registry_path),
                "--target-env-id",
                "prod-cn-east",
                "--available-secrets",
                str(available_path),
                "--output",
                str(preflight_dir),
            ]
        )
        == 0
    )
    captured = json.loads(capsys.readouterr().out)
    preflight = json.loads(Path(captured["secret_preflight"]).read_text(encoding="utf8"))
    assert preflight["ready"] is True
    assert preflight["target_env_id"] == "prod-cn-east"


def test_protected_k8s_release_cli_prepares_sourceable_release_metadata(tmp_path, capsys):
    from deeptutor_enterprise.protected_k8s_release_cli import main

    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(_registry(), ensure_ascii=False), encoding="utf8")
    trusted_metadata_path = tmp_path / "trusted-trigger-metadata.json"
    trusted_metadata_path.write_text(
        json.dumps(
            {
                "protected_ref": True,
                "approved": True,
                "approval_id": "approval-123",
                "actor": "release-manager",
                "tag_object_sha": _TAG_SHA,
                "commit_sha": _SHA_A,
                "trust_source": "vcs-protected-tag-api",
            },
            ensure_ascii=False,
        ),
        encoding="utf8",
    )
    output_env = tmp_path / ".deeptutor-release.env"
    output_dir = tmp_path / "metadata"

    assert (
        main(
            [
                "prepare-metadata",
                "--registry",
                str(registry_path),
                "--event",
                "tag",
                "--ref",
                "refs/tags/deploy/prod-cn-east/v1.4.0",
                "--tag",
                "deploy/prod-cn-east/v1.4.0",
                "--trusted-metadata",
                str(trusted_metadata_path),
                "--output-env-file",
                str(output_env),
                "--output",
                str(output_dir),
            ]
        )
        == 0
    )
    captured = json.loads(capsys.readouterr().out)
    gate_payload = json.loads(Path(captured["trigger_gate"]).read_text(encoding="utf8"))
    assert gate_payload["ready"] is True

    env = _read_shell_exports(output_env)
    assert env["DEEPTUTOR_TARGET_ENV_ID"] == "prod-cn-east"
    assert env["DEEPTUTOR_RELEASE_VERSION"] == "v1.4.0"
    assert env["DEEPTUTOR_RELEASE_TAG"] == "deploy/prod-cn-east/v1.4.0"
    assert env["DEEPTUTOR_IMAGE_TAG"] == "deploy-prod-cn-east-v1.4.0"
    assert env["DEEPTUTOR_RELEASE_ID"] == "prod-cn-east-v1-4-0"
    assert "." not in env["DEEPTUTOR_RELEASE_ID"]
    assert len(env["DEEPTUTOR_RELEASE_ID"]) <= 52
    assert env["DEEPTUTOR_REGISTRY_REPOSITORY"] == "registry.example/deeptutor/prod-cn-east"
    assert env["DEEPTUTOR_EVIDENCE_DIR"] == "release-evidence/prod-cn-east/v1.4.0"
    assert env["DEEPTUTOR_BACKEND_EXECUTOR_REPLICAS"] == "1"
    assert env["DEEPTUTOR_EXECUTION_MODE"] == "single"
    assert env["DEEPTUTOR_TURN_COORDINATION_BACKEND"] == "memory"
    assert env["DEEPTUTOR_HPA_ENABLED"] == "false"
    assert "TOKEN" not in output_env.read_text(encoding="utf8")


def test_protected_k8s_release_cli_runs_gate_without_pydantic_dependency(tmp_path):
    import os
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[2].parent
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(_registry(), ensure_ascii=False), encoding="utf8")
    metadata_path = tmp_path / "trusted-trigger-metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "protected_ref": True,
                "approved": True,
                "approval_id": "approval-123",
                "actor": "release-manager",
                "tag_object_sha": _TAG_SHA,
                "commit_sha": _SHA_A,
                "trust_source": "vcs-protected-tag-api",
            },
            ensure_ascii=False,
        ),
        encoding="utf8",
    )
    (tmp_path / "sitecustomize.py").write_text(
        """
import builtins
_real_import = builtins.__import__
def _blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == 'pydantic' or name.startswith('pydantic.'):
        raise ModuleNotFoundError("No module named 'pydantic'", name='pydantic')
    return _real_import(name, globals, locals, fromlist, level)
builtins.__import__ = _blocked_import
""".lstrip(),
        encoding="utf8",
    )
    output_dir = tmp_path / "metadata"
    output_env = tmp_path / ".deeptutor-release.env"
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(tmp_path), str(root / "extensions/enterprise/src")]
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "deeptutor_enterprise.protected_k8s_release_cli",
            "prepare-metadata",
            "--registry",
            str(registry_path),
            "--event",
            "tag",
            "--ref",
            "refs/tags/deploy/test-cn/v1.4.0-rc.8",
            "--tag",
            "deploy/test-cn/v1.4.0-rc.8",
            "--trusted-metadata",
            str(metadata_path),
            "--output-env-file",
            str(output_env),
            "--output",
            str(output_dir),
        ],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    captured = json.loads(result.stdout)
    payload = json.loads(Path(captured["trigger_gate"]).read_text(encoding="utf8"))
    env_values = _read_shell_exports(Path(captured["release_env"]))
    assert payload["ready"] is True
    assert payload["target_env_id"] == "test-cn"
    assert env_values["DEEPTUTOR_TARGET_ENV_ID"] == "test-cn"
    assert env_values["DEEPTUTOR_RELEASE_VERSION"] == "v1.4.0-rc.8"


def test_protected_k8s_example_registry_pipeline_and_k8s_sources_are_contract_driven():
    from deeptutor_enterprise.protected_k8s_release import EnvironmentRegistry

    root = Path(__file__).resolve().parents[2].parent
    registry_path = root / "extensions/enterprise/protected-k8s-release-environments.example.json"
    pipeline_path = root / ".woodpecker/protected-k8s-release.yml"
    k8s_dir = root / "deploy/kubernetes/protected-k8s-release"
    evidence_template = root / "docs/enterprise/protected-k8s-release-evidence-template.md"
    k8s_readme = k8s_dir / "README.md"
    dockerignore_path = root / ".dockerignore"

    registry_text = registry_path.read_text(encoding="utf8")
    assert "registry.example" not in registry_text
    assert "docker-hub.f123.pub/lfun/deeptutor/test-cn" in registry_text
    registry_payload = json.loads(registry_text)
    registry = EnvironmentRegistry.model_validate(registry_payload)
    assert registry.production_env_ids == ("prod-cn-east", "prod-overseas-a")

    pipeline = pipeline_path.read_text(encoding="utf8")
    assert "CI_COMMIT_TAG" in pipeline
    assert "python -m deeptutor_enterprise.protected_k8s_release_cli trigger" in pipeline
    assert "python -m deeptutor_enterprise.protected_k8s_release_cli prepare-metadata" in pipeline
    assert "g1_release" not in pipeline
    assert "g1-release" not in pipeline.lower()
    assert "add-m1" not in pipeline.lower()
    assert "NON-RUNNABLE SKELETON" not in pipeline
    assert "workspace:" in pipeline
    assert "docker-hub.f123.pub/woodpeckerci/plugin-git:2.8.1" in pipeline
    assert "docker-hub.f123.pub/devops/kaniko:v1.14.0-debug" in pipeline
    assert "docker-hub.f123.pub/base/ci-tools:alpine-3.22.4" in pipeline
    assert "pydantic>=2,<3" not in pipeline
    assert "pip install" not in pipeline
    assert "variables:" not in pipeline
    assert "--registry $REGISTRY_FILE" not in pipeline
    assert "extensions/enterprise/protected-k8s-release-environments.example.json" in pipeline
    assert "base64.b64encode" not in pipeline
    assert '"username":"%s","password":"%s"' in pipeline
    assert "unset SOCKS_PROXY socks_proxy ALL_PROXY all_proxy HTTPS_PROXY https_proxy HTTP_PROXY http_proxy" in pipeline
    assert ". ./.deeptutor-release.env" in pipeline
    assert "from_secret: DOCKER_USERNAME" in pipeline
    assert "from_secret: DOCKER_PASSWORD" in pipeline
    assert "from_secret: kubeconfig_test" in pipeline
    assert "from_secret: kubeconfig_test" in pipeline
    assert "from_secret: dt_test_cn_registry_push_token" not in pipeline
    assert "from_secret: dt_test_cn_registry_push_username" not in pipeline
    assert "from_secret: dt_test_cn_kubeconfig" not in pipeline
    assert "from_secret: dt_test_cn_kube_deploy_token" not in pipeline
    assert "from_secret: dt_prod_cn_east_kube_deploy_token" in pipeline
    assert "DT_${ENV_KEY}" not in pipeline
    assert "--approved" not in pipeline
    assert "--protected-ref" not in pipeline
    assert "trusted metadata" in pipeline.lower()
    assert "$${TRUSTED_TRIGGER_METADATA_JSON:-}" in pipeline
    assert "$${PROTECTED_K8S_RELEASE_TRUSTED_METADATA_FILE:-}" in pipeline
    assert 'test -n "${TRUSTED_TRIGGER_METADATA_JSON:-}"' not in pipeline
    assert "deploy/prod/**" not in pipeline
    assert "event: tag" in pipeline
    for env_id in ("test-cn", "pre-cn", "prod-cn-east", "prod-overseas-a"):
        suffix = env_id.replace("-", "_").upper()
        assert f"build-runtime-image-{env_id}" in pipeline
        assert f"pre-deploy-check-{env_id}" in pipeline
        assert f"secret-preflight-{env_id}" in pipeline
        assert f"deploy-{env_id}" in pipeline
        if env_id == "test-cn":
            assert "from_secret: DOCKER_PASSWORD" in pipeline
            assert "from_secret: kubeconfig_test" in pipeline
        else:
            assert f"from_secret: dt_{suffix.lower()}_registry_push_token" in pipeline
            assert f"from_secret: dt_{suffix.lower()}_kube_deploy_token" in pipeline

    backend = (k8s_dir / "backend.yaml").read_text(encoding="utf8")
    migration = (k8s_dir / "migration-job.yaml").read_text(encoding="utf8")
    network = (k8s_dir / "networkpolicy.yaml").read_text(encoding="utf8")
    deploy_script = (k8s_dir / "deploy.sh").read_text(encoding="utf8")
    status_script = (k8s_dir / "status.sh").read_text(encoding="utf8")
    readme = k8s_readme.read_text(encoding="utf8")
    assert 'image: "${DEEPTUTOR_RUNTIME_IMAGE_DIGEST}"' in backend
    assert "replicas: ${DEEPTUTOR_BACKEND_EXECUTOR_REPLICAS}" in backend
    assert "type: Recreate" in backend
    assert ":latest" not in backend
    assert "release-lock" in migration
    assert "schema_history" in migration
    assert " bootstrap " in migration
    assert "--password-env DEEPTUTOR_BOOTSTRAP_ADMIN_PASSWORD" in migration
    assert "NetworkPolicy" in network
    hpa = (k8s_dir / "patches/autoscaling/hpa.yaml").read_text(encoding="utf8")
    assert "HorizontalPodAutoscaler" in hpa
    assert "pre-provisioned by the target environment contract" in readme
    assert "deeptutor-runtime-secrets" in readme
    assert "deeptutor-deployment-config" in readme
    assert 'DEEPTUTOR_DEPLOY_APPROVED:-' in deploy_script
    assert "kubectl -n" in deploy_script
    assert 'render_manifest "${manifest_dir}/networkpolicy.yaml"' in deploy_script
    assert "rollout status" in deploy_script
    assert "DEEPTUTOR_TURN_COORDINATION_BACKEND" in deploy_script
    assert "logs \"job/${migration_job_name}\"" in deploy_script
    assert "get deployment" in status_script

    template = evidence_template.read_text(encoding="utf8")
    active_artifacts = {
        "pipeline": pipeline_path,
        "registry": registry_path,
        "k8s_dir": k8s_dir,
        "evidence_template": evidence_template,
    }
    for label, artifact_path in active_artifacts.items():
        assert "g1" not in str(artifact_path).lower(), label
        assert "m1" not in str(artifact_path).lower(), label
    for label, artifact_text in {
        "pipeline": pipeline,
        "backend": backend,
        "migration": migration,
        "network": network,
        "deploy_script": deploy_script,
        "status_script": status_script,
        "readme": readme,
        "evidence_template": template,
    }.items():
        lowered = artifact_text.lower()
        assert "g1" not in lowered, label
        assert "m1" not in lowered, label
    assert "target_env_id" in template
    assert "release-evidence/<target-env-id>/<version>/" in template
    assert "不得包含 JWT、dt_token、client secret" in template

    dockerignore = dockerignore_path.read_text(encoding="utf8")
    for required in (".secrets/", ".codegraph/", ".superpowers/", ".worktrees/", "**/.env", "**/.env.*"):
        assert required in dockerignore


def test_protected_k8s_yaml_sources_parse_before_and_after_release_substitution():
    import string

    import yaml

    root = Path(__file__).resolve().parents[2].parent
    k8s_dir = root / "deploy/kubernetes/protected-k8s-release"
    release_values = {
        "DEEPTUTOR_RUNTIME_IMAGE_DIGEST": "registry.example/deeptutor/test-cn/runtime@sha256:"
        + "1" * 64,
        "DEEPTUTOR_RELEASE_ID": "test-cn-v1-4-0",
        "DEEPTUTOR_TARGET_ENV_ID": "test-cn",
        "DEEPTUTOR_INGRESS_HOST": "deeptutor-test-cn.example.internal",
        "DEEPTUTOR_TLS_SECRET_NAME": "deeptutor-test-cn-tls",
        "DEEPTUTOR_RELEASE_LOCK_REF": "postgres:test-cn/release_locks",
        "DEEPTUTOR_MIGRATION_LOCK_REF": "postgres:test-cn/migration_locks",
        "DEEPTUTOR_BACKEND_EXECUTOR_REPLICAS": "3",
        "DEEPTUTOR_EXECUTION_MODE": "replicated",
        "DEEPTUTOR_TURN_COORDINATION_BACKEND": "redis",
        "DEEPTUTOR_REDIS_KEY_PREFIX": "deeptutor-test-cn",
        "DEEPTUTOR_HPA_MIN_REPLICAS": "3",
        "DEEPTUTOR_HPA_MAX_REPLICAS": "12",
        "DEEPTUTOR_HPA_TARGET_CPU_UTILIZATION_PERCENTAGE": "70",
    }

    for manifest_name in (
        "backend.yaml",
        "migration-job.yaml",
        "networkpolicy.yaml",
        "patches/autoscaling/hpa.yaml",
    ):
        source = (k8s_dir / manifest_name).read_text(encoding="utf8")
        source_docs = [doc for doc in yaml.safe_load_all(source) if doc]
        rendered = string.Template(source).safe_substitute(release_values)
        rendered_docs = [doc for doc in yaml.safe_load_all(rendered) if doc]
        assert [doc["kind"] for doc in source_docs] == [doc["kind"] for doc in rendered_docs]
        for doc in rendered_docs:
            assert doc["metadata"]["name"]
            if doc["kind"] == "Deployment":
                assert doc["spec"]["replicas"] == 3
                env = {
                    item["name"]: item.get("value", "")
                    for item in doc["spec"]["template"]["spec"]["containers"][0]["env"]
                }
                assert env["DEEPTUTOR_EXECUTION_MODE"] == "replicated"
                assert env["DEEPTUTOR_TURN_COORDINATION_BACKEND"] == "redis"
            if doc["kind"] == "HorizontalPodAutoscaler":
                assert doc["spec"]["minReplicas"] == 3
                assert doc["spec"]["maxReplicas"] == 12

    prod_hotfix_values = {
        **release_values,
        "DEEPTUTOR_RELEASE_ID": "prod-overseas-a-v1-4-0-hotfix-1",
        "DEEPTUTOR_TARGET_ENV_ID": "prod-overseas-a",
    }
    prod_migration = string.Template((k8s_dir / "migration-job.yaml").read_text(encoding="utf8")).safe_substitute(
        prod_hotfix_values
    )
    prod_job = next(doc for doc in yaml.safe_load_all(prod_migration) if doc)
    assert prod_job["kind"] == "Job"
    assert len(prod_job["metadata"]["name"]) <= 63


def test_protected_k8s_deploy_script_fails_closed_before_kubectl_without_approval():
    import os
    import subprocess

    root = Path(__file__).resolve().parents[2].parent
    script = root / "deploy/kubernetes/protected-k8s-release/deploy.sh"
    env = os.environ.copy()
    env.update(
        {
            "DEEPTUTOR_TARGET_ENV_ID": "prod-cn-east",
            "DEEPTUTOR_RELEASE_ID": "prod-cn-east-v1.4.0",
            "DEEPTUTOR_RUNTIME_IMAGE_DIGEST": "registry.example/deeptutor/prod-cn-east/runtime@sha256:"
            + "1" * 64,
            "DEEPTUTOR_K8S_NAMESPACE": "deeptutor-prod-cn-east",
            "KUBECONFIG_DATA": "apiVersion: v1\nclusters: []\ncontexts: []\n",
        }
    )
    result = subprocess.run(
        ["bash", str(script)],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1
    assert "DEEPTUTOR_DEPLOY_APPROVED=yes is required" in result.stderr
    assert "kubectl" not in result.stderr


def test_protected_k8s_deploy_script_rejects_replicas_without_redis_before_kubectl():
    import os
    import subprocess

    root = Path(__file__).resolve().parents[2].parent
    script = root / "deploy/kubernetes/protected-k8s-release/deploy.sh"
    env = os.environ.copy()
    env.update(
        {
            "DEEPTUTOR_DEPLOY_APPROVED": "yes",
            "DEEPTUTOR_TARGET_ENV_ID": "test-cn",
            "DEEPTUTOR_RELEASE_ID": "test-cn-v1.4.0",
            "DEEPTUTOR_RUNTIME_IMAGE_DIGEST": "registry.example/deeptutor/test-cn/runtime@sha256:"
            + "1" * 64,
            "DEEPTUTOR_K8S_NAMESPACE": "deeptutor-test-cn",
            "DEEPTUTOR_INGRESS_HOST": "deeptutor-test-cn.example.internal",
            "DEEPTUTOR_TLS_SECRET_NAME": "deeptutor-test-cn-tls",
            "DEEPTUTOR_RELEASE_LOCK_REF": "postgres:test-cn/release_locks",
            "DEEPTUTOR_MIGRATION_LOCK_REF": "postgres:test-cn/migration_locks",
            "DEEPTUTOR_BACKEND_EXECUTOR_REPLICAS": "3",
            "DEEPTUTOR_EXECUTION_MODE": "replicated",
            "DEEPTUTOR_TURN_COORDINATION_BACKEND": "memory",
            "KUBECONFIG_DATA": "apiVersion: v1\nclusters: []\ncontexts: []\n",
        }
    )
    result = subprocess.run(
        ["bash", str(script)],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1
    assert "backend replicas > 1 requires DEEPTUTOR_TURN_COORDINATION_BACKEND=redis" in (
        result.stderr
    )
    assert "kubectl" not in result.stderr


def test_prepare_test_woodpecker_secrets_prefers_existing_global_kubectl_and_registry(
    tmp_path,
):
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[2].parent
    input_path = tmp_path / ".test-secrets"
    output_path = tmp_path / "test.secrets"
    input_path.write_text(
        """
# Docker Registry
- URL = registry.example
- Username = local-registry-user
- Password = local-registry-password

# PostgreSQL
- IP = 10.0.0.12
- 端口 = 5432
- 用户 = dt_user
- 数据库 = deeptutor_test
- 密码 = dt_password

# S3
DEEPTUTOR_OBJECT_STORE=s3
DEEPTUTOR_S3_ENDPOINT_URL=https://s3.example
DEEPTUTOR_S3_BUCKET=deeptutor-test
DEEPTUTOR_S3_REGION=auto
DEEPTUTOR_S3_ACCESS_KEY_ID=s3-ak
DEEPTUTOR_S3_SECRET_ACCESS_KEY=s3-sk

# LightRAG
URL=https://lightrag.example
APIKEY=lightrag-key

# DeepTutor EduPlus2 runtime env (canonical; generated from token-test.secrets)
DT_EDUPLUS2_CLIENT_SECRET_REF=external-secret:test-cn/eduplus2-existing
""".strip()
        + "\n",
        encoding="utf8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(root / "scripts/protected-k8s-release/prepare-test-woodpecker-secrets.py"),
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--commit-sha",
            _SHA_A,
            "--fixed-generated-token",
            "generated-test-token",
        ],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    rendered = output_path.read_text(encoding="utf8")
    assert "helm" not in rendered.lower()
    assert "DT_TEST_CN_REGISTRY_PUSH_USERNAME=" not in rendered
    assert "DT_TEST_CN_REGISTRY_PUSH_TOKEN=" not in rendered
    assert "DT_TEST_CN_KUBECONFIG=" not in rendered
    assert "DT_TEST_CN_KUBE_DEPLOY_TOKEN=" not in rendered
    assert "DOCKER_USERNAME" in rendered
    assert "DOCKER_PASSWORD" in rendered
    assert "kubeconfig_test" in rendered

    values = {}
    for line in rendered.splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip().strip("'")
    assert values["DT_TEST_CN_PG_MIGRATOR_DSN"] == (
        "postgresql://dt_user:dt_password@10.0.0.12:5432/deeptutor_test"
    )
    assert values["DT_TEST_CN_EDUPLUS2_CLIENT_SECRET_REF"] == (
        "external-secret:test-cn/eduplus2-existing"
    )
    assert values["DT_TEST_CN_SMOKE_TOKEN_ISSUER_SECRET"] == "generated-test-token"
    assert values["DT_TEST_CN_SECRET_PREFLIGHT_METADATA_JSON"]


def test_secret_preflight_status_script_outputs_only_metadata(monkeypatch, tmp_path):
    import os
    import subprocess
    import sys

    from deeptutor_enterprise.protected_k8s_release import EnvironmentRegistry, secret_preflight

    root = Path(__file__).resolve().parents[2].parent
    script = root / "scripts/protected-k8s-release/collect-secret-preflight-status.sh"
    monkeypatch.setenv("REGISTRY_PUSH_TOKEN", "registry-token-should-not-leak")
    monkeypatch.setenv("KUBE_DEPLOY_TOKEN", "kube-token-should-not-leak")
    monkeypatch.setenv("PYTHON", sys.executable)
    result = subprocess.run(
        ["bash", str(script), "prod-cn-east"],
        cwd=root,
        env=os.environ.copy(),
        check=True,
        text=True,
        capture_output=True,
    )
    assert "registry-token-should-not-leak" not in result.stdout
    assert "kube-token-should-not-leak" not in result.stdout
    payload = json.loads(result.stdout)
    assert payload["REGISTRY_PUSH_TOKEN"]["present"] is True
    assert payload["REGISTRY_PUSH_TOKEN"]["scope_env_id"] == ""
    assert payload["REGISTRY_PUSH_TOKEN"]["least_privilege"] is False
    assert payload["REGISTRY_PUSH_TOKEN"]["rotation_state"] == "unknown"
    assert payload["SECRETSTORE_ROLE"]["present"] is False

    registry = EnvironmentRegistry.model_validate(_registry())
    report = secret_preflight(registry, "prod-cn-east", payload)
    assert report["ready"] is False
    assert "secret_scope_mismatch:REGISTRY_PUSH_TOKEN" in report["error_codes"]
    assert "secret_over_privileged:REGISTRY_PUSH_TOKEN" in report["error_codes"]
    assert "secret_rotation_not_current:REGISTRY_PUSH_TOKEN" in report["error_codes"]

    monkeypatch.setenv(
        "SECRET_PREFLIGHT_METADATA_JSON",
        json.dumps(
            {
                "REGISTRY_PUSH_TOKEN": {
                    "scope_env_id": "prod-cn-east",
                    "least_privilege": "false",
                    "rotation_state": "current",
                    "permission_summary": "registry_push:prod-cn-east",
                    "secret_value": "must-not-be-copied",
                }
            },
            ensure_ascii=False,
        ),
    )
    result = subprocess.run(
        ["bash", str(script), "prod-cn-east"],
        cwd=root,
        env=os.environ.copy(),
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(result.stdout)
    assert "must-not-be-copied" not in result.stdout
    assert payload["REGISTRY_PUSH_TOKEN"]["scope_env_id"] == "prod-cn-east"
    assert payload["REGISTRY_PUSH_TOKEN"]["least_privilege"] is False

    monkeypatch.delenv("SECRET_PREFLIGHT_METADATA_JSON")
    monkeypatch.setenv("REGISTRY_PUSH_TOKEN_SCOPE_ENV_ID", "prod-cn-east")
    monkeypatch.setenv("REGISTRY_PUSH_TOKEN_LEAST_PRIVILEGE", "true")
    monkeypatch.setenv("REGISTRY_PUSH_TOKEN_ROTATION_STATE", "current")
    monkeypatch.setenv("REGISTRY_PUSH_TOKEN_PERMISSION_SUMMARY", "registry_push:prod-cn-east")
    result = subprocess.run(
        ["bash", str(script), "prod-cn-east"],
        cwd=root,
        env=os.environ.copy(),
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(result.stdout)
    assert payload["REGISTRY_PUSH_TOKEN"]["scope_env_id"] == "prod-cn-east"
    assert payload["REGISTRY_PUSH_TOKEN"]["least_privilege"] is True
    assert payload["REGISTRY_PUSH_TOKEN"]["rotation_state"] == "current"


def test_protected_k8s_release_cli_trigger_requires_trusted_metadata(tmp_path, capsys):
    from deeptutor_enterprise.protected_k8s_release_cli import main

    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(_registry(), ensure_ascii=False), encoding="utf8")
    output_dir = tmp_path / "metadata"
    output_env = tmp_path / ".deeptutor-release.env"

    with pytest.raises(SystemExit):
        main(
            [
                "trigger",
                "--registry",
                str(registry_path),
                "--event",
                "tag",
                "--ref",
                "refs/tags/deploy/prod-cn-east/v1.4.0",
                "--tag",
                "deploy/prod-cn-east/v1.4.0",
                "--tag-object-sha",
                _TAG_SHA,
                "--commit-sha",
                _SHA_A,
                "--actor",
                "release-manager",
                "--approval-id",
                "approval-123",
                "--output",
                str(output_dir),
            ]
        )

    metadata_path = tmp_path / "trusted-trigger-metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "protected_ref": True,
                "approved": True,
                "approval_id": "approval-123",
                "actor": "release-manager",
                "tag_object_sha": _TAG_SHA,
                "commit_sha": _SHA_A,
                "trust_source": "vcs-protected-tag-api",
            },
            ensure_ascii=False,
        ),
        encoding="utf8",
    )
    assert (
        main(
            [
                "trigger",
                "--registry",
                str(registry_path),
                "--event",
                "tag",
                "--ref",
                "refs/tags/deploy/prod-cn-east/v1.4.0",
                "--tag",
                "deploy/prod-cn-east/v1.4.0",
                "--trusted-metadata",
                str(metadata_path),
                "--output",
                str(output_dir),
            ]
        )
        == 0
    )
    captured = json.loads(capsys.readouterr().out)
    payload = json.loads(Path(captured["trigger_gate"]).read_text(encoding="utf8"))
    assert payload["ready"] is True
    assert payload["trust_source"] == "vcs-protected-tag-api"


def test_release_manifest_and_rollback_digest_must_match_target_env_registry():
    from deeptutor_enterprise.protected_k8s_release import (
        EnvironmentRegistry,
        build_release_manifest,
        decide_rollback,
    )

    registry = EnvironmentRegistry.model_validate(_registry())
    with pytest.raises(ValueError, match="image_digest_registry_mismatch:backend"):
        build_release_manifest(
            registry,
            target_env_id="prod-cn-east",
            version="v1.4.0",
            tag="deploy/prod-cn-east/v1.4.0",
            tag_object_sha=_TAG_SHA,
            tag_creator="release-manager",
            source_sha=_SHA_A,
            upstream_sha=_SHA_B,
            enterprise_package_version="0.1.0",
            backend_image_digest="registry.example/deeptutor/prod-overseas-a/backend@sha256:" + "1" * 64,
            frontend_image_digest="registry.example/deeptutor/prod-cn-east/frontend@sha256:" + "2" * 64,
            build_run_id="woodpecker-100",
            scan_summary={},
        )

    with pytest.raises(ValueError, match="image_digest_registry_mismatch:rollback"):
        decide_rollback(
            registry,
            "prod-cn-east",
            failure_code="smoke_failed",
            previous_release_compatible=True,
            previous_digest="registry.example/deeptutor/prod-overseas-a/backend@sha256:" + "5" * 64,
            approval_id="rollback-approval-1",
        )


def test_environment_registry_rejects_cross_environment_resources():
    from deeptutor_enterprise.protected_k8s_release import EnvironmentRegistry

    bad = _registry()
    prod = next(env for env in bad["environments"] if env["env_id"] == "prod-cn-east")
    prod["kubernetes"]["namespace"] = "deeptutor-prod-overseas-a"
    with pytest.raises(Exception, match="namespace"):
        EnvironmentRegistry.model_validate(bad)

    bad = _registry()
    prod = next(env for env in bad["environments"] if env["env_id"] == "prod-cn-east")
    prod["release_control"]["release_lock_ref"] = "postgres:prod-overseas-a/release_locks"
    with pytest.raises(Exception, match="release_lock_ref"):
        EnvironmentRegistry.model_validate(bad)

    bad = _registry()
    prod = next(env for env in bad["environments"] if env["env_id"] == "prod-cn-east")
    prod["data_plane"]["object_store_ref"] = "external-secret:prod-overseas-a/objectstore"
    with pytest.raises(Exception, match="object_store_ref"):
        EnvironmentRegistry.model_validate(bad)


def test_secret_leakage_scan_detects_json_secret_keys(tmp_path):
    from deeptutor_enterprise.protected_k8s_release import scan_secret_leakage

    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "manifest.json").write_text(
        json.dumps(
            {
                "client_secret": "super-secret-value",
                "openai_api_key": "sk-test",
                "Authorization": "Bearer token",
            },
            ensure_ascii=False,
        ),
        encoding="utf8",
    )
    report = scan_secret_leakage(evidence)
    assert report["ready"] is False
    assert "secret_leak_detected" in report["error_codes"]
    assert {leak["code"] for leak in report["leaks"]} >= {
        "json_sensitive_key:client_secret",
        "json_sensitive_key:openai_api_key",
        "json_sensitive_key:Authorization",
    }
