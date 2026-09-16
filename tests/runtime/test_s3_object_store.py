from __future__ import annotations

import hashlib
import os
from typing import Any
import uuid

import httpx
import pytest

from deeptutor.persistence.postgres.configuration import SecretValue
from deeptutor.runtime.externalized_providers import SecretRef


class RecordingResolver:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values
        self.calls: list[str] = []

    def resolve(self, ref: SecretRef) -> SecretValue:
        self.calls.append(ref.safe_label())
        return SecretValue(self.values[ref.name])


def _config(**updates: Any):
    from deeptutor.runtime.externalized_providers import S3ObjectStoreConfig

    raw = {
        "endpoint": "https://storage.example:9000",
        "region": "us-east-1",
        "bucket": "deeptutor-assets",
        "access_key_ref": SecretRef.parse("env:S3_ACCESS_KEY"),
        "secret_key_ref": SecretRef.parse("env:S3_SECRET_KEY"),
        "path_style": True,
        "server_side_encryption": "AES256",
        "timeout_seconds": 3.0,
        "max_retries": 0,
    }
    raw.update(updates)
    return S3ObjectStoreConfig(**raw)


def test_s3_object_store_config_from_environment_uses_secret_refs_not_plaintext() -> None:
    """若环境配置读取 Secret 明文而非 SecretRef，本测试应失败。"""

    from deeptutor.runtime.externalized_providers import S3ObjectStoreConfig

    config = S3ObjectStoreConfig.from_environment(
        {
            "DEEPTUTOR_OBJECTSTORE_ENDPOINT": "https://storage.example",
            "DEEPTUTOR_OBJECTSTORE_REGION": "cn-north-1",
            "DEEPTUTOR_OBJECTSTORE_BUCKET": "deeptutor-assets",
            "DEEPTUTOR_OBJECTSTORE_ACCESS_KEY_REF": "env:COMPAT_ACCESS_KEY",
            "DEEPTUTOR_OBJECTSTORE_SECRET_KEY_REF": "env:COMPAT_SECRET_KEY",
            "DEEPTUTOR_OBJECTSTORE_SESSION_TOKEN_REF": "env:COMPAT_SESSION_TOKEN",
            "DEEPTUTOR_OBJECTSTORE_PATH_STYLE": "false",
            "DEEPTUTOR_OBJECTSTORE_VERIFY_TLS": "true",
            "DEEPTUTOR_OBJECTSTORE_SERVER_SIDE_ENCRYPTION": "AES256",
            "DEEPTUTOR_OBJECTSTORE_TIMEOUT_SECONDS": "2.5",
            "DEEPTUTOR_OBJECTSTORE_MAX_RETRIES": "3",
            "DEEPTUTOR_OBJECTSTORE_RETRY_BACKOFF_SECONDS": "0.2",
            "COMPAT_ACCESS_KEY": "access-key-plaintext-must-not-be-read",
            "COMPAT_SECRET_KEY": "secret-key-plaintext-must-not-be-read",
        }
    )

    assert config.endpoint == "https://storage.example"
    assert config.region == "cn-north-1"
    assert config.bucket == "deeptutor-assets"
    assert config.access_key_ref.safe_label() == "env:COMPAT_ACCESS_KEY"
    assert config.secret_key_ref.safe_label() == "env:COMPAT_SECRET_KEY"
    assert config.session_token_ref is not None
    assert config.session_token_ref.safe_label() == "env:COMPAT_SESSION_TOKEN"
    assert config.path_style is False
    assert config.verify_tls is True
    assert config.server_side_encryption == "AES256"
    assert config.timeout_seconds == 2.5
    assert config.max_retries == 3
    assert config.retry_backoff_seconds == 0.2
    assert "plaintext-must-not-be-read" not in repr(config)


