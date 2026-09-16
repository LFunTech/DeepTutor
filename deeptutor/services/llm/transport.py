"""Fail-closed transport policy for managed LLM execution.

Enterprise/default PostgreSQL runtimes resolve model credentials from controlled
Secret references.  This small value object keeps the transport-related policy
beside the LLM package rather than letting enterprise code reach into provider
internals or ambient process configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from urllib.parse import urlsplit

_AMBIENT_HEADER_ENV_VARS = (
    "OPENAI_CUSTOM_HEADERS",
    "OPENAI_EXTRA_HEADERS",
    "ANTHROPIC_CUSTOM_HEADERS",
)


@dataclass(frozen=True)
class LLMTransportConfig:
    """Validated per-deployment LLM transport limits."""

    request_timeout_seconds: float = 90.0
    connect_timeout_seconds: float = 10.0
    max_retries: int = 0
    disable_ssl_verify: bool = False

    def validate_environment(self, *, backend: str) -> None:
        """Reject ambient credentials/headers that bypass deployment config."""

        _ = backend
        for name in _AMBIENT_HEADER_ENV_VARS:
            if os.environ.get(name):
                raise RuntimeError("ambient LLM transport headers are not allowed")
        if self.request_timeout_seconds <= 0 or self.connect_timeout_seconds <= 0:
            raise RuntimeError("LLM transport timeouts must be positive")
        if self.max_retries < 0:
            raise RuntimeError("LLM transport retry budget must be non-negative")
        if self.disable_ssl_verify and os.getenv("ENVIRONMENT", "").strip().lower() in {
            "prod",
            "production",
        }:
            raise RuntimeError("LLM transport may not disable TLS verification in production")

    def validate_provider(self, *, backend: str, api_key: str, base_url: str) -> None:
        """Validate resolved Secret-backed provider fields without leaking values."""

        if not api_key:
            raise RuntimeError("required LLM Secret is unavailable")
        parsed = urlsplit(base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise RuntimeError("LLM provider endpoint must be HTTPS")
        self.validate_environment(backend=backend)


__all__ = ["LLMTransportConfig"]
