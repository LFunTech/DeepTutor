"""Subagent settings/cache files work when tenant scopes have no local PathService."""

from __future__ import annotations

from deeptutor.services.subagent import claude_models, config, sessions
from deeptutor.services.subagent.config import SubagentSettings


def _raise_local_path_unavailable():
    raise RuntimeError("local path service is unavailable for this scope")


def test_subagent_settings_fall_back_to_runtime_settings_dir(monkeypatch, tmp_path) -> None:
    settings_dir = tmp_path / "settings"
    monkeypatch.setattr(config, "get_path_service", _raise_local_path_unavailable)
    monkeypatch.setattr(config, "get_runtime_settings_dir", lambda: settings_dir, raising=False)

    config.save_subagent_settings(SubagentSettings(consult_budget=7))

    assert config.load_subagent_settings().consult_budget == 7
    assert (settings_dir / "subagent.json").is_file()


def test_subagent_sessions_fall_back_to_runtime_settings_dir(monkeypatch, tmp_path) -> None:
    settings_dir = tmp_path / "settings"
    monkeypatch.setattr(sessions, "get_path_service", _raise_local_path_unavailable)
    monkeypatch.setattr(sessions, "get_runtime_settings_dir", lambda: settings_dir, raising=False)

    key = sessions.session_key("chat-1", "agent-1")
    sessions.remember_session(key, "session-1", kind="codex", cwd="/workspace")

    assert sessions.get_session(key) == "session-1"
    assert (settings_dir / "subagent_sessions.json").is_file()
    sessions.forget_connection("agent-1")
    assert sessions.get_session(key) is None


def test_claude_model_cache_falls_back_to_runtime_settings_dir(monkeypatch, tmp_path) -> None:
    settings_dir = tmp_path / "settings"
    monkeypatch.setattr(claude_models, "get_path_service", _raise_local_path_unavailable)
    monkeypatch.setattr(
        claude_models, "get_runtime_settings_dir", lambda: settings_dir, raising=False
    )

    claude_models._write_cache([{"slug": "opus", "display_name": "Opus"}], "2026-09-15T00:00:00Z")

    models, fetched_at = claude_models.load_cached_claude_models()
    assert models == [{"slug": "opus", "display_name": "Opus"}]
    assert fetched_at == "2026-09-15T00:00:00Z"
    assert (settings_dir / "claude_models_cache.json").is_file()


async def test_subagent_connections_list_degrades_when_local_kb_paths_are_unavailable(
    monkeypatch,
) -> None:
    from deeptutor.api.routers import subagents

    monkeypatch.setattr(subagents, "current_kb_manager", _raise_local_path_unavailable)

    assert await subagents.list_connections() == {"connections": []}
