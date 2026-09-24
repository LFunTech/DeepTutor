import importlib.util

import pytest


def test_secret_references_and_model_policy_are_immutable(monkeypatch):
    assert importlib.util.find_spec("deeptutor_enterprise.configuration"), (
        "部署配置provider尚未实现"
    )
    from deeptutor_enterprise.configuration import Configuration, DeploymentConfig

    monkeypatch.setenv("TEST_MODEL_SECRET", "model-secret")
    raw = {
        "version": 1,
        "tenant_id": "62ccf04e-0913-4fef-961e-ffbc6d8e449c",
        "resource": "isolated",
        "database_secret": "env:TEST_DATABASE_SECRET",
        "signing_secret": "env:TEST_SIGNING_SECRET",
        "auth_epoch_secret": "env:TEST_AUTH_EPOCH",
        "origins": ["https://school.example"],
        "models": [
            {
                "profile_id": "chat",
                "model_id": "primary",
                "model": "some-model",
                "base_url": "https://model.example/v1",
                "secret": "env:TEST_MODEL_SECRET",
                "allowed_roles": ["user", "tenant_admin"],
            }
        ],
    }
    config = Configuration(DeploymentConfig.model_validate(raw))
    selection = {"profile_id": "chat", "model_id": "primary"}
    assert config.resolve_model(selection, role="user", user_id="u").api_key == "model-secret"
    assert config.resolve_model(selection, role="tenant_admin", user_id="a").model == "some-model"
    raw["models"][0]["model"] = "tampered"
    assert config.resolve_model(selection, role="user", user_id="u").model == "some-model"
    for role in ["user", "tenant_admin"]:
        with pytest.raises(PermissionError):
            config.resolve_model(
                {"profile_id": "other", "model_id": "primary"}, role=role, user_id="u"
            )
    assert "model-secret" not in repr(config)
    assert config.agent_params("summary")["max_tokens"] > 0


def test_reject_insecure_origins_and_secret_literals():
    assert importlib.util.find_spec("deeptutor_enterprise.configuration")
    from deeptutor_enterprise.configuration import ModelDeployment, SecretReference
    from pydantic import TypeAdapter, ValidationError

    for value in ["actual-password", "env:", "env:../../bad"]:
        with pytest.raises(ValidationError):
            TypeAdapter(SecretReference).validate_python(value)
    with pytest.raises(ValidationError):
        ModelDeployment(
            profile_id="p",
            model_id="m",
            model="model",
            base_url="file:///etc",
            secret="env:KEY",
            allowed_roles=["admin"],
        )

def test_deployment_config_allows_rag_tool_for_required_knowledge_bases():
    from deeptutor_enterprise.configuration import DeploymentConfig

    config = DeploymentConfig.model_validate(
        {
            "version": 1,
            "tenant_id": "62ccf04e-0913-4fef-961e-ffbc6d8e449c",
            "resource": "isolated",
            "database_secret": "env:TEST_DATABASE_SECRET",
            "signing_secret": "env:TEST_SIGNING_SECRET",
            "auth_epoch_secret": "env:TEST_AUTH_EPOCH",
            "origins": ["https://school.example"],
            "allowed_tools": ["ask_user", "rag"],
            "models": [
                {
                    "profile_id": "chat",
                    "model_id": "primary",
                    "model": "some-model",
                    "base_url": "https://model.example/v1",
                    "secret": "env:TEST_MODEL_SECRET",
                    "allowed_roles": ["user", "tenant_admin"],
                }
            ],
        }
    )

    assert config.allowed_tools == ("ask_user", "rag")


def test_lightrag_binding_allows_loopback_only_outside_production():
    from deeptutor_enterprise.configuration import DeploymentConfig, LightRAGBinding
    from pydantic import ValidationError

    local = LightRAGBinding.model_validate(
        {
            "endpoint": "http://127.0.0.1:9621",
            "api_secret": "env:LIGHTRAG_API_KEY",
            "workspace_binding": "local",
            "index_version": "idx-local",
            "contract_version": "lightrag-api-v1",
        }
    )
    assert local.endpoint == "http://127.0.0.1:9621"

    raw = {
        "version": 1,
        "tenant_id": "62ccf04e-0913-4fef-961e-ffbc6d8e449c",
        "resource": "isolated",
        "database_secret": "env:TEST_DATABASE_SECRET",
        "signing_secret": "env:TEST_SIGNING_SECRET",
        "auth_epoch_secret": "env:TEST_AUTH_EPOCH",
        "origins": ["https://school.example"],
        "models": [
            {
                "profile_id": "chat",
                "model_id": "primary",
                "model": "some-model",
                "base_url": "https://model.example/v1",
                "secret": "env:TEST_MODEL_SECRET",
                "allowed_roles": ["user", "tenant_admin"],
            }
        ],
        "object_store": {
            "provider": "s3-compatible",
            "endpoint": "https://objects.example",
            "bucket": "deeptutor-test",
            "region": "us-east-1",
            "access_key_secret": "env:OBJECT_ACCESS",
            "secret_key_secret": "env:OBJECT_SECRET",
        },
        "settings_provider": {"kind": "postgres"},
        "secret_provider": {"kind": "env", "name": "test"},
        "lightrag": local.model_dump(),
        "eduplus2": {
            "base_url": "https://eduplus2.example",
            "client_id": "eduplus2",
            "client_secret": "env:EDUPLUS2_SECRET",
        },
        "production": {"runtime_mode": "production"},
    }
    with pytest.raises(ValidationError):
        DeploymentConfig.model_validate(raw)
