"""M1/G1 单租户生产基线门禁。"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

VALID_UUID = "11111111-1111-4111-8111-111111111111"


def _base_deployment() -> dict:
    return {
        "version": 1,
        "tenant_id": VALID_UUID,
        "resource": "m1-g1",
        "database_secret": "env:DT_DATABASE_DSN",
        "migration_database_secret": "env:DT_MIGRATION_DATABASE_DSN",
        "signing_secret": "env:DT_SIGNING_KEY",
        "auth_epoch_secret": "env:DT_AUTH_EPOCH",
        "origins": ["https://school.example"],
        "models": [
            {
                "profile_id": "chat",
                "model_id": "primary",
                "model": "gpt-test",
                "base_url": "https://model.example/v1",
                "secret": "env:DT_MODEL_API_KEY",
                "allowed_roles": ["user", "tenant_admin"],
            }
        ],
        "object_store": {
            "provider": "s3-compatible",
            "endpoint": "https://objects.example.internal",
            "bucket": "deeptutor-runtime",
            "region": "us-east-1",
            "access_key_secret": "env:DT_OBJECTSTORE_ACCESS_KEY",
            "secret_key_secret": "env:DT_OBJECTSTORE_SECRET_KEY",
            "prefix": "m1-g1",
        },
        "settings_provider": {"kind": "postgres"},
        "secret_provider": {"kind": "external-secret", "name": "platform-secret-store"},
        "lightrag": {
            "endpoint": "https://lightrag.example.internal",
            "api_secret": "env:DT_LIGHTRAG_API_KEY",
            "workspace_binding": "m1-g1-fixed-workspace",
            "index_version": "kb-v1",
            "contract_version": "2026-09-g1",
        },
        "eduplus2": {
            "base_url": "https://eduplus2.example.internal",
            "client_id": "deeptutor-smoke",
            "client_secret": "env:DT_EDUPLUS2_CLIENT_SECRET",
            "allowed_clients_ref": "env:DT_EDUPLUS2_ALLOWED_CLIENTS",
        },
        "production": {
            "runtime_mode": "production",
            "local_authority_fallback": False,
            "sqlite_fallback": False,
            "pocketbase_fallback": False,
            "required_readiness": [
                "postgres",
                "object_store",
                "secret_provider",
                "lightrag",
                "eduplus2",
            ],
        },
    }


def test_deployment_config_requires_m1_g1_bindings_and_rejects_local_fallback():
    from deeptutor_enterprise.configuration import DeploymentConfig

    config = DeploymentConfig.model_validate(_base_deployment())
    assert config.object_store.bucket == "deeptutor-runtime"
    assert config.production.runtime_mode == "production"
    assert config.production.required_readiness == (
        "postgres",
        "object_store",
        "secret_provider",
        "lightrag",
        "eduplus2",
    )

    bad = _base_deployment()
    bad["production"]["sqlite_fallback"] = True
    with pytest.raises(Exception, match="fallback"):
        DeploymentConfig.model_validate(bad)

    bad = _base_deployment()
    bad["object_store"]["endpoint"] = "http://objects.example.internal"
    with pytest.raises(Exception, match="HTTPS"):
        DeploymentConfig.model_validate(bad)


def test_readiness_inventory_fails_closed_for_missing_required_bindings(monkeypatch):
    from deeptutor_enterprise.configuration import DeploymentConfig
    from deeptutor_enterprise.m1_g1 import readiness_inventory

    config = DeploymentConfig.model_validate(_base_deployment())
    for name in [
        "DT_DATABASE_DSN",
        "DT_MIGRATION_DATABASE_DSN",
        "DT_SIGNING_KEY",
        "DT_AUTH_EPOCH",
        "DT_MODEL_API_KEY",
        "DT_OBJECTSTORE_ACCESS_KEY",
        "DT_OBJECTSTORE_SECRET_KEY",
        "DT_LIGHTRAG_API_KEY",
        "DT_EDUPLUS2_CLIENT_SECRET",
        "DT_EDUPLUS2_ALLOWED_CLIENTS",
    ]:
        monkeypatch.setenv(name, "set")
    inventory = readiness_inventory(config)
    assert inventory["ready"] is True
    assert inventory["local_authority_fallback"] == "disabled"

    monkeypatch.delenv("DT_LIGHTRAG_API_KEY")
    inventory = readiness_inventory(config)
    assert inventory["ready"] is False
    assert "lightrag_secret_missing" in inventory["error_codes"]
    assert "set" not in json.dumps(inventory)


def test_release_evidence_is_traceable_and_redacts_sensitive_values(tmp_path):
    from deeptutor_enterprise.m1_g1 import ReleaseEvidence

    evidence = ReleaseEvidence(
        release_id="g1-20260918-001",
        source_sha="a" * 40,
        upstream_sha="b" * 40,
        backend_image_digest="ghcr.io/lfuntech/deeptutor-backend@sha256:" + "1" * 64,
        frontend_image_digest="ghcr.io/lfuntech/deeptutor-frontend@sha256:" + "2" * 64,
        schema_version="20260918_m1_g1",
        runtime_mode="production",
        secret_refs=["env:DT_DATABASE_DSN", "env:DT_MODEL_API_KEY"],
        smoke_run_id="smoke-123",
        approval="test-approval",
        unresolved=["target_k8s_not_run"],
    )
    output = evidence.write(
        tmp_path, extra={"note": "contains dt_token marker", "secret": "client-secret"}
    )
    text = output.read_text(encoding="utf8")
    assert "source_sha" in text
    assert "env:DT_DATABASE_DSN" in text
    assert "contains dt_token marker" not in text
    assert "client-secret" not in text
    assert "[REDACTED]" in text


def test_smoke_plan_records_required_cases_and_blocks_unverified_lightrag():
    from deeptutor_enterprise.m1_g1 import build_smoke_plan

    plan = build_smoke_plan(base_url="https://deeptutor.example", lightrag_sample_ready=False)
    case_ids = {case["id"] for case in plan["cases"]}
    assert {
        "http_status",
        "eduplus2_exchange",
        "ws_start_turn",
        "ws_auth_refresh",
        "object_store",
        "audit_export",
        "owner_guard_denied",
    } <= case_ids
    assert "lightrag_sample_unavailable" in plan["blocking_unverified"]
    assert plan["claims_full_production"] is False


def _target_deployment_contract() -> dict:
    return {
        "contract_version": "2026-09-g1",
        "environment": "test",
        "tenant_mode": "single-tenant",
        "topology_source": "target-environment-contract",
        "target_base_url": "https://deeptutor.example",
        "woodpecker": {
            "server_url": "https://woodpecker.example",
            "server_version": "3.2.1",
            "agent_version": "3.2.1",
            "agent_backend": "kubernetes",
            "protected_refs": ["refs/heads/main", "refs/tags/prod-*"],
            "approval_gate": "protected-environment-approval",
            "secret_boundary": "production-secrets-only-after-approval",
            "registry": {
                "repository": "registry.example/deeptutor/backend",
                "credentials_ref": "woodpecker:registry-prod",
            },
        },
        "kubernetes": {
            "namespace": "deeptutor-m1-g1",
            "ingress_host": "deeptutor.example",
            "tls_secret_ref": "k8s:deeptutor-tls",
            "secret_store_ref": "external-secret:platform",
            "service_account": "deeptutor-runtime",
            "network_policy": "default-deny-with-egress-allowlist",
            "release_lock_ref": "postgres:enterprise.release_locks/m1-g1",
            "backend_executor_replicas": 1,
            "rollout_strategy": "single-executor-drain",
        },
        "rollback": {
            "strategy": "previous-digest-if-compatible",
            "previous_release_ref": "object-store:release-evidence/latest-successful",
            "requires_smoke_after_rollback": True,
        },
        "evidence_store": {
            "kind": "object-store",
            "location_ref": "object-store:deeptutor-release-evidence/m1-g1",
            "retention_days": 180,
        },
    }


def test_target_deployment_contract_requires_target_topology_and_single_executor():
    from deeptutor_enterprise.m1_g1 import TargetDeploymentContract

    contract = TargetDeploymentContract.model_validate(_target_deployment_contract())
    assert contract.topology_source == "target-environment-contract"
    assert contract.kubernetes.backend_executor_replicas == 1

    bad = _target_deployment_contract()
    bad["topology_source"] = "single-tenant-derived"
    with pytest.raises(Exception, match="target-environment-contract"):
        TargetDeploymentContract.model_validate(bad)

    bad = _target_deployment_contract()
    bad["kubernetes"]["backend_executor_replicas"] = 2
    with pytest.raises(Exception):
        TargetDeploymentContract.model_validate(bad)


def test_target_deployment_contract_inventory_is_redacted_and_actionable():
    from deeptutor_enterprise.m1_g1 import (
        TargetDeploymentContract,
        deployment_contract_inventory,
    )

    contract = TargetDeploymentContract.model_validate(_target_deployment_contract())
    inventory = deployment_contract_inventory(contract)
    text = json.dumps(inventory, ensure_ascii=False)

    assert inventory["ready"] is True
    assert inventory["topology_source"] == "target-environment-contract"
    assert inventory["woodpecker"]["agent_backend"] == "kubernetes"
    assert inventory["kubernetes"]["backend_executor_replicas"] == 1
    assert "registry-prod" not in text
    assert "deeptutor.example" not in text
    assert "host_hash" in inventory["target_base_url"]


def test_m1_g1_cli_writes_redacted_deployment_contract_inventory(tmp_path, capsys):
    from deeptutor_enterprise.m1_g1_cli import main

    contract_path = tmp_path / "deployment-contract.json"
    payload = _target_deployment_contract()
    payload["x_open_spec_note"] = "example-only-not-a3-evidence"
    contract_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf8")
    output_dir = tmp_path / "evidence"

    assert main(["contract", "--input", str(contract_path), "--output", str(output_dir)]) == 0
    captured = json.loads(capsys.readouterr().out)
    output = output_dir / "deployment-contract.json"
    assert captured == {"deployment_contract": str(output)}

    text = output.read_text(encoding="utf8")
    payload = json.loads(text)
    assert payload["ready"] is True
    assert payload["topology_source"] == "target-environment-contract"
    assert "registry-prod" not in text
    assert "deeptutor.example" not in text


def test_deployment_contract_example_validates_without_claiming_a3_completion():
    from deeptutor_enterprise.m1_g1 import TargetDeploymentContract

    example_path = Path(__file__).resolve().parents[1] / "deployment-contract.example.json"
    payload = json.loads(example_path.read_text(encoding="utf8"))
    assert payload["x_open_spec_note"] == "example-only-not-a3-evidence"
    contract_payload = {key: value for key, value in payload.items() if not key.startswith("x_")}
    contract = TargetDeploymentContract.model_validate(contract_payload)

    assert contract.topology_source == "target-environment-contract"
    assert contract.tenant_mode == "single-tenant"
    assert contract.kubernetes.backend_executor_replicas == 1


async def test_smoke_harness_output_redacts_base_url_and_tokens(monkeypatch):
    from deeptutor_enterprise.smoke import run_smoke

    monkeypatch.setenv("DT_SMOKE_DT_TOKEN", "dt_" + "a" * 32)
    monkeypatch.setenv("DT_SMOKE_EDUPLUS2_JWT", "header.payload.signature")

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in {"/tms", "/oms"}:
            return httpx.Response(404)
        if request.url.path == "/api/v1/auth/eduplus2/exchange":
            return httpx.Response(401)
        return httpx.Response(200)

    result = await run_smoke(
        base_url="https://deeptutor.example",
        transport=httpx.MockTransport(handler),
    )
    text = json.dumps(result, ensure_ascii=False)

    assert result["base_url"]["scheme"] == "https"
    assert "host_hash" in result["base_url"]
    assert "deeptutor.example" not in text
    assert "dt_" + "a" * 32 not in text
    assert "header.payload.signature" not in text


def test_governance_projection_exports_oms_inputs_without_governance_controls():
    from deeptutor_enterprise.m1_g1 import (
        ReleaseEvidence,
        TargetDeploymentContract,
        build_governance_projection,
        deployment_contract_inventory,
    )

    evidence = ReleaseEvidence(
        release_id="g1-20260918-002",
        source_sha="a" * 40,
        upstream_sha="b" * 40,
        backend_image_digest="ghcr.io/lfuntech/deeptutor-backend@sha256:" + "3" * 64,
        frontend_image_digest="ghcr.io/lfuntech/deeptutor-frontend@sha256:" + "4" * 64,
        schema_version="20260918_m1_g1",
        runtime_mode="production",
        secret_refs=["env:DT_DATABASE_DSN", "env:DT_MODEL_API_KEY"],
        smoke_run_id="g1-smoke-123",
        approval="approval-001",
        unresolved=["target_k8s_not_run"],
    ).to_dict(extra={"pipeline": {"run_id": "woodpecker-42", "secret": "client-secret"}})
    contract = TargetDeploymentContract.model_validate(_target_deployment_contract())

    projection = build_governance_projection(
        release_evidence=evidence,
        deployment_contract=deployment_contract_inventory(contract),
        audit_export={
            "format": "jsonl",
            "row_count": 2,
            "file_ref": "db://eduplus2/audit-export/job-1",
            "preview": "request=req-1 dt_token marker",
        },
    )
    rendered = json.dumps(projection, ensure_ascii=False)

    assert projection["future_oms_input"] is True
    assert projection["online_policy_mutation"] == "not_available"
    assert projection["cross_tenant_governance"] == "not_available"
    assert {
        "release_id",
        "source_sha",
        "backend_image_digest",
        "smoke_run_id",
        "audit_export",
        "evidence_store",
    } <= set(projection["governance_fields"])
    assert "client-secret" not in rendered
    assert "dt_token marker" not in rendered
    assert "deeptutor.example" not in rendered


def test_m1_g1_cli_writes_governance_projection_without_policy_controls(tmp_path, capsys):
    from deeptutor_enterprise.m1_g1 import (
        ReleaseEvidence,
        TargetDeploymentContract,
        deployment_contract_inventory,
    )
    from deeptutor_enterprise.m1_g1_cli import main

    evidence = ReleaseEvidence(
        release_id="g1-20260918-003",
        source_sha="a" * 40,
        upstream_sha="b" * 40,
        backend_image_digest="ghcr.io/lfuntech/deeptutor-backend@sha256:" + "5" * 64,
        frontend_image_digest="ghcr.io/lfuntech/deeptutor-frontend@sha256:" + "6" * 64,
        schema_version="20260918_m1_g1",
        runtime_mode="production",
        secret_refs=["env:DT_DATABASE_DSN"],
        smoke_run_id="g1-smoke-456",
        approval="approval-002",
    ).to_dict(extra={"pipeline": {"run_id": "woodpecker-43", "secret": "client-secret"}})
    release_path = tmp_path / "manifest.json"
    release_path.write_text(json.dumps(evidence, ensure_ascii=False), encoding="utf8")
    contract_path = tmp_path / "deployment-contract.json"
    contract = TargetDeploymentContract.model_validate(_target_deployment_contract())
    contract_path.write_text(
        json.dumps(deployment_contract_inventory(contract), ensure_ascii=False),
        encoding="utf8",
    )
    audit_path = tmp_path / "audit-export.json"
    audit_path.write_text(
        json.dumps(
            {"format": "jsonl", "row_count": 1, "preview": "dt_token marker"},
            ensure_ascii=False,
        ),
        encoding="utf8",
    )
    output_dir = tmp_path / "governance"

    assert (
        main(
            [
                "governance",
                "--release-evidence",
                str(release_path),
                "--deployment-contract",
                str(contract_path),
                "--audit-export",
                str(audit_path),
                "--output",
                str(output_dir),
            ]
        )
        == 0
    )
    captured = json.loads(capsys.readouterr().out)
    output = output_dir / "governance-projection.json"
    assert captured == {"governance_projection": str(output)}

    text = output.read_text(encoding="utf8")
    payload = json.loads(text)
    assert payload["future_oms_input"] is True
    assert payload["online_policy_mutation"] == "not_available"
    assert payload["cross_tenant_governance"] == "not_available"
    assert "client-secret" not in text
    assert "dt_token marker" not in text


def test_governance_gate_fails_closed_for_missing_usage_and_policy_gaps():
    from deeptutor_enterprise.m1_g1 import evaluate_governance_gate

    gate = evaluate_governance_gate(
        usage_accounted=False,
        lightrag_remote_confirmed=False,
        revocation_window_implemented=False,
        policy_source_consistent=False,
    )

    assert gate["ready"] is False
    assert gate["decision"] == "unavailable"
    assert {
        "usage_missing",
        "lightrag_remote_unconfirmed",
        "revocation_window_not_implemented",
        "policy_source_inconsistent",
    } <= set(gate["error_codes"])
    assert gate["online_policy_mutation"] == "not_available"
    assert gate["cross_tenant_governance"] == "not_available"


def test_governance_gate_allows_only_when_c2_inputs_are_confirmed():
    from deeptutor_enterprise.m1_g1 import evaluate_governance_gate

    gate = evaluate_governance_gate(
        usage_accounted=True,
        lightrag_remote_confirmed=True,
        revocation_window_implemented=True,
        policy_source_consistent=True,
    )

    assert gate["ready"] is True
    assert gate["decision"] == "available_for_evidence_only"
    assert gate["error_codes"] == []
    assert gate["online_policy_mutation"] == "not_available"


def test_resource_binding_evidence_records_hashes_and_blocks_missing_lightrag_sample():
    from deeptutor_enterprise.configuration import DeploymentConfig
    from deeptutor_enterprise.m1_g1 import build_resource_binding_evidence

    config = DeploymentConfig.model_validate(_base_deployment())
    evidence = build_resource_binding_evidence(
        config,
        object_manifest_hash="sha256:" + "a" * 64,
        lightrag_service_status="unavailable",
        cleanup_result="not_run",
        lightrag_sample_ready=False,
    )
    rendered = json.dumps(evidence, ensure_ascii=False)

    assert evidence["ready"] is False
    assert "lightrag_sample_unavailable" in evidence["blocking_unverified"]
    assert evidence["object_store"]["manifest_hash"] == "sha256:" + "a" * 64
    assert evidence["object_store"]["cleanup_result"] == "not_run"
    assert evidence["lightrag"]["service_status"] == "unavailable"
    assert evidence["lightrag"]["index_version"] == "kb-v1"
    assert "deeptutor-runtime" not in rendered
    assert "objects.example.internal" not in rendered
    assert "m1-g1-fixed-workspace" not in rendered


def test_m1_g1_cli_writes_resource_binding_evidence(tmp_path, capsys):
    from deeptutor_enterprise.m1_g1_cli import main

    deployment_path = tmp_path / "deployment.json"
    deployment_path.write_text(json.dumps(_base_deployment(), ensure_ascii=False), encoding="utf8")
    output_dir = tmp_path / "resources"

    assert (
        main(
            [
                "resources",
                "--deployment",
                str(deployment_path),
                "--object-manifest-hash",
                "sha256:" + "b" * 64,
                "--lightrag-service-status",
                "unavailable",
                "--cleanup-result",
                "not_run",
                "--output",
                str(output_dir),
            ]
        )
        == 0
    )
    captured = json.loads(capsys.readouterr().out)
    output = output_dir / "resource-binding.json"
    assert captured == {"resource_binding": str(output)}

    text = output.read_text(encoding="utf8")
    payload = json.loads(text)
    assert payload["ready"] is False
    assert "lightrag_sample_unavailable" in payload["blocking_unverified"]
    assert "deeptutor-runtime" not in text
    assert "objects.example.internal" not in text
