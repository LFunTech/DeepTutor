"""Deprecated PocketBase runtime client.

PG-only runtime no longer enables PocketBase as a business backend.  Historical
PocketBase data is handled by the controlled offline exporter/importer under
``deeptutor.persistence.postgres.offline_import``; runtime code must not create
PocketBase clients or validate PocketBase tokens.
"""

from __future__ import annotations

import logging
from typing import Any

from deeptutor.services.config import load_integrations_settings

logger = logging.getLogger(__name__)

_client = None
_client_initialised = False
_client_key = ""

# Token validation cache: token -> (payload_dict, expires_at)
_TOKEN_CACHE: dict[str, tuple[dict[str, Any], float]] = {}
_TOKEN_CACHE_TTL: float = 60.0  # seconds


def is_pocketbase_enabled() -> bool:
    """PocketBase runtime backend is permanently disabled in PG-only mode."""
    return False


def _pocketbase_settings() -> dict[str, str]:
    settings = load_integrations_settings()
    return {
        "url": str(settings["pocketbase_url"]).rstrip("/"),
        "admin_email": str(settings["pocketbase_admin_email"]),
        "admin_password": str(settings["pocketbase_admin_password"]),
    }


def get_pb_client():
    """
    Return an admin-authenticated PocketBase SDK client (cached singleton).

    Raises RuntimeError if integrations.pocketbase_url is not set.
    Raises on authentication failure.
    """
    raise RuntimeError(
        "PostgreSQL-only runtime no longer supports PocketBase as a business "
        "backend. Use PostgreSQL for runtime state; legacy PocketBase data must "
        "be handled by the controlled offline export/import tools."
    )


def validate_pb_token(token: str) -> dict[str, Any] | None:
    """
    Validate a PocketBase user token and return the user payload dict.

    Uses PocketBase's /api/collections/users/auth-refresh endpoint.
    Results are cached for ``_TOKEN_CACHE_TTL`` seconds so only the
    first call per token per minute makes a network round-trip.

    Returns a dict with at least ``username`` and ``role`` keys, or
    None if the token is invalid / expired.
    """
    return None


async def ping_pocketbase() -> bool:
    """
    Async health check called during FastAPI lifespan startup.

    Returns True if PocketBase is reachable, False otherwise.
    Logs a clear warning (not an exception) so the server still starts
    when PocketBase is configured but temporarily unavailable.
    """
    return False
