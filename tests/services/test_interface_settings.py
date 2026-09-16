"""Interface settings PG-runtime fallback tests."""

from __future__ import annotations

import json

from deeptutor.services.settings import interface_settings


def test_interface_settings_fallback_to_runtime_settings_when_local_path_unavailable(
    monkeypatch, tmp_path
) -> None:
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir()
    (settings_dir / "interface.json").write_text(
        json.dumps({"theme": "dark", "language": "zh"}), encoding="utf-8"
    )

    def _raise_local_path_unavailable():
        raise RuntimeError("local path service is unavailable for this scope")

    monkeypatch.setattr(interface_settings, "get_path_service", _raise_local_path_unavailable)
    monkeypatch.setattr(interface_settings, "get_runtime_settings_dir", lambda: settings_dir)

    settings = interface_settings.get_ui_settings()

    assert settings["theme"] == "dark"
    assert settings["language"] == "zh"
    assert settings["response_language"] == "zh"
