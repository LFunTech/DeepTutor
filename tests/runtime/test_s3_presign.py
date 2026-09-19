from __future__ import annotations

from deeptutor.runtime.externalized_providers import (
    EnvSecretResolver,
    S3CompatibleObjectStore,
    S3ObjectStoreConfig,
    SecretRef,
)


def test_s3_presigned_put_url_is_short_lived_and_does_not_expose_secret(monkeypatch):
    monkeypatch.setenv("OBJ_ACCESS", "AKIATEST")
    monkeypatch.setenv("OBJ_SECRET", "super-secret-value")
    store = S3CompatibleObjectStore(
        S3ObjectStoreConfig(
            endpoint="https://objects.example",
            region="us-east-1",
            bucket="deeptutor-runtime",
            access_key_ref=SecretRef.parse("env:OBJ_ACCESS"),
            secret_key_ref=SecretRef.parse("env:OBJ_SECRET"),
        ),
        secret_resolver=EnvSecretResolver(),
    )

    signed = store.presign_put(
        "tenants/t1/resource.bin",
        expires_seconds=300,
        content_type="image/png",
        size_bytes=12,
        expected_sha256="a" * 64,
    )

    assert signed.url.startswith("https://objects.example/deeptutor-runtime/tenants/t1/resource.bin?")
    assert "X-Amz-Expires=300" in signed.url
    assert "X-Amz-Signature=" in signed.url
    assert "super-secret-value" not in signed.url
    assert signed.headers["content-type"] == "image/png"
    assert signed.headers["x-amz-meta-sha256"] == "a" * 64
