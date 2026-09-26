"""OMS 平台主体不能复用租户换票，也不能从 JWT 角色派生业务权限。"""

from __future__ import annotations

import base64
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import httpx
from jose import jwt
import pytest

pytestmark = pytest.mark.asyncio

ISSUER = "https://eduplus-auth.test/realms/eduplus"
DISCOVERY = ISSUER + "/.well-known/openid-configuration"
AUDIENCE = "deeptutor-oms"
CLIENT_ID = "deeptutor-oms-web"


def _b64url_uint(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


@pytest.fixture
def oidc_fixture():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = key.public_key().public_numbers()
    public_jwk = {
        "kty": "RSA",
        "kid": "oms-test-kid",
        "use": "sig",
        "alg": "RS256",
        "n": _b64url_uint(numbers.n),
        "e": _b64url_uint(numbers.e),
    }
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )

    def token(**overrides):
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "azp": CLIENT_ID,
            "sub": "platform-user-123",
            "typ": "Bearer",
            "iat": now,
            "nbf": now - 1,
            "exp": now + 600,
            "realm_access": {"roles": ["platform_admin"]},
        }
        claims.update(overrides)
        return jwt.encode(claims, private_pem, algorithm="RS256", headers={"kid": "oms-test-kid"})

    async def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == DISCOVERY:
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "jwks_uri": ISSUER + "/protocol/openid-connect/certs",
                    "id_token_signing_alg_values_supported": ["RS256"],
                },
            )
        if request.url.path.endswith("/protocol/openid-connect/certs"):
            return httpx.Response(200, json={"keys": [public_jwk]})
        return httpx.Response(404)

    return token, handler


async def test_platform_token_is_verified_without_tenant_exchange_claims(oidc_fixture):
    from deeptutor_enterprise.oms.identity import PlatformOidcJwtVerifier

    token, handler = oidc_fixture
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        verifier = PlatformOidcJwtVerifier(
            discovery_url=DISCOVERY,
            issuer=ISSUER,
            audience=AUDIENCE,
            client_id=CLIENT_ID,
            http_client=client,
        )
        value = token(tid=None, eui=None)
        identity = await verifier.verify(value)

    assert identity.subject == "platform-user-123"
    assert identity.client_id == CLIENT_ID
    assert identity.token_hash and value not in identity.token_hash
    assert not hasattr(identity, "roles")
    assert not hasattr(identity, "permissions")
    assert not hasattr(identity, "tenant_id")


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "deeptutor-tenant"},
        {"azp": "other-client"},
        {"iss": ISSUER + "/other"},
        {"sub": ""},
        {"typ": "ID"},
        {"iat": int(time.time()) + 3600},
    ],
)
async def test_platform_verifier_rejects_wrong_identity_contract(oidc_fixture, overrides):
    from deeptutor_enterprise.oms.identity import PlatformOidcJwtVerifier

    token, handler = oidc_fixture
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        verifier = PlatformOidcJwtVerifier(
            discovery_url=DISCOVERY,
            issuer=ISSUER,
            audience=AUDIENCE,
            client_id=CLIENT_ID,
            http_client=client,
        )
        with pytest.raises(PermissionError):
            await verifier.verify(token(**overrides))


async def test_platform_verifier_rejects_tampered_signature(oidc_fixture):
    from deeptutor_enterprise.oms.identity import PlatformOidcJwtVerifier

    token, handler = oidc_fixture
    signed = token()
    body = signed.split(".")
    changed = body[0] + "." + body[1] + "." + ("A" if body[2][0] != "A" else "B") + body[2][1:]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        verifier = PlatformOidcJwtVerifier(
            discovery_url=DISCOVERY,
            issuer=ISSUER,
            audience=AUDIENCE,
            client_id=CLIENT_ID,
            http_client=client,
        )
        with pytest.raises(PermissionError):
            await verifier.verify(changed)


async def test_platform_verifier_rejects_symmetric_algorithm(oidc_fixture):
    from deeptutor_enterprise.oms.identity import PlatformOidcJwtVerifier

    _, handler = oidc_fixture
    now = int(time.time())
    forged = jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "azp": CLIENT_ID,
            "sub": "platform-user-123",
            "typ": "Bearer",
            "iat": now,
            "exp": now + 600,
        },
        "attacker-secret",
        algorithm="HS256",
        headers={"kid": "oms-test-kid"},
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        verifier = PlatformOidcJwtVerifier(
            discovery_url=DISCOVERY,
            issuer=ISSUER,
            audience=AUDIENCE,
            client_id=CLIENT_ID,
            http_client=client,
        )
        with pytest.raises(PermissionError):
            await verifier.verify(forged)


async def test_platform_verifier_requires_https_and_same_origin_jwks(oidc_fixture):
    from deeptutor_enterprise.oms.identity import PlatformOidcJwtVerifier

    token, _ = oidc_fixture
    with pytest.raises(ValueError, match="HTTPS"):
        PlatformOidcJwtVerifier(
            discovery_url="http://eduplus-auth.test/discovery",
            issuer=ISSUER,
            audience=AUDIENCE,
            client_id=CLIENT_ID,
        )

    async def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == DISCOVERY:
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "jwks_uri": "https://attacker.example/jwks",
                    "id_token_signing_alg_values_supported": ["RS256"],
                },
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        verifier = PlatformOidcJwtVerifier(
            discovery_url=DISCOVERY,
            issuer=ISSUER,
            audience=AUDIENCE,
            client_id=CLIENT_ID,
            http_client=client,
        )
        with pytest.raises(PermissionError, match="JWKS"):
            await verifier.verify(token())
