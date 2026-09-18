from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess
import sys
import time


def _b64url(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _jwt(*, exp: int, azp: str = "client-a", tid: str = "tenant-private", eui: str = "user-private") -> str:
    return ".".join(
        [
            _b64url({"alg": "RS256", "kid": "kid-private"}),
            _b64url(
                {
                    "iss": "https://eduplus2.example",
                    "sub": "subject-private",
                    "tid": tid,
                    "eui": eui,
                    "azp": azp,
                    "iat": int(time.time()) - 30,
                    "exp": exp,
                }
            ),
            "signature-private",
        ]
    )


def _write_inputs(tmp_path: Path, *, token: str | None) -> tuple[Path, Path, str]:
    secret = "client-secret-private"
    token_file = tmp_path / "token-test.secrets"
    lines = ["ClientID=client-a", f"ClientSecret={secret}"]
    if token is not None:
        lines.insert(0, f"TOKEN={token}")
    token_file.write_text("\n".join(lines) + "\n")
    env_file = tmp_path / "deeptutor-local-eduplus2.env"
    env_file.write_text(
        "\n".join(
            [
                "DT_EDUPLUS2_DISCOVERY_URL=https://eduplus2.example/.well-known/openid-configuration",
                "DT_EDUPLUS2_JWKS_URI=https://eduplus2.example/.well-known/jwks.json",
                "DT_EDUPLUS2_TOKEN_ENDPOINT=https://eduplus2.example/oauth/token",
                "DT_EDUPLUS2_RESOLVE_URL=https://eduplus2.example/api/v1/open/oauth-clients/resolve",
                "DT_EDUPLUS2_PROFILE_URL=https://eduplus2.example/api/v1/open/profile",
                "DT_EDUPLUS2_PERMISSION_URL=https://eduplus2.example/api/v1/open/permissions/check",
                "DT_EDUPLUS2_CLIENT_ID=client-a",
                f"DT_EDUPLUS2_CLIENT_SECRET={secret}",
                "DT_EDUPLUS2_ALLOWED_CLIENTS=client-a:tenant-private:app-private",
            ]
        )
        + "\n"
    )
    return token_file, env_file, secret


def _run(tmp_path: Path, *, token: str | None) -> subprocess.CompletedProcess[str]:
    token_file, env_file, _secret = _write_inputs(tmp_path, token=token)
    return subprocess.run(
        [
            sys.executable,
            "scripts/enterprise/eduplus2_fronting_app_smoke.py",
            "--dry-run",
            "--token-file",
            str(token_file),
            "--env-file",
            str(env_file),
        ],
        check=False,
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def test_dry_run_outputs_redacted_summary_without_secret_values(tmp_path: Path):
    """防止 P1 smoke 摘要回显 user JWT、client secret 或外部用户原文。"""

    token = _jwt(exp=int(time.time()) + 600)

    result = _run(tmp_path, token=token)

    assert result.returncode == 0, result.stderr
    rendered = result.stdout + result.stderr
    assert token not in rendered
    assert "client-secret-private" not in rendered
    assert "user-private" not in rendered
    payload = json.loads(result.stdout)
    assert payload["overall_status"] == "ok"
    assert payload["steps"]["user_jwt"]["valid_now"] is True
    assert payload["steps"]["user_jwt"]["azp_matches_client"] is True
    assert payload["steps"]["user_jwt"]["claims"]["eui_sha256"]
    assert payload["steps"]["configuration"]["secret_values_printed"] is False


def test_dry_run_fails_closed_for_missing_token_without_leaking_secret(tmp_path: Path):
    """防止 token-test.secrets 缺 JWT 时 smoke 继续执行或泄漏 secret。"""

    result = _run(tmp_path, token=None)

    assert result.returncode == 2
    rendered = result.stdout + result.stderr
    assert "client-secret-private" not in rendered
    payload = json.loads(result.stdout)
    assert payload["overall_status"] == "failed"
    assert payload["steps"]["user_jwt"]["status"] == "missing"
    assert payload["next_steps"]


def test_dry_run_fails_closed_for_expired_token_without_leaking_token(tmp_path: Path):
    """防止过期 EduPlus2 user JWT 被 smoke 标记为可联调。"""

    token = _jwt(exp=int(time.time()) - 60)

    result = _run(tmp_path, token=token)

    assert result.returncode == 2
    rendered = result.stdout + result.stderr
    assert token not in rendered
    assert "client-secret-private" not in rendered
    payload = json.loads(result.stdout)
    assert payload["overall_status"] == "failed"
    assert payload["steps"]["user_jwt"]["status"] == "expired"
    assert payload["steps"]["user_jwt"]["valid_now"] is False
