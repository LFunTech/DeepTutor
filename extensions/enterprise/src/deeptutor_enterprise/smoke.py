"""M1/G1 目标环境 smoke harness。

真实 token/Secret 只通过环境变量读取，输出只包含 run_id、case id、状态码与脱敏错误。
缺少目标依赖时以非零退出，避免把未验证项误报为 G1 通过。
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
import uuid

import httpx

from .m1_g1 import build_smoke_plan

_ALLOWED_NEGATIVE_STATUSES = {401, 403, 404, 405, 410, 503}


def _origin(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("--base-url must be an HTTPS origin without credentials")
    return f"{parsed.scheme}://{parsed.netloc}"


def _endpoint_summary(value: str) -> dict[str, Any]:
    parsed = urlsplit(value)
    return {
        "scheme": parsed.scheme,
        "host_hash": hashlib.sha256((parsed.hostname or "").encode("utf8")).hexdigest()[:12],
        "port": parsed.port,
    }


async def _get(client: httpx.AsyncClient, path: str, *, token: str | None = None) -> dict[str, Any]:
    headers = {"Authorization": "Bearer " + token} if token else {}
    response = await client.get(path, headers=headers)
    return {"status_code": response.status_code}


async def run_smoke(
    *,
    base_url: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    origin = _origin(base_url)
    run_id = "g1-smoke-" + uuid.uuid4().hex[:12]
    dt_token = os.environ.get("DT_SMOKE_DT_TOKEN", "")
    eduplus2_jwt = os.environ.get("DT_SMOKE_EDUPLUS2_JWT", "")
    lightrag_sample_ready = os.environ.get("DT_SMOKE_LIGHTRAG_SAMPLE_READY") == "1"
    plan = build_smoke_plan(base_url=origin, lightrag_sample_ready=lightrag_sample_ready)
    cases: list[dict[str, Any]] = []
    unverified = set(plan["blocking_unverified"])

    async with httpx.AsyncClient(
        base_url=origin,
        follow_redirects=False,
        timeout=20,
        transport=transport,
    ) as client:
        for case_id, coro in [
            ("frontend_reachable", _get(client, "/")),
            ("http_status", _get(client, "/api/auth/status")),
            ("bearer_session_list", _get(client, "/api/sessions", token=dt_token or None)),
            ("tms_unavailable", _get(client, "/tms")),
            ("oms_unavailable", _get(client, "/oms")),
        ]:
            try:
                result = await coro
                ok = result["status_code"] < 500
                if case_id in {"bearer_session_list"} and not dt_token:
                    ok = False
                    unverified.add("dt_token_missing")
                if case_id in {"tms_unavailable", "oms_unavailable"}:
                    ok = result["status_code"] in _ALLOWED_NEGATIVE_STATUSES
                cases.append({"id": case_id, "ok": ok, **result})
            except Exception as exc:  # noqa: BLE001 - 输出脱敏错误类别即可
                cases.append({"id": case_id, "ok": False, "error": type(exc).__name__})

        if eduplus2_jwt:
            try:
                response = await client.post(
                    "/api/v1/auth/eduplus2/exchange",
                    json={"jwt": eduplus2_jwt},
                )
                cases.append(
                    {
                        "id": "eduplus2_exchange",
                        "ok": response.status_code in {200, 201},
                        "status_code": response.status_code,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                cases.append({"id": "eduplus2_exchange", "ok": False, "error": type(exc).__name__})
        else:
            cases.append({"id": "eduplus2_exchange", "ok": False, "unverified": "jwt_missing"})
            unverified.add("eduplus2_jwt_missing")

    for case_id in [
        "ws_start_turn",
        "ws_auth_refresh",
        "object_store",
        "audit_export",
        "owner_guard_denied",
    ]:
        cases.append(
            {"id": case_id, "ok": False, "unverified": "target_harness_requires_credentials"}
        )
        unverified.add(case_id + "_not_run")

    ok = all(case.get("ok") for case in cases) and not unverified
    return {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "base_url": _endpoint_summary(origin),
        "ok": ok,
        "cases": cases,
        "unverified": sorted(unverified),
        "redaction": plan["redaction"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    result = asyncio.run(run_smoke(base_url=args.base_url))
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf8"
    )
    print(
        json.dumps(
            {"run_id": result["run_id"], "ok": result["ok"], "unverified": result["unverified"]},
            ensure_ascii=False,
        )
    )
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
