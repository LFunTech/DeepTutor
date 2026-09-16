from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from deeptutor.runtime.data_gate import RuntimeMode


def test_env_secret_resolver_returns_redacted_secret_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """若 SecretResolver 泄漏明文或接受非引用 Secret，本测试应失败。"""

    from deeptutor.runtime.externalized_providers import EnvSecretResolver, SecretRef

    monkeypatch.setenv("OBJECT_STORE_SECRET", "secret-sentinel-value")
    resolver = EnvSecretResolver()

    secret = resolver.resolve(SecretRef.parse("env:OBJECT_STORE_SECRET"))

    assert secret.reveal() == "secret-sentinel-value"
    assert "secret-sentinel-value" not in repr(secret)
    assert "secret-sentinel-value" not in resolver.safe_status(SecretRef.parse("env:OBJECT_STORE_SECRET"))
    with pytest.raises(ValueError):
        SecretRef.parse("secret-sentinel-value")


def test_local_dev_object_store_verifies_hash_and_is_disabled_in_production(tmp_path: Path) -> None:
    """若 local-dev object store 可在 production 充当权威或不校验 hash，本测试应失败。"""

    from deeptutor.runtime.externalized_providers import LocalDevObjectStore, ProviderModeError

    store = LocalDevObjectStore(tmp_path / "objects", mode=RuntimeMode("local"))
    data = b"artifact-bytes"
    digest = hashlib.sha256(data).hexdigest()

    ref = store.put_bytes("tenant-a/owner-a/artifact.bin", data, expected_sha256=digest)

    assert ref.key == "tenant-a/owner-a/artifact.bin"
    assert ref.size_bytes == len(data)
    assert ref.sha256 == digest
    assert store.get_bytes(ref) == data
    with pytest.raises(ValueError):
        store.put_bytes("../escape.bin", b"bad")
    with pytest.raises(ValueError):
        store.put_bytes("tenant-a/owner-a/bad.bin", data, expected_sha256="0" * 64)
    with pytest.raises(ProviderModeError):
        LocalDevObjectStore(tmp_path / "prod-objects", mode=RuntimeMode("production"))


def test_resource_handle_is_metadata_only_and_local_settings_provider_is_mode_gated(
    tmp_path: Path,
) -> None:
    """若资源引用暴露本地 path，或 local settings provider 在 production 可写，本测试应失败。"""

    from deeptutor.runtime.externalized_providers import (
        LocalDevSettingsProvider,
        ProviderModeError,
        ResourceHandle,
    )

    handle = ResourceHandle(
        tenant_id="tenant-a",
        owner_id="owner-a",
        resource_kind="attachment",
        resource_id="resource-1",
        object_id="object-1",
        version=1,
        state="ready",
        size_bytes=3,
        sha256="a" * 64,
        mime_type="text/plain",
    )

    assert "path" not in handle.__dict__
    assert "local" not in repr(handle).lower()

    provider = LocalDevSettingsProvider(mode=RuntimeMode("local"))
    provider.save("tenant-a", "model.default", {"profile": "safe"}, actor="admin")
    assert provider.load("tenant-a", "model.default").active == {"profile": "safe"}
    with pytest.raises(ProviderModeError):
        LocalDevSettingsProvider(mode=RuntimeMode("kubernetes"))
