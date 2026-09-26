"""受保护镜像的启动入口不得回退到本地管理 API。"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]
START = ROOT / "deploy/docker-runtime/start-backend.sh"
DOCKERFILE = ROOT / "Dockerfile.protected-runtime"


@pytest.fixture
def fake_python(tmp_path: Path) -> tuple[Path, Path]:
    binary = tmp_path / "python"
    marker = tmp_path / "uvicorn-module"
    binary.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = '-c' ]; then echo 300; exit 0; fi\n"
        'printf "%s" "$3" > "$TEST_UVICORN_MODULE"\n',
        encoding="utf-8",
    )
    binary.chmod(0o755)
    return binary, marker


def _start(fake_python: tuple[Path, Path], *, config: Path | None, override: str = ""):
    binary, marker = fake_python
    env = {
        **os.environ,
        "PATH": f"{binary.parent}:{os.environ['PATH']}",
        "DEEPTUTOR_PROTECTED_RUNTIME": "1",
        "DEEPTUTOR_POSTGRES_CONFIG": str(config) if config is not None else "",
        "DEEPTUTOR_BACKEND_APP_MODULE": override,
        "TEST_UVICORN_MODULE": str(marker),
    }
    result = subprocess.run(["bash", str(START)], env=env, capture_output=True, text=True)
    return result, marker


def test_protected_image_declares_fail_closed_runtime_mode():
    assert "ENV DEEPTUTOR_PROTECTED_RUNTIME=1" in DOCKERFILE.read_text(encoding="utf-8")


def test_protected_backend_rejects_missing_config_and_core_override(fake_python, tmp_path):
    for config, override in (
        (None, ""),
        (tmp_path / "missing.json", ""),
        (tmp_path / "deployment.json", "deeptutor.api.main:app"),
    ):
        if config is not None and config.name == "deployment.json":
            config.write_text("{}", encoding="utf-8")
        result, marker = _start(fake_python, config=config, override=override)
        assert result.returncode != 0
        assert not marker.exists()


def test_protected_backend_uses_only_enterprise_app(fake_python, tmp_path):
    config = tmp_path / "deployment.json"
    config.write_text("{}", encoding="utf-8")
    result, marker = _start(fake_python, config=config)
    assert result.returncode == 0, result.stderr
    assert marker.read_text(encoding="utf-8") == "deeptutor_enterprise.runtime_app:app"


def test_local_backend_keeps_existing_core_fallback(fake_python):
    binary, marker = fake_python
    env = {
        **os.environ,
        "PATH": f"{binary.parent}:{os.environ['PATH']}",
        "DEEPTUTOR_PROTECTED_RUNTIME": "",
        "DEEPTUTOR_POSTGRES_CONFIG": "",
        "DEEPTUTOR_BACKEND_APP_MODULE": "",
        "TEST_UVICORN_MODULE": str(marker),
    }
    result = subprocess.run(["bash", str(START)], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert marker.read_text(encoding="utf-8") == "deeptutor.api.main:app"
