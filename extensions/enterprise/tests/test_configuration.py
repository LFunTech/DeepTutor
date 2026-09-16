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
