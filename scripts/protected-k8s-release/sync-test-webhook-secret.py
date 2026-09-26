#!/usr/bin/env python3
"""仅在 test-cn 受控发布时同步 EduPlus2 Webhook 的运行时 Secret。"""

from __future__ import annotations

import base64
import binascii
import json
import os
from pathlib import Path
import subprocess
import tempfile

SECRET_NAME = "deeptutor-runtime-secrets"
SECRET_KEY = "DT_EDUPLUS2_WEBHOOK_SECRET"
NAMESPACE = "deeptutor-test-cn"


def _kubectl(*args: str, kubeconfig: Path, payload: dict | None = None) -> str:
    try:
        result = subprocess.run(
            ["kubectl", "--kubeconfig", str(kubeconfig), "-n", NAMESPACE, *args],
            input=json.dumps(payload) if payload is not None else None,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise SystemExit("kubectl is unavailable") from exc
    if result.returncode:
        # kubectl 错误可能包含请求数据；不要把原文写入 CI 日志。
        raise SystemExit("test-cn Webhook Secret synchronization failed")
    return result.stdout


def _kubeconfig_bytes(raw: str) -> bytes:
    if raw.startswith("apiVersion:"):
        return raw.encode("utf-8")
    try:
        return base64.b64decode("".join(raw.split()), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise SystemExit("invalid test-cn kubeconfig data") from exc


def main() -> int:
    if os.environ.get("DEEPTUTOR_TARGET_ENV_ID") != "test-cn":
        raise SystemExit("Webhook Secret sync is restricted to test-cn")
    if os.environ.get("DEEPTUTOR_K8S_NAMESPACE") != NAMESPACE:
        raise SystemExit("unexpected test-cn namespace")
    secret = os.environ.get("DT_TEST_CN_EDUPLUS2_WEBHOOK_SECRET", "")
    if not secret or len(secret) > 4096 or "\x00" in secret or "\n" in secret:
        raise SystemExit("test-cn Webhook Secret is missing or invalid")
    kubeconfig_data = os.environ.get("KUBECONFIG_DATA", "")
    if not kubeconfig_data:
        raise SystemExit("test-cn kubeconfig data is missing")

    with tempfile.TemporaryDirectory(prefix="dt-test-webhook-") as directory:
        kubeconfig = Path(directory) / "kubeconfig"
        kubeconfig.write_bytes(_kubeconfig_bytes(kubeconfig_data))
        kubeconfig.chmod(0o600)
        try:
            current = json.loads(
                _kubectl("get", "secret", SECRET_NAME, "-o", "json", kubeconfig=kubeconfig)
            )
        except (ValueError, KeyError) as exc:
            raise SystemExit("invalid test-cn runtime Secret response") from exc
        metadata = current.get("metadata") or {}
        if (
            current.get("kind") != "Secret"
            or metadata.get("name") != SECRET_NAME
            or metadata.get("namespace") != NAMESPACE
            or current.get("immutable") is True
            or SECRET_KEY not in (current.get("data") or {})
        ):
            raise SystemExit("unexpected test-cn runtime Secret contract")
        original = dict(current["data"])
        encoded = base64.b64encode(secret.encode("utf-8")).decode("ascii")
        if original[SECRET_KEY] == encoded:
            print("test-cn Webhook Secret already matches")
            return 0

        current["data"][SECRET_KEY] = encoded
        for field in ("managedFields", "uid", "creationTimestamp", "generation"):
            metadata.pop(field, None)
        _kubectl("replace", "-f", "-", kubeconfig=kubeconfig, payload=current)
        updated = json.loads(
            _kubectl("get", "secret", SECRET_NAME, "-o", "json", kubeconfig=kubeconfig)
        )
        data = updated.get("data") or {}
        if data.get(SECRET_KEY) != encoded or any(
            data.get(key) != value for key, value in original.items() if key != SECRET_KEY
        ):
            raise SystemExit("test-cn Webhook Secret post-update verification failed")
    print("test-cn Webhook Secret synchronized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
