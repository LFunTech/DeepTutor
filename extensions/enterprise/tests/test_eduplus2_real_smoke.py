"""EduPlus2 真实测试环境 smoke。

默认跳过；只有显式设置 DT_EDUPLUS2_REAL_SMOKE=1 且环境变量齐备时才访问外部服务。
测试不得打印 token、client secret 或完整上游响应。
"""

from __future__ import annotations

import os
import uuid

from deeptutor_enterprise.eduplus2.client import EduPlus2OidcJwtVerifier, EduPlus2ResolveClient
import httpx
import pytest

pytestmark = pytest.mark.asyncio


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.skip(f"missing {name}")
    return value


def _secret(reference: str) -> str:
    if not reference.startswith("env:"):
        pytest.skip("EduPlus2 client secret must be provided as env: reference")
    return _env(reference[4:])


async def test_real_eduplus2_discovery_m2m_resolve_smoke():
    """防止 B1-lite 只通过 mock；真实环境需 discovery/token/resolve 正负例可用。"""

    if os.environ.get("DT_EDUPLUS2_REAL_SMOKE") != "1":
        pytest.skip("set DT_EDUPLUS2_REAL_SMOKE=1 to run real EduPlus2 smoke")

    discovery_url = _env("DT_EDUPLUS2_DISCOVERY_URL")
    issuer = os.environ.get("DT_EDUPLUS2_OIDC_ISSUER", "").strip() or None
    token_url = _env("DT_EDUPLUS2_TOKEN_ENDPOINT")
    base_url = os.environ.get("DT_EDUPLUS2_BASE_URL", "").rstrip("/")
    resolve_url = os.environ.get("DT_EDUPLUS2_RESOLVE_URL", "").strip()
    if not resolve_url and base_url:
        resolve_url = base_url + "/api/v1/open/oauth-clients/resolve"
    if not resolve_url:
        pytest.skip("missing DT_EDUPLUS2_RESOLVE_URL or DT_EDUPLUS2_BASE_URL")
    client_id = _env("DT_EDUPLUS2_CLIENT_ID")
    secret_ref = os.environ.get("DT_EDUPLUS2_CLIENT_SECRET_REF", "env:DT_EDUPLUS2_CLIENT_SECRET")
    client_secret = _secret(secret_ref)

    async with httpx.AsyncClient(timeout=10) as http_client:
        verifier = EduPlus2OidcJwtVerifier(
            discovery_url=discovery_url,
            issuer=issuer,
            jwks_uri=os.environ.get("DT_EDUPLUS2_JWKS_URI", "").strip() or None,
            http_client=http_client,
        )
        # 加载 discovery/JWKS 即可验证 OIDC 元数据链路；无真实 user JWT 时不伪造 exchange。
        await verifier.warmup()

        client = EduPlus2ResolveClient(
            token_url=token_url,
            resolve_url=resolve_url,
            client_id=client_id,
            client_secret=client_secret,
            http_client=http_client,
        )
        resolved = await client.resolve_client(client_id)
        assert resolved["client_id"] == client_id
        assert resolved["external_tenant_id"]
        assert resolved["external_app_id"]

        with pytest.raises(PermissionError):
            await client.resolve_client("missing-" + uuid.uuid4().hex)

        actual_tenant_id = str(resolved["external_tenant_id"])
        if actual_tenant_id.isdigit():
            wrong_tenant_id = int(actual_tenant_id) + 1
        else:
            try:
                uuid.UUID(actual_tenant_id)
                wrong_tenant_id = str(uuid.uuid4())
            except ValueError:
                wrong_tenant_id = actual_tenant_id + "-mismatch"
        with pytest.raises(PermissionError):
            await client.resolve_client(client_id, expected_tenant_id=wrong_tenant_id)
