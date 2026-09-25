"""Helpers for synchronizing the native K8s deployment ConfigMap.

The release pipeline treats ``deeptutor-deployment-config`` as the target
environment contract and stores only secret references inside it.  The public
ingress origin is non-secret, but it must match the deployed host; otherwise
browser WebSocket and CSRF checks fail even when the image rollout succeeds.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


def _assert_exact_https_origin(origin: str) -> str:
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("expected origin must be an exact HTTPS origin")
    return f"{parsed.scheme}://{parsed.netloc}"


def _deployment_payload(configmap: dict[str, Any]) -> dict[str, Any]:
    try:
        raw = configmap["data"]["deployment.json"]
    except KeyError:
        raise ValueError("deployment ConfigMap must contain data.deployment.json") from None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("deployment.json must be valid JSON") from None
    if not isinstance(payload, dict):
        raise ValueError("deployment.json must be a JSON object")
    return payload


def _normalized_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def build_origin_patch(
    configmap: dict[str, Any], *, expected_origin: str
) -> tuple[dict[str, dict[str, str]], str]:
    """Return a Kubernetes merge patch and a stable hash for deployment.json."""

    origin = _assert_exact_https_origin(expected_origin)
    payload = _deployment_payload(configmap)
    raw_origins = payload.get("origins")
    if not isinstance(raw_origins, list) or not all(
        isinstance(item, str) for item in raw_origins
    ):
        raise ValueError("deployment.json origins must be a string list")
    origins = list(raw_origins)
    if origin not in origins:
        origins.append(origin)
    payload["origins"] = origins
    rendered = _normalized_json(payload)
    digest = "sha256:" + hashlib.sha256(rendered.encode("utf8")).hexdigest()
    return {"data": {"deployment.json": rendered}}, digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--input", required=True, help="Kubernetes ConfigMap JSON from kubectl get -o json")
    parser.add_argument("--expected-origin", required=True)
    parser.add_argument("--output-patch", required=True)
    parser.add_argument("--hash-output", required=True)
    args = parser.parse_args(argv)

    configmap = json.loads(Path(args.input).read_text(encoding="utf8"))
    patch, digest = build_origin_patch(configmap, expected_origin=args.expected_origin)
    Path(args.output_patch).write_text(
        json.dumps(patch, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf8"
    )
    Path(args.hash_output).write_text(digest + "\n", encoding="utf8")
    print(
        json.dumps(
            {
                "ready": True,
                "expected_origin": _assert_exact_https_origin(args.expected_origin),
                "deployment_config_hash": digest,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
