"""Production entry points must not call local skill/persona services directly."""

from __future__ import annotations

from pathlib import Path


def test_turn_and_api_entrypoints_use_runtime_skill_persona_providers() -> None:
    """若 API/turn 仍直接读取 data/user/workspace/{skills,personas}，本测试应失败。"""

    files = {
        "turn executor": Path("deeptutor/services/session/turns/executor.py"),
        "skills api": Path("deeptutor/api/routers/skills.py"),
        "personas api": Path("deeptutor/api/routers/personas.py"),
    }
    contents = {name: path.read_text(encoding="utf-8") for name, path in files.items()}

    assert "get_runtime_skill_service" in contents["turn executor"]
    assert "get_runtime_persona_service" in contents["turn executor"]
    assert "get_runtime_skill_service" in contents["skills api"]
    assert "get_runtime_persona_service" in contents["personas api"]
    assert "get_skill_service()" not in contents["turn executor"]
    assert "get_persona_service()" not in contents["turn executor"]
