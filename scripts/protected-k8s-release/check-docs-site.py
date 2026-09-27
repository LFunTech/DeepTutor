"""通过目标 Ingress/TLS 验证 test-cn 文档首页和一项真实静态资源。"""

from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class DocsPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self._in_title = False
        self.assets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "title":
            self._in_title = True
        if tag == "link" and values.get("rel") == "stylesheet" and values.get("href"):
            self.assets.append(values["href"] or "")
        if tag == "script" and values.get("src"):
            self.assets.append(values["src"] or "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data


def fetch(origin: str, path: str) -> tuple[int, str, bytes]:
    try:
        with urlopen(f"{origin}{path}", timeout=30) as response:
            final = urlsplit(response.geturl())
            expected = urlsplit(origin)
            if (final.scheme, final.netloc) != (expected.scheme, expected.netloc):
                raise ValueError("cross_origin_redirect")
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise ValueError("oversized_response")
            return response.status, response.headers.get_content_type(), body
    except HTTPError as exc:
        raise ValueError(f"http_{exc.code}") from exc
    except URLError as exc:
        raise ValueError("transport_error") from exc


def check(origin: str, allow_http_for_test: bool) -> dict[str, object]:
    parsed_origin = urlsplit(origin)
    expected_scheme = "http" if allow_http_for_test else "https"
    if (
        parsed_origin.scheme != expected_scheme
        or not parsed_origin.netloc
        or parsed_origin.path not in ("", "/")
        or parsed_origin.query
        or parsed_origin.fragment
    ):
        raise ValueError("invalid_origin")
    origin = origin.rstrip("/")
    home_status, home_type, home_body = fetch(origin, "/docs/")
    if home_status != 200 or home_type != "text/html":
        raise ValueError("invalid_homepage_response")
    parser = DocsPageParser()
    parser.feed(home_body.decode("utf8"))
    if "智能体基座" not in parser.title:
        raise ValueError("unexpected_homepage_title")
    asset_path = next(
        (
            path
            for path in parser.assets
            if path.startswith("/docs/assets/")
            and not urlsplit(path).query
            and not urlsplit(path).fragment
        ),
        "",
    )
    if not asset_path:
        raise ValueError("missing_local_asset")
    asset_status, asset_type, asset_body = fetch(origin, asset_path)
    if (
        asset_status != 200
        or not asset_body
        or asset_type not in ("text/css", "application/javascript", "text/javascript")
    ):
        raise ValueError("invalid_asset_response")
    return {
        "ready": True,
        "target_env_id": "test-cn",
        "origin_host_hash": hashlib.sha256(parsed_origin.netloc.encode("utf8")).hexdigest()[:12],
        "homepage_path": "/docs/",
        "homepage_status": home_status,
        "asset_path": asset_path,
        "asset_status": asset_status,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--allow-http-for-test", action="store_true")
    args = parser.parse_args()
    try:
        result = check(args.origin, args.allow_http_for_test)
    except Exception as exc:
        code = str(exc) if isinstance(exc, ValueError) else "unexpected_error"
        result = {"ready": False, "target_env_id": "test-cn", "error_code": code}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf8"
    )
    if not result["ready"]:
        print(f"docs_smoke_failed:{result['error_code']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
