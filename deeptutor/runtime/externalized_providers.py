"""Core seams for externalized runtime data providers.

This module defines provider-neutral contracts used by the Kubernetes runtime
work.  Implementations here are deliberately local-dev only or reference-only;
production ObjectStore/Settings providers are wired in later slices and must not
silently fall back to these local helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import hmac
import os
from pathlib import Path
import re
import time
from typing import Any, Mapping, Protocol
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

import httpx

from deeptutor.persistence.postgres.configuration import SecretValue
from deeptutor.runtime.data_gate import RuntimeMode

_SECRET_REF = re.compile(r"env:[A-Za-z_][A-Za-z0-9_]*\Z")
_SAFE_KEY_PART = re.compile(r"[A-Za-z0-9._=@+-]+\Z")
_BUCKET = re.compile(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]\Z")
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


class ProviderModeError(RuntimeError):
    """A local-dev provider was requested in production/Kubernetes mode."""


class SecretResolutionError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class ObjectStoreError(RuntimeError):
    """Stable, redacted object-store error."""

    def __init__(self, code: str, *, retryable: bool = False, status_code: int | None = None):
        self.code = code
        self.retryable = retryable
        self.status_code = status_code
        super().__init__(code)


class SecretResolverProtocol(Protocol):
    def resolve(self, ref: "SecretRef") -> SecretValue: ...


@dataclass(frozen=True)
class SecretRef:
    provider: str
    name: str
    version: str = ""

    @classmethod
    def parse(cls, value: object) -> "SecretRef":
        if not isinstance(value, str) or not _SECRET_REF.fullmatch(value):
            raise ValueError("secret reference is required")
        return cls(provider="env", name=value[4:])

    def safe_label(self) -> str:
        return f"{self.provider}:{self.name}" + (f"@{self.version}" if self.version else "")


class EnvSecretResolver:
    """Resolve ``env:NAME`` references without ever storing plaintext in config."""

    def resolve(self, ref: SecretRef) -> SecretValue:
        if ref.provider != "env":
            raise SecretResolutionError("secret_provider_unsupported")
        value = os.environ.get(ref.name)
        if not value:
            raise SecretResolutionError("secret_missing")
        return SecretValue(value)

    def safe_status(self, ref: SecretRef) -> str:
        if ref.provider != "env":
            return f"{ref.safe_label()}:unsupported"
        return f"{ref.safe_label()}:" + ("configured" if os.environ.get(ref.name) else "missing")


@dataclass(frozen=True)
class ObjectBlobRef:
    key: str
    size_bytes: int
    sha256: str
    content_type: str = "application/octet-stream"


@dataclass(frozen=True)
class PresignedUpload:
    url: str
    headers: dict[str, str]
    expires_seconds: int


@dataclass(frozen=True)
class ObjectStoreStatus:
    provider: str
    bucket: str
    available: bool
    code: str
    retryable: bool = False

    def safe_summary(self) -> str:
        state = "available" if self.available else "unavailable"
        return f"{self.provider}:{self.bucket}:{state}:{self.code}"


@dataclass(frozen=True)
class ResourceHandle:
    """User-visible resource metadata; never a filesystem authorization."""

    tenant_id: str
    owner_id: str
    resource_kind: str
    resource_id: str
    object_id: str
    version: int
    state: str
    size_bytes: int
    sha256: str
    mime_type: str


class LocalDevObjectStore:
    """Filesystem-backed ObjectStore test/dev helper.

    It is explicitly disabled in production/Kubernetes mode so it cannot become
    a PVC-shaped replacement for the required S3-compatible provider.
    """

    def __init__(self, root: str | Path, *, mode: RuntimeMode | None = None) -> None:
        self.mode = mode or RuntimeMode.from_environ()
        if self.mode.production:
            raise ProviderModeError("local object store is disabled in production runtime")
        self.root = Path(root).resolve()

    def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        expected_sha256: str | None = None,
        content_type: str = "application/octet-stream",
    ) -> ObjectBlobRef:
        safe_key = self._safe_key(key)
        digest = hashlib.sha256(data).hexdigest()
        if expected_sha256 is not None and digest != expected_sha256:
            raise ValueError("object hash mismatch")
        target = (self.root / safe_key).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        tmp.write_bytes(data)
        tmp.replace(target)
        return ObjectBlobRef(
            key=safe_key.as_posix(),
            size_bytes=len(data),
            sha256=digest,
            content_type=content_type,
        )

    def get_bytes(self, ref: ObjectBlobRef) -> bytes:
        return (self.root / self._safe_key(ref.key)).read_bytes()

    def delete(self, ref: ObjectBlobRef) -> None:
        try:
            (self.root / self._safe_key(ref.key)).unlink()
        except FileNotFoundError:
            return

    def _safe_key(self, key: str) -> Path:
        path = Path(key)
        if path.is_absolute() or not path.parts:
            raise ValueError("object key must be a relative path")
        parts: list[str] = []
        for part in path.parts:
            if part in {"", ".", ".."} or not _SAFE_KEY_PART.fullmatch(part):
                raise ValueError("invalid object key")
            parts.append(part)
        return Path(*parts)


@dataclass(frozen=True)
class S3ObjectStoreConfig:
    endpoint: str
    region: str
    bucket: str
    access_key_ref: SecretRef
    secret_key_ref: SecretRef
    session_token_ref: SecretRef | None = None
    path_style: bool = True
    verify_tls: bool = True
    server_side_encryption: str = ""
    timeout_seconds: float = 10.0
    max_retries: int = 2
    retry_backoff_seconds: float = 0.05

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        prefix: str = "DEEPTUTOR_OBJECTSTORE_",
    ) -> "S3ObjectStoreConfig":
        source = os.environ if environ is None else environ

        def text(name: str, *, required: bool = False, default: str = "") -> str:
            value = str(source.get(prefix + name) or "").strip()
            if required and not value:
                raise ValueError("object store environment configuration is incomplete")
            return value or default

        def flag(name: str, *, default: bool) -> bool:
            raw = text(name).lower()
            if not raw:
                return default
            if raw in {"1", "true", "yes", "on"}:
                return True
            if raw in {"0", "false", "no", "off"}:
                return False
            raise ValueError("object store boolean environment configuration is invalid")

        def number(name: str, *, default: float) -> float:
            raw = text(name)
            if not raw:
                return default
            try:
                return float(raw)
            except ValueError:
                raise ValueError("object store numeric environment configuration is invalid") from None

        def integer(name: str, *, default: int) -> int:
            raw = text(name)
            if not raw:
                return default
            try:
                return int(raw)
            except ValueError:
                raise ValueError("object store numeric environment configuration is invalid") from None

        access_ref = text("ACCESS_KEY_REF", default=f"env:{prefix}ACCESS_KEY")
        secret_ref = text("SECRET_KEY_REF", default=f"env:{prefix}SECRET_KEY")
        session_ref = text("SESSION_TOKEN_REF")
        return cls(
            endpoint=text("ENDPOINT", required=True),
            region=text("REGION", required=True),
            bucket=text("BUCKET", required=True),
            access_key_ref=SecretRef.parse(access_ref),
            secret_key_ref=SecretRef.parse(secret_ref),
            session_token_ref=SecretRef.parse(session_ref) if session_ref else None,
            path_style=flag("PATH_STYLE", default=True),
            verify_tls=flag("VERIFY_TLS", default=True),
            server_side_encryption=text("SERVER_SIDE_ENCRYPTION"),
            timeout_seconds=number("TIMEOUT_SECONDS", default=10.0),
            max_retries=integer("MAX_RETRIES", default=2),
            retry_backoff_seconds=number("RETRY_BACKOFF_SECONDS", default=0.05),
        )

    def __post_init__(self) -> None:
        parts = urlsplit(self.endpoint)
        if parts.scheme not in {"http", "https"} or not parts.netloc or parts.username:
            raise ValueError("object store endpoint must be an http(s) origin")
        if parts.query or parts.fragment:
            raise ValueError("object store endpoint must not include query or fragment")
        if not _BUCKET.fullmatch(self.bucket):
            raise ValueError("object store bucket name is invalid")
        if not self.region:
            raise ValueError("object store region is required")
        if self.timeout_seconds <= 0 or self.max_retries < 0 or self.retry_backoff_seconds < 0:
            raise ValueError("object store timeout/retry settings are invalid")

    @property
    def origin(self) -> str:
        parts = urlsplit(self.endpoint)
        return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


@dataclass(frozen=True)
class _S3Credentials:
    access_key: str
    secret_key: str
    session_token: str = ""


class S3CompatibleObjectStore:
    """Minimal S3-compatible ObjectStore provider with SigV4 signing."""

    def __init__(
        self,
        config: S3ObjectStoreConfig,
        *,
        secret_resolver: SecretResolverProtocol,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.config = config
        self._secret_resolver = secret_resolver
        self._credentials: _S3Credentials | None = None
        self._client = http_client or httpx.Client(
            timeout=config.timeout_seconds,
            verify=config.verify_tls,
        )

    def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        expected_sha256: str | None = None,
        content_type: str = "application/octet-stream",
    ) -> ObjectBlobRef:
        safe_key = self._safe_key(key)
        digest = hashlib.sha256(data).hexdigest()
        if expected_sha256 is not None and digest != expected_sha256:
            raise ObjectStoreError("objectstore_hash_mismatch")
        headers = {
            "content-type": content_type,
            "content-length": str(len(data)),
            "x-amz-meta-sha256": digest,
        }
        if self.config.server_side_encryption:
            headers["x-amz-server-side-encryption"] = self.config.server_side_encryption
        self._request("PUT", safe_key, data, headers=headers, payload_sha256=digest)
        self._verify_remote_object(safe_key, expected_size=len(data), expected_sha256=digest)
        return ObjectBlobRef(
            key=safe_key,
            size_bytes=len(data),
            sha256=digest,
            content_type=content_type,
        )

    def get_bytes(self, ref: ObjectBlobRef) -> bytes:
        response = self._request("GET", self._safe_key(ref.key), b"")
        data = response.content
        if len(data) != ref.size_bytes or hashlib.sha256(data).hexdigest() != ref.sha256:
            raise ObjectStoreError("objectstore_hash_mismatch")
        return data

    def delete(self, ref: ObjectBlobRef) -> None:
        self._request("DELETE", self._safe_key(ref.key), b"")

    def presign_put(
        self,
        key: str,
        *,
        expires_seconds: int,
        content_type: str = "application/octet-stream",
        size_bytes: int | None = None,
        expected_sha256: str | None = None,
    ) -> PresignedUpload:
        safe_key = self._safe_key(key)
        expires = max(1, min(int(expires_seconds), 3600))
        headers = {"content-type": str(content_type or "application/octet-stream")}
        if size_bytes is not None:
            headers["content-length"] = str(max(0, int(size_bytes)))
        if expected_sha256:
            headers["x-amz-meta-sha256"] = str(expected_sha256)
        if self.config.server_side_encryption:
            headers["x-amz-server-side-encryption"] = self.config.server_side_encryption
        url = self._presigned_url(
            "PUT",
            safe_key,
            self._url_for_key(safe_key),
            self._canonical_uri(safe_key),
            headers=headers,
            expires_seconds=expires,
        )
        return PresignedUpload(url=url, headers=headers, expires_seconds=expires)

    def head_object(self, key: str) -> ObjectBlobRef:
        safe_key = self._safe_key(key)
        response = self._request("HEAD", safe_key, b"")
        try:
            size = int(response.headers.get("content-length", "-1"))
        except ValueError:
            size = -1
        return ObjectBlobRef(
            key=safe_key,
            size_bytes=size,
            sha256=response.headers.get("x-amz-meta-sha256", ""),
            content_type=response.headers.get("content-type", "application/octet-stream"),
        )

    def check_bucket(self) -> ObjectStoreStatus:
        try:
            self._request_bucket("HEAD")
        except ObjectStoreError as exc:
            return ObjectStoreStatus(
                provider="s3",
                bucket=self.config.bucket,
                available=False,
                code=exc.code,
                retryable=exc.retryable,
            )
        return ObjectStoreStatus(
            provider="s3",
            bucket=self.config.bucket,
            available=True,
            code="objectstore_ready",
        )

    def _verify_remote_object(self, key: str, *, expected_size: int, expected_sha256: str) -> None:
        response = self._request("HEAD", key, b"")
        try:
            actual_size = int(response.headers.get("content-length", "-1"))
        except ValueError:
            actual_size = -1
        actual_sha256 = response.headers.get("x-amz-meta-sha256", "")
        if actual_size != expected_size:
            raise ObjectStoreError("objectstore_size_mismatch")
        if actual_sha256 != expected_sha256:
            raise ObjectStoreError("objectstore_hash_mismatch")

    def _request(
        self,
        method: str,
        key: str,
        payload: bytes,
        *,
        headers: dict[str, str] | None = None,
        payload_sha256: str | None = None,
    ) -> httpx.Response:
        body_hash = payload_sha256 or _EMPTY_SHA256
        return self._request_url(
            method,
            self._url_for_key(key),
            self._canonical_uri(key),
            payload,
            headers={"x-amz-content-sha256": body_hash, **(headers or {})},
            payload_sha256=body_hash,
        )

    def _request_bucket(self, method: str) -> httpx.Response:
        return self._request_url(
            method,
            self._url_for_bucket(),
            self._canonical_bucket_uri(),
            b"",
            headers={"x-amz-content-sha256": _EMPTY_SHA256},
            payload_sha256=_EMPTY_SHA256,
        )

    def _request_url(
        self,
        method: str,
        url: str,
        canonical_uri: str,
        payload: bytes,
        *,
        headers: dict[str, str],
        payload_sha256: str,
    ) -> httpx.Response:
        last_error: ObjectStoreError | None = None
        for attempt in range(self.config.max_retries + 1):
            signed_headers = self._signed_headers_for_url(
                method, url, canonical_uri, headers, payload_sha256
            )
            try:
                response = self._client.request(
                    method,
                    url,
                    headers=signed_headers,
                    content=payload if method not in {"GET", "HEAD", "DELETE"} else None,
                )
            except httpx.RequestError:
                last_error = ObjectStoreError("objectstore_unreachable", retryable=True)
                if attempt < self.config.max_retries:
                    self._sleep_before_retry(attempt)
                    continue
                raise last_error from None
            if response.status_code < 400:
                return response
            error = self._error_for_response(response)
            if error.retryable and attempt < self.config.max_retries:
                self._sleep_before_retry(attempt)
                continue
            raise error
        raise last_error or ObjectStoreError("objectstore_unreachable", retryable=True)

    def _sleep_before_retry(self, attempt: int) -> None:
        if self.config.retry_backoff_seconds:
            time.sleep(self.config.retry_backoff_seconds * (2**attempt))

    def _error_for_response(self, response: httpx.Response) -> ObjectStoreError:
        if response.status_code == 403:
            return ObjectStoreError("objectstore_permission_denied", status_code=403)
        if response.status_code == 404:
            return ObjectStoreError("objectstore_bucket_missing", status_code=404)
        if response.status_code in {408, 429} or response.status_code >= 500:
            return ObjectStoreError(
                "objectstore_unavailable",
                retryable=True,
                status_code=response.status_code,
            )
        return ObjectStoreError("objectstore_request_failed", status_code=response.status_code)

    def _credentials_for_request(self) -> _S3Credentials:
        if self._credentials is None:
            try:
                access = self._secret_resolver.resolve(self.config.access_key_ref).reveal()
                secret = self._secret_resolver.resolve(self.config.secret_key_ref).reveal()
                token = (
                    self._secret_resolver.resolve(self.config.session_token_ref).reveal()
                    if self.config.session_token_ref is not None
                    else ""
                )
            except SecretResolutionError:
                raise ObjectStoreError("objectstore_credentials_missing") from None
            if not access or not secret:
                raise ObjectStoreError("objectstore_credentials_missing")
            self._credentials = _S3Credentials(access, secret, token)
        return self._credentials

    def _presigned_url(
        self,
        method: str,
        key: str,
        url_value: str,
        canonical_uri: str,
        *,
        headers: dict[str, str],
        expires_seconds: int,
    ) -> str:
        credentials = self._credentials_for_request()
        now = datetime.now(UTC)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        url = httpx.URL(url_value)
        signing_headers = {k.lower(): str(v).strip() for k, v in headers.items()}
        signing_headers["host"] = (
            url.netloc.decode() if isinstance(url.netloc, bytes) else url.netloc
        )
        signed_headers = ";".join(sorted(signing_headers))
        scope = f"{date_stamp}/{self.config.region}/s3/aws4_request"
        query = {
            "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
            "X-Amz-Credential": f"{credentials.access_key}/{scope}",
            "X-Amz-Date": amz_date,
            "X-Amz-Expires": str(expires_seconds),
            "X-Amz-SignedHeaders": signed_headers,
        }
        if credentials.session_token:
            query["X-Amz-Security-Token"] = credentials.session_token
        canonical_query = urlencode(sorted(query.items()), quote_via=quote, safe="")
        canonical_headers = "".join(
            f"{name}:{signing_headers[name]}\n" for name in sorted(signing_headers)
        )
        canonical_request = "\n".join(
            [
                method,
                canonical_uri,
                canonical_query,
                canonical_headers,
                signed_headers,
                "UNSIGNED-PAYLOAD",
            ]
        )
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                scope,
                hashlib.sha256(canonical_request.encode()).hexdigest(),
            ]
        )
        signature = hmac.new(
            self._signing_key(credentials.secret_key, date_stamp, self.config.region),
            string_to_sign.encode(),
            hashlib.sha256,
        ).hexdigest()
        final_query = urlencode(
            sorted({**query, "X-Amz-Signature": signature}.items()),
            quote_via=quote,
            safe="",
        )
        parts = urlsplit(url_value)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, final_query, ""))

    def _signed_headers_for_url(
        self,
        method: str,
        url_value: str,
        canonical_uri: str,
        headers: dict[str, str],
        payload_sha256: str,
    ) -> dict[str, str]:
        credentials = self._credentials_for_request()
        now = datetime.now(UTC)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        url = httpx.URL(url_value)
        signing_headers = {k.lower(): str(v).strip() for k, v in headers.items()}
        signing_headers["host"] = (
            url.netloc.decode() if isinstance(url.netloc, bytes) else url.netloc
        )
        signing_headers["x-amz-date"] = amz_date
        if credentials.session_token:
            signing_headers["x-amz-security-token"] = credentials.session_token
        canonical_headers = "".join(
            f"{name}:{signing_headers[name]}\n" for name in sorted(signing_headers)
        )
        signed_headers = ";".join(sorted(signing_headers))
        canonical_request = "\n".join(
            [
                method,
                canonical_uri,
                "",
                canonical_headers,
                signed_headers,
                payload_sha256,
            ]
        )
        scope = f"{date_stamp}/{self.config.region}/s3/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                scope,
                hashlib.sha256(canonical_request.encode()).hexdigest(),
            ]
        )
        signature = hmac.new(
            self._signing_key(credentials.secret_key, date_stamp, self.config.region),
            string_to_sign.encode(),
            hashlib.sha256,
        ).hexdigest()
        outgoing = dict(headers)
        outgoing["host"] = signing_headers["host"]
        outgoing["x-amz-date"] = amz_date
        outgoing["authorization"] = (
            "AWS4-HMAC-SHA256 "
            f"Credential={credentials.access_key}/{scope},"
            f"SignedHeaders={signed_headers},Signature={signature}"
        )
        if credentials.session_token:
            outgoing["x-amz-security-token"] = credentials.session_token
        return outgoing

    @staticmethod
    def _signing_key(secret_key: str, date_stamp: str, region: str) -> bytes:
        date_key = hmac.new(
            ("AWS4" + secret_key).encode(),
            date_stamp.encode(),
            hashlib.sha256,
        ).digest()
        region_key = hmac.new(date_key, region.encode(), hashlib.sha256).digest()
        service_key = hmac.new(region_key, b"s3", hashlib.sha256).digest()
        return hmac.new(service_key, b"aws4_request", hashlib.sha256).digest()

    def _url_for_key(self, key: str) -> str:
        origin = self.config.origin
        encoded_key = "/".join(quote(part, safe="") for part in key.split("/"))
        if self.config.path_style:
            return f"{origin}/{self.config.bucket}/{encoded_key}"
        parts = urlsplit(origin)
        return urlunsplit(
            (
                parts.scheme,
                f"{self.config.bucket}.{parts.netloc}",
                f"/{encoded_key}",
                "",
                "",
            )
        )

    def _url_for_bucket(self) -> str:
        if self.config.path_style:
            return f"{self.config.origin}/{self.config.bucket}"
        parts = urlsplit(self.config.origin)
        return urlunsplit((parts.scheme, f"{self.config.bucket}.{parts.netloc}", "/", "", ""))

    def _canonical_bucket_uri(self) -> str:
        return f"/{self.config.bucket}" if self.config.path_style else "/"

    def _canonical_uri(self, key: str) -> str:
        encoded_key = "/".join(quote(part, safe="") for part in key.split("/"))
        if self.config.path_style:
            return f"/{self.config.bucket}/{encoded_key}"
        return f"/{encoded_key}"

    @staticmethod
    def _safe_key(key: str) -> str:
        path = Path(key)
        if path.is_absolute() or not path.parts:
            raise ValueError("object key must be a relative path")
        parts: list[str] = []
        for part in path.parts:
            if part in {"", ".", ".."} or not _SAFE_KEY_PART.fullmatch(part):
                raise ValueError("invalid object key")
            parts.append(part)
        return "/".join(parts)


@dataclass(frozen=True)
class SettingsRecord:
    tenant_id: str
    key: str
    version: int
    desired: dict[str, Any]
    active: dict[str, Any]
    status: str
    updated_by: str


class LocalDevSettingsProvider:
    """In-memory settings provider for local-dev tests and adapters."""

    def __init__(self, *, mode: RuntimeMode | None = None) -> None:
        self.mode = mode or RuntimeMode.from_environ()
        if self.mode.production:
            raise ProviderModeError("local settings provider is disabled in production runtime")
        self._records: dict[tuple[str, str], SettingsRecord] = {}

    def save(
        self,
        tenant_id: str,
        key: str,
        value: dict[str, Any],
        *,
        actor: str,
    ) -> SettingsRecord:
        if not tenant_id or not key:
            raise ValueError("tenant and settings key are required")
        current = self._records.get((tenant_id, key))
        record = SettingsRecord(
            tenant_id=tenant_id,
            key=key,
            version=(current.version + 1 if current else 1),
            desired=dict(value),
            active=dict(value),
            status="active",
            updated_by=str(actor or ""),
        )
        self._records[(tenant_id, key)] = record
        return record

    def load(self, tenant_id: str, key: str) -> SettingsRecord:
        try:
            return self._records[(tenant_id, key)]
        except KeyError:
            raise KeyError("settings record not found") from None


__all__ = [
    "EnvSecretResolver",
    "LocalDevObjectStore",
    "LocalDevSettingsProvider",
    "ObjectBlobRef",
    "ObjectStoreError",
    "ObjectStoreStatus",
    "S3CompatibleObjectStore",
    "S3ObjectStoreConfig",
    "ProviderModeError",
    "ResourceHandle",
    "SecretRef",
    "SecretResolutionError",
    "SettingsRecord",
]