def test_s3_object_store_put_uses_secret_resolver_path_style_sse_and_verifies_hash_size() -> None:
    """若上传绕过 SecretResolver、漏掉 path-style/SSE 或不做 HEAD 校验，本测试应失败。"""

    from deeptutor.runtime.externalized_providers import S3CompatibleObjectStore

    requests: list[httpx.Request] = []
    data = b"deep tutor artifact"
    digest = hashlib.sha256(data).hexdigest()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert "secret-sentinel" not in request.headers.get("authorization", "")
        if request.method == "PUT":
            assert request.url.path == "/deeptutor-assets/tenant-a/owner-a/file.txt"
            assert request.headers["x-amz-server-side-encryption"] == "AES256"
            assert request.headers["x-amz-meta-sha256"] == digest
            assert request.content == data
            return httpx.Response(200, request=request)
        if request.method == "HEAD":
            return httpx.Response(
                200,
                headers={"content-length": str(len(data)), "x-amz-meta-sha256": digest},
                request=request,
            )
        raise AssertionError(f"unexpected request: {request.method}")

    resolver = RecordingResolver(
        {"S3_ACCESS_KEY": "access-id", "S3_SECRET_KEY": "secret-sentinel-value"}
    )
    store = S3CompatibleObjectStore(
        _config(),
        secret_resolver=resolver,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    ref = store.put_bytes("tenant-a/owner-a/file.txt", data, expected_sha256=digest)

    assert ref.key == "tenant-a/owner-a/file.txt"
    assert ref.size_bytes == len(data)
    assert ref.sha256 == digest
    assert [request.method for request in requests] == ["PUT", "HEAD"]
    assert resolver.calls == ["env:S3_ACCESS_KEY", "env:S3_SECRET_KEY"]
    assert "secret-sentinel-value" not in repr(store)


def test_s3_object_store_supports_virtual_hosted_style_without_leaking_secret() -> None:
    """若 virtual-hosted-style 错把 bucket 放入 path 或泄漏 Secret，本测试应失败。"""

    from deeptutor.runtime.externalized_providers import S3CompatibleObjectStore

    requests: list[httpx.Request] = []
    payload = b"virtual hosted object"
    digest = hashlib.sha256(payload).hexdigest()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.host == "deeptutor-assets.storage.example"
        assert "secret-sentinel-value" not in request.headers.get("authorization", "")
        if request.method == "PUT":
            assert request.url.path == "/tenant-a/owner-a/file.txt"
            return httpx.Response(200, request=request)
        if request.method == "HEAD":
            assert request.url.path == "/tenant-a/owner-a/file.txt"
            return httpx.Response(
                200,
                headers={"content-length": str(len(payload)), "x-amz-meta-sha256": digest},
                request=request,
            )
        raise AssertionError(f"unexpected request: {request.method}")

    store = S3CompatibleObjectStore(
        _config(path_style=False),
        secret_resolver=RecordingResolver(
            {"S3_ACCESS_KEY": "access-id", "S3_SECRET_KEY": "secret-sentinel-value"}
        ),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    ref = store.put_bytes("tenant-a/owner-a/file.txt", payload, expected_sha256=digest)

    assert ref.key == "tenant-a/owner-a/file.txt"
    assert [request.method for request in requests] == ["PUT", "HEAD"]


@pytest.mark.parametrize(
    ("status", "want_code"),
    [
        (404, "objectstore_bucket_missing"),
        (403, "objectstore_permission_denied"),
    ],
)
def test_s3_object_store_maps_provider_errors_without_leaking_secret(
    status: int, want_code: str
) -> None:
    """若 S3 错误把响应正文或 Secret 泄漏给调用方，本测试应失败。"""

    from deeptutor.runtime.externalized_providers import ObjectStoreError, S3CompatibleObjectStore

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="secret-sentinel-value", request=request)

    store = S3CompatibleObjectStore(
        _config(),
        secret_resolver=RecordingResolver(
            {"S3_ACCESS_KEY": "access-id", "S3_SECRET_KEY": "secret-sentinel-value"}
        ),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(ObjectStoreError) as error:
        store.put_bytes("tenant-a/owner-a/file.txt", b"payload")

    assert error.value.code == want_code
    assert "secret-sentinel-value" not in str(error.value)
    assert "storage.example" not in str(error.value)


def test_s3_object_store_retries_network_errors_and_redacts_failure() -> None:
    """若临时网络中断不可重试或最终错误泄漏 Secret，本测试应失败。"""

    from deeptutor.runtime.externalized_providers import ObjectStoreError, S3CompatibleObjectStore

    attempts = 0
    digest = hashlib.sha256(b"payload").hexdigest()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("secret-sentinel-value", request=request)
        return httpx.Response(
            200,
            headers={"content-length": "7", "x-amz-meta-sha256": digest},
            request=request,
        )

    store = S3CompatibleObjectStore(
        _config(max_retries=1),
        secret_resolver=RecordingResolver(
            {"S3_ACCESS_KEY": "access-id", "S3_SECRET_KEY": "secret-sentinel-value"}
        ),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    ref = store.put_bytes("tenant-a/owner-a/file.txt", b"payload", expected_sha256=digest)

    assert ref.sha256 == digest
    assert attempts == 3  # failed PUT, retried PUT, then HEAD verify

    always_down = S3CompatibleObjectStore(
        _config(max_retries=1),
        secret_resolver=RecordingResolver(
            {"S3_ACCESS_KEY": "access-id", "S3_SECRET_KEY": "secret-sentinel-value"}
        ),
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: (_ for _ in ()).throw(
                    httpx.ConnectError("secret-sentinel-value", request=request)
                )
            )
        ),
    )
    with pytest.raises(ObjectStoreError) as error:
        always_down.put_bytes("tenant-a/owner-a/file.txt", b"payload")
    assert error.value.code == "objectstore_unreachable"
    assert error.value.retryable is True
    assert "secret-sentinel-value" not in str(error.value)


def test_s3_object_store_detects_remote_hash_mismatch() -> None:
    """若远端返回的对象 hash 与本地上传内容不一致，本测试应失败。"""

    from deeptutor.runtime.externalized_providers import ObjectStoreError, S3CompatibleObjectStore

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            return httpx.Response(200, request=request)
        return httpx.Response(
            200,
            headers={"content-length": "7", "x-amz-meta-sha256": "0" * 64},
            request=request,
        )

    store = S3CompatibleObjectStore(
        _config(),
        secret_resolver=RecordingResolver(
            {"S3_ACCESS_KEY": "access-id", "S3_SECRET_KEY": "secret-sentinel-value"}
        ),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(ObjectStoreError) as error:
        store.put_bytes("tenant-a/owner-a/file.txt", b"payload")

    assert error.value.code == "objectstore_hash_mismatch"
    assert "secret-sentinel-value" not in str(error.value)


def test_s3_object_store_check_bucket_uses_head_bucket_and_redacted_status() -> None:
    """若 readiness 检查访问对象 key 或泄漏 endpoint/Secret，本测试应失败。"""

    from deeptutor.runtime.externalized_providers import S3CompatibleObjectStore

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "HEAD"
        assert request.url.path == "/deeptutor-assets"
        return httpx.Response(200, request=request)

    store = S3CompatibleObjectStore(
        _config(),
        secret_resolver=RecordingResolver(
            {"S3_ACCESS_KEY": "access-id", "S3_SECRET_KEY": "secret-sentinel-value"}
        ),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    status = store.check_bucket()

    assert status.available is True
    assert status.code == "objectstore_ready"
    assert status.bucket == "deeptutor-assets"
    assert "secret-sentinel-value" not in status.safe_summary()
    assert "storage.example" not in status.safe_summary()
    assert len(requests) == 1


def test_s3_object_store_check_bucket_reports_missing_secret_without_http_or_plaintext(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """若 readiness 在 Secret 缺失时继续联网或泄漏引用细节，本测试应失败。"""

    from deeptutor.runtime.externalized_providers import EnvSecretResolver, S3CompatibleObjectStore

    monkeypatch.delenv("S3_ACCESS_KEY", raising=False)
    monkeypatch.delenv("S3_SECRET_KEY", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"missing credentials must fail before HTTP: {request.method}")

    store = S3CompatibleObjectStore(
        _config(),
        secret_resolver=EnvSecretResolver(),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    status = store.check_bucket()

    assert status.available is False
    assert status.code == "objectstore_credentials_missing"
    assert "S3_ACCESS_KEY" not in status.safe_summary()
    assert "S3_SECRET_KEY" not in status.safe_summary()


def test_s3_object_store_put_fails_closed_when_secret_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """若对象写入把 SecretResolver 异常透出为非 ObjectStore 错误，本测试应失败。"""

    from deeptutor.runtime.externalized_providers import (
        EnvSecretResolver,
        ObjectStoreError,
        S3CompatibleObjectStore,
    )

    monkeypatch.delenv("S3_ACCESS_KEY", raising=False)
    monkeypatch.delenv("S3_SECRET_KEY", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"missing credentials must fail before HTTP: {request.method}")

    store = S3CompatibleObjectStore(
        _config(),
        secret_resolver=EnvSecretResolver(),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(ObjectStoreError) as error:
        store.put_bytes("tenant-a/owner-a/file.txt", b"payload")

    assert error.value.code == "objectstore_credentials_missing"
    assert "S3_ACCESS_KEY" not in str(error.value)
    assert "S3_SECRET_KEY" not in str(error.value)


@pytest.mark.integration
def test_s3_object_store_round_trips_against_s3_compatible_endpoint() -> None:
    """若 SigV4、path-style、SecretResolver 或 hash 校验无法与真实 S3-compatible 端点互通，本测试应失败。"""

    if os.environ.get("DEEPTUTOR_RUN_S3_COMPATIBLE_TESTS") != "1":
        pytest.skip("set DEEPTUTOR_RUN_S3_COMPATIBLE_TESTS=1 to run S3-compatible smoke")
    if not os.environ.get("DEEPTUTOR_TEST_S3_ACCESS_KEY") or not os.environ.get(
        "DEEPTUTOR_TEST_S3_SECRET_KEY"
    ):
        pytest.skip("S3-compatible smoke credential references are not configured")

    from deeptutor.runtime.externalized_providers import (
        EnvSecretResolver,
        S3CompatibleObjectStore,
        S3ObjectStoreConfig,
    )

    endpoint = os.environ.get("DEEPTUTOR_TEST_S3_ENDPOINT", "http://127.0.0.1:9000")
    bucket = os.environ.get("DEEPTUTOR_TEST_S3_BUCKET", "local-debug")

    store = S3CompatibleObjectStore(
        S3ObjectStoreConfig.from_environment(
            {
                "DEEPTUTOR_OBJECTSTORE_ENDPOINT": endpoint,
                "DEEPTUTOR_OBJECTSTORE_REGION": os.environ.get(
                    "DEEPTUTOR_TEST_S3_REGION", "us-east-1"
                ),
                "DEEPTUTOR_OBJECTSTORE_BUCKET": bucket,
                "DEEPTUTOR_OBJECTSTORE_ACCESS_KEY_REF": "env:DEEPTUTOR_TEST_S3_ACCESS_KEY",
                "DEEPTUTOR_OBJECTSTORE_SECRET_KEY_REF": "env:DEEPTUTOR_TEST_S3_SECRET_KEY",
                "DEEPTUTOR_OBJECTSTORE_PATH_STYLE": os.environ.get(
                    "DEEPTUTOR_TEST_S3_PATH_STYLE", "true"
                ),
                "DEEPTUTOR_OBJECTSTORE_TIMEOUT_SECONDS": "3.0",
                "DEEPTUTOR_OBJECTSTORE_MAX_RETRIES": "1",
            }
        ),
        secret_resolver=EnvSecretResolver(),
    )

    status = store.check_bucket()
    assert status.available is True, status.safe_summary()

    payload = f"deeptutor s3-compatible smoke {uuid.uuid4()}".encode()
    digest = hashlib.sha256(payload).hexdigest()
    key = f"local-debug/deeptutor-s3-provider/{uuid.uuid4().hex}.txt"

    ref = store.put_bytes(
        key,
        payload,
        expected_sha256=digest,
        content_type="text/plain; charset=utf-8",
    )
    try:
        assert ref.key == key
        assert ref.size_bytes == len(payload)
        assert ref.sha256 == digest
        assert store.get_bytes(ref) == payload
    finally:
        store.delete(ref)
