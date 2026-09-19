#!/usr/bin/env python3
"""EduPlus2 前置应用接入契约 smoke 入口。

默认 dry-run 只解析本地 `.secrets` 配置和 user JWT 结构，不发起网络请求；
`--real` 才访问 EduPlus2/DeepTutor。所有输出都必须保持脱敏。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any
from urllib import error, parse, request

DEFAULT_TOKEN_FILE = Path(".secrets/token-test.secrets")
DEFAULT_ENV_FILE = Path(".secrets/deeptutor-local-eduplus2.env")
DEFAULT_INCLUDE = ("tenant", "app", "policy")
REQUIRED_ENV_KEYS = (
    "DT_EDUPLUS2_DISCOVERY_URL",
    "DT_EDUPLUS2_TOKEN_ENDPOINT",
    "DT_EDUPLUS2_CLIENT_ID",
)
SENSITIVE_NAME_PARTS = ("TOKEN", "SECRET", "JWT", "AUTHORIZATION")


class SmokeError(RuntimeError):
    """可脱敏展示的 smoke 错误。"""


class SecretLeakError(SmokeError):
    """输出中出现了输入 secret 值。"""


def _parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[7:].lstrip()
    if "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    key = key.strip()
    value = value.strip()
    if not key:
        return None
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    return key, value


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        parsed = _parse_env_line(line)
        if parsed is not None:
            key, value = parsed
            values[key] = value
    return values


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def decode_jwt_unverified(token: str) -> tuple[dict[str, Any], dict[str, Any]]:
    parts = token.split(".")
    if len(parts) < 2:
        raise SmokeError("invalid_jwt_format")
    try:
        header = json.loads(_b64url_decode(parts[0]).decode("utf-8"))
        payload = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise SmokeError("invalid_jwt_encoding") from exc
    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise SmokeError("invalid_jwt_payload")
    return header, payload


def _sha256(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _bool_status(ok: bool) -> str:
    return "ok" if ok else "failed"


def _client_id(token_values: dict[str, str], env_values: dict[str, str]) -> str:
    return (
        env_values.get("DT_EDUPLUS2_CLIENT_ID")
        or token_values.get("ClientID")
        or token_values.get("CLIENT_ID")
        or ""
    ).strip()


def _client_secret(token_values: dict[str, str], env_values: dict[str, str]) -> str:
    return (
        env_values.get("DT_EDUPLUS2_CLIENT_SECRET")
        or token_values.get("ClientSecret")
        or token_values.get("CLIENT_SECRET")
        or ""
    )


def _resolve_url(env_values: dict[str, str]) -> str:
    explicit = env_values.get("DT_EDUPLUS2_RESOLVE_URL", "").strip()
    if explicit:
        return explicit
    base_url = env_values.get("DT_EDUPLUS2_BASE_URL", "").rstrip("/")
    if base_url:
        return base_url + "/api/v1/open/oauth-clients/resolve"
    return ""


def _secret_values(token_values: dict[str, str], env_values: dict[str, str]) -> list[str]:
    values: list[str] = []
    for source in (token_values, env_values):
        for key, value in source.items():
            if value and any(part in key.upper() for part in SENSITIVE_NAME_PARTS):
                values.append(value)
    return values


def _assert_no_secret_leak(rendered: str, secrets: list[str]) -> None:
    for value in secrets:
        if len(value) >= 8 and value in rendered:
            raise SecretLeakError("smoke output contains a configured secret value")


def build_configuration_step(
    *,
    token_file: Path,
    env_file: Path,
    token_values: dict[str, str],
    env_values: dict[str, str],
) -> dict[str, Any]:
    missing = [key for key in REQUIRED_ENV_KEYS if not env_values.get(key)]
    if not _resolve_url(env_values):
        missing.append("DT_EDUPLUS2_RESOLVE_URL or DT_EDUPLUS2_BASE_URL")
    if not _client_secret(token_values, env_values):
        missing.append("DT_EDUPLUS2_CLIENT_SECRET or ClientSecret")
    return {
        "status": _bool_status(not missing and token_file.exists() and env_file.exists()),
        "token_file_exists": token_file.exists(),
        "env_file_exists": env_file.exists(),
        "loaded_key_names": sorted(set(token_values) | set(env_values)),
        "missing_key_names": missing,
        "client_id_present": bool(_client_id(token_values, env_values)),
        "secret_values_printed": False,
    }


def build_user_jwt_step(token: str, *, expected_client_id: str, now: int | None = None) -> dict[str, Any]:
    now = int(time.time()) if now is None else int(now)
    if not token:
        return {
            "status": "missing",
            "valid_now": False,
            "azp_matches_client": False,
            "claims": {},
            "reason": "missing_user_jwt",
        }
    try:
        header, claims = decode_jwt_unverified(token)
    except SmokeError as exc:
        return {
            "status": "invalid",
            "valid_now": False,
            "azp_matches_client": False,
            "claims": {},
            "reason": str(exc),
        }
    exp = int(claims.get("exp") or 0)
    nbf = int(claims.get("nbf") or 0)
    iat = int(claims.get("iat") or 0)
    valid_now = bool(exp and exp > now and (not nbf or nbf <= now))
    azp = str(claims.get("azp") or "")
    azp_matches = bool(expected_client_id and azp == expected_client_id)
    status = "ok"
    reason = ""
    if not valid_now:
        status = "expired" if exp and exp <= now else "not_yet_valid"
        reason = status
    elif not azp_matches:
        status = "client_mismatch"
        reason = "azp_does_not_match_configured_client"
    return {
        "status": status,
        "valid_now": valid_now,
        "azp_matches_client": azp_matches,
        "claims": {
            "issuer": claims.get("iss") or "",
            "azp": azp,
            "kid": header.get("kid") or "",
            "alg": header.get("alg") or "",
            "tid_sha256": _sha256(claims.get("tid")),
            "eui_sha256": _sha256(claims.get("eui")),
            "sub_sha256": _sha256(claims.get("sub")),
            "iat": iat,
            "exp": exp,
            "seconds_until_expiry": max(0, exp - now) if exp else 0,
        },
        "reason": reason,
    }


def _http_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    req = request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with request.urlopen(req, timeout=timeout) as response:  # noqa: S310 - operator supplied smoke URL
            raw = response.read()
    except error.HTTPError as exc:
        raise SmokeError(f"http_{exc.code}") from None
    except error.URLError as exc:
        raise SmokeError("endpoint_unavailable") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise SmokeError("invalid_json_response") from exc
    if not isinstance(payload, dict):
        raise SmokeError("invalid_json_response")
    return payload


def run_discovery(env_values: dict[str, str]) -> dict[str, Any]:
    discovery_url = env_values.get("DT_EDUPLUS2_DISCOVERY_URL", "").strip()
    if not discovery_url:
        return {"status": "skipped", "reason": "missing_discovery_url"}
    try:
        discovery = _http_json(discovery_url, headers={"Accept": "application/json"})
        jwks_uri = env_values.get("DT_EDUPLUS2_JWKS_URI", "").strip() or str(
            discovery.get("jwks_uri") or ""
        )
        jwks = _http_json(jwks_uri, headers={"Accept": "application/json"}) if jwks_uri else {}
        keys = jwks.get("keys") if isinstance(jwks.get("keys"), list) else []
        return {
            "status": "ok",
            "issuer": discovery.get("issuer") or "",
            "jwks_key_count": len(keys),
        }
    except SmokeError as exc:
        return {"status": "failed", "reason": str(exc)}


def request_m2m_token(env_values: dict[str, str], client_secret: str) -> tuple[dict[str, Any], str]:
    token_url = env_values.get("DT_EDUPLUS2_TOKEN_ENDPOINT", "").strip()
    client_id = env_values.get("DT_EDUPLUS2_CLIENT_ID", "").strip()
    if not token_url or not client_id or not client_secret:
        return ({"status": "skipped", "reason": "missing_m2m_config"}, "")
    auth_raw = f"{client_id}:{client_secret}".encode("utf-8")
    auth = base64.b64encode(auth_raw).decode("ascii")
    body = parse.urlencode({"grant_type": "client_credentials"}).encode("utf-8")
    try:
        payload = _http_json(
            token_url,
            method="POST",
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": "Basic " + auth,
            },
        )
    except SmokeError as exc:
        return ({"status": "failed", "reason": str(exc)}, "")
    access_token = str(payload.get("access_token") or "")
    if not access_token:
        return ({"status": "failed", "reason": "missing_access_token"}, "")
    return (
        {
            "status": "ok",
            "token_received": True,
            "expires_in": int(payload.get("expires_in") or 0),
            "token_sha256": _sha256(access_token),
        },
        access_token,
    )


def run_resolve(env_values: dict[str, str], *, m2m_token: str, client_id: str) -> dict[str, Any]:
    resolve_url = _resolve_url(env_values)
    if not resolve_url or not m2m_token or not client_id:
        return {"status": "skipped", "reason": "missing_resolve_inputs"}
    body = json.dumps({"client_id": client_id, "include": list(DEFAULT_INCLUDE)}).encode("utf-8")
    try:
        payload = _http_json(
            resolve_url,
            method="POST",
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": "Bearer " + m2m_token,
            },
        )
    except SmokeError as exc:
        return {"status": "failed", "reason": str(exc)}
    code = payload.get("code")
    if code not in (None, 0, "0"):
        return {"status": "failed", "reason": "resolve_rejected"}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    client = data.get("client") if isinstance(data.get("client"), dict) else data
    tenant = data.get("tenant") if isinstance(data.get("tenant"), dict) else data
    app = data.get("app") if isinstance(data.get("app"), dict) else data
    return {
        "status": "ok" if data.get("verified", payload.get("verified", True)) else "failed",
        "client_id": client.get("client_id") or client.get("id") or client_id,
        "external_tenant_sha256": _sha256(
            tenant.get("id") or tenant.get("tenant_id") or tenant.get("external_tenant_id")
        ),
        "external_app_id": app.get("id") or app.get("app_id") or app.get("external_app_id") or "",
        "client_status": client.get("status") or "",
    }


def run_exchange(
    *,
    deeptutor_url: str,
    user_jwt: str,
    request_id: str,
    expected_client_id: str,
) -> dict[str, Any]:
    if not deeptutor_url:
        return {
            "status": "delegated",
            "reason": "deeptutor_url_not_provided",
            "command": "POST /api/v1/auth/eduplus2/exchange with Authorization: Bearer <eduplus2_user_jwt>",
        }
    url = deeptutor_url.rstrip("/") + "/api/v1/auth/eduplus2/exchange"
    try:
        payload = _http_json(
            url,
            method="POST",
            data=b"{}",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": "Bearer " + user_jwt,
                "X-Request-ID": request_id,
            },
        )
    except SmokeError as exc:
        return {"status": "failed", "reason": str(exc), "request_id": request_id}
    dt_token = str(payload.get("dt_token") or payload.get("access_token") or "")
    if not dt_token:
        return {"status": "failed", "reason": "missing_dt_token", "request_id": request_id}
    try:
        _, claims = decode_jwt_unverified(dt_token)
    except SmokeError as exc:
        return {"status": "failed", "reason": str(exc), "request_id": request_id}
    eduplus2 = claims.get("eduplus2") if isinstance(claims.get("eduplus2"), dict) else {}
    return {
        "status": "ok",
        "request_id": request_id,
        "dt_token_valid_now": int(claims.get("exp") or 0) > int(time.time()),
        "dt_token_has_eduplus2_claim": bool(eduplus2),
        "dt_token_azp_matches_client": str(eduplus2.get("azp") or "") == expected_client_id,
        "expires_at": int(claims.get("exp") or payload.get("expires_at") or 0),
        "tenant_id_sha256": _sha256(payload.get("tenant_id") or claims.get("tid")),
        "user_id_sha256": _sha256(payload.get("user_id") or claims.get("sub")),
    }


def delegated_resource_upload_reference_step() -> dict[str, Any]:
    return {
        "status": "delegated",
        "upload_channel": "http_presigned_upload",
        "turn_channel": "http_or_ws_start_turn_resource_ids",
        "websocket_upload_payload_allowed": False,
        "forbidden_payloads": ["raw_binary", "external_url", "large_base64", "signed_upload_url"],
        "evidence": "A2.2 target smoke must create upload intent, confirm upload, then submit prompt + resource_ids.",
    }


def delegated_ws_and_audit_steps() -> tuple[dict[str, Any], dict[str, Any]]:
    ws = {
        "status": "delegated",
        "auth_ack_expected": True,
        "pytest": (
            "PYTHONPATH=extensions/enterprise/src ./.venv/bin/python -m pytest "
            "extensions/enterprise/tests/test_eduplus2_federated_access.py::"
            "test_ws_auth_refresh_accepts_only_same_eduplus2_identity -q"
        ),
    }
    audit = {
        "status": "delegated",
        "ordinary_user_denied": "403",
        "tenant_admin_export": "completed/jsonl-or-csv/redacted",
        "pytest": (
            "PYTHONPATH=extensions/enterprise/src ./.venv/bin/python -m pytest "
            "extensions/enterprise/tests/test_eduplus2_federated_access.py::"
            "test_audit_query_and_export_api_requires_tenant_admin -q"
        ),
    }
    return ws, audit


def summarize(args: argparse.Namespace) -> dict[str, Any]:
    token_file = Path(args.token_file)
    env_file = Path(args.env_file)
    token_values = load_env_file(token_file)
    env_values = load_env_file(env_file)
    client_id = _client_id(token_values, env_values)
    user_jwt = (token_values.get("TOKEN") or token_values.get("USER_JWT") or "").strip()

    steps: dict[str, Any] = {
        "configuration": build_configuration_step(
            token_file=token_file,
            env_file=env_file,
            token_values=token_values,
            env_values=env_values,
        ),
        "user_jwt": build_user_jwt_step(user_jwt, expected_client_id=client_id),
    }

    if args.real:
        steps["discovery_jwks"] = run_discovery(env_values)
        m2m_step, m2m_token = request_m2m_token(env_values, _client_secret(token_values, env_values))
        steps["m2m_token"] = m2m_step
        steps["resolve"] = run_resolve(env_values, m2m_token=m2m_token, client_id=client_id)
        steps["exchange"] = run_exchange(
            deeptutor_url=args.deeptutor_url or "",
            user_jwt=user_jwt,
            request_id=args.request_id,
            expected_client_id=client_id,
        )
    else:
        steps["discovery_jwks"] = {"status": "dry_run", "network_called": False}
        steps["m2m_token"] = {"status": "dry_run", "network_called": False}
        steps["resolve"] = {"status": "dry_run", "network_called": False}
        steps["exchange"] = {
            "status": "dry_run",
            "network_called": False,
            "dt_token_decode": "requires --real --deeptutor-url",
        }
    steps["resource_upload_reference"] = delegated_resource_upload_reference_step()
    steps["ws_refresh"], steps["audit_query_export"] = delegated_ws_and_audit_steps()

    blockers = []
    if steps["configuration"]["status"] != "ok":
        blockers.append("configuration_incomplete")
    if steps["user_jwt"]["status"] != "ok":
        blockers.append("user_jwt_" + steps["user_jwt"]["status"])
    if args.real:
        for name in ("discovery_jwks", "m2m_token", "resolve", "exchange"):
            if steps[name]["status"] not in {"ok", "delegated"}:
                blockers.append(name + "_" + steps[name]["status"])

    return {
        "schema_version": 1,
        "mode": "real" if args.real else "dry_run",
        "overall_status": "failed" if blockers else "ok",
        "request_id": args.request_id,
        "steps": steps,
        "negative_cases": {
            "missing_token": "return code 2 with user_jwt.status=missing",
            "expired_token": "return code 2 with user_jwt.status=expired",
            "tenant_mismatch_or_rate_limit_or_503": "covered by integration tests or --real endpoint response",
            "ws_upload_payload": "WebSocket must reject raw binary, external URL, large base64 or signed upload URL",
            "resource_binding": "A2.2/A2.3 must cover expired upload URL, hash mismatch and cross-owner resource_ids",
        },
        "next_steps": blockers,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="只解析配置和 JWT，不访问网络（默认）")
    mode.add_argument("--real", action="store_true", help="访问 EduPlus2/DeepTutor 真实 endpoint")
    parser.add_argument("--token-file", default=str(DEFAULT_TOKEN_FILE))
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    parser.add_argument("--deeptutor-url", default="", help="可选 DeepTutor base URL，用于真实 exchange")
    parser.add_argument(
        "--request-id",
        default="p1-fronting-smoke-" + hashlib.sha256(str(time.time()).encode()).hexdigest()[:12],
    )
    parsed = parser.parse_args(argv)
    if not parsed.real:
        parsed.dry_run = True
    return parsed


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    token_values = load_env_file(Path(args.token_file))
    env_values = load_env_file(Path(args.env_file))
    secrets = _secret_values(token_values, env_values)
    try:
        payload = summarize(args)
        rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
        _assert_no_secret_leak(rendered, secrets)
    except SecretLeakError as exc:
        safe = {
            "schema_version": 1,
            "mode": "real" if args.real else "dry_run",
            "overall_status": "failed",
            "steps": {"redaction": {"status": "failed", "reason": str(exc)}},
            "next_steps": ["fix_redaction_before_rerun"],
        }
        print(json.dumps(safe, ensure_ascii=False, sort_keys=True, indent=2))
        return 3
    print(rendered)
    return 0 if payload["overall_status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
