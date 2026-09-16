"""Runtime-local fallbacks for read-heavy services in PostgreSQL tenant scopes."""

from __future__ import annotations

from deeptutor.services.persona import service as persona_service_module
from deeptutor.services.skill import service as skill_service_module
from deeptutor.visualizers import store as visualizer_store_module


def _raise_local_path_unavailable():
    raise RuntimeError("local path service is unavailable for this scope")


def test_persona_service_uses_runtime_workspace_when_local_path_unavailable(
    monkeypatch, tmp_path
) -> None:
    data_root = tmp_path / "data"
    expected_root = (data_root / "user" / "workspace" / "personas").resolve()
    persona_service_module._instances.clear()
    monkeypatch.setattr(persona_service_module, "get_path_service", _raise_local_path_unavailable)
    monkeypatch.setattr(
        persona_service_module, "get_runtime_data_root", lambda: data_root, raising=False
    )

    service = persona_service_module.get_persona_service()

    assert service.root == expected_root
    assert service.list_personas() == []


def test_skill_service_uses_runtime_workspace_when_local_path_unavailable(
    monkeypatch, tmp_path
) -> None:
    data_root = tmp_path / "data"
    expected_root = (data_root / "user" / "workspace" / "skills").resolve()
    skill_service_module._instances.clear()
    monkeypatch.setattr(skill_service_module, "get_path_service", _raise_local_path_unavailable)
    monkeypatch.setattr(
        skill_service_module, "get_runtime_data_root", lambda: data_root, raising=False
    )

    service = skill_service_module.get_skill_service()

    assert service.root == expected_root
    assert isinstance(service.list_skills(), list)


def test_visualizer_store_uses_runtime_user_dirs_when_local_path_unavailable(
    monkeypatch, tmp_path
) -> None:
    from deeptutor.services import path_service

    data_root = tmp_path / "data"
    monkeypatch.setattr(path_service, "get_path_service", _raise_local_path_unavailable)
    monkeypatch.setattr(
        visualizer_store_module, "get_runtime_data_root", lambda: data_root, raising=False
    )
    monkeypatch.setattr(
        visualizer_store_module,
        "get_runtime_settings_dir",
        lambda: data_root / "user" / "settings",
        raising=False,
    )

    store = visualizer_store_module.VisualizerStore()

    assert store.root == (data_root / "user" / "visualizers").resolve()
    assert store.state_file == (data_root / "user" / "settings" / "visualizers.json").resolve()
    assert store.state() == {"installed": [], "disabled": [], "uninstalled": []}


def test_notebook_manager_uses_runtime_notebook_dir_when_local_path_unavailable(
    monkeypatch, tmp_path
) -> None:
    from deeptutor.services.notebook import service as notebook_service_module

    data_root = tmp_path / "data"
    notebook_service_module._instances.clear()
    monkeypatch.setattr(notebook_service_module, "get_path_service", _raise_local_path_unavailable)
    monkeypatch.setattr(
        notebook_service_module, "get_runtime_data_root", lambda: data_root, raising=False
    )

    manager = notebook_service_module.get_notebook_manager()

    assert manager.base_dir == (data_root / "user" / "notebooks").resolve()
    assert manager.list_notebooks() == []


def test_co_writer_storage_uses_runtime_workspace_when_local_path_unavailable(
    monkeypatch, tmp_path
) -> None:
    from deeptutor.co_writer import storage as co_writer_storage_module

    data_root = tmp_path / "data"
    co_writer_storage_module._storages.clear()
    monkeypatch.setattr(co_writer_storage_module, "get_path_service", _raise_local_path_unavailable)
    monkeypatch.setattr(
        co_writer_storage_module, "get_runtime_data_root", lambda: data_root, raising=False
    )

    storage = co_writer_storage_module.get_co_writer_storage()

    assert storage.docs_root() == data_root / "user" / "workspace" / "co-writer" / "documents"
    assert storage.list_documents() == []


def test_book_storage_uses_runtime_workspace_when_local_path_unavailable(
    monkeypatch, tmp_path
) -> None:
    from deeptutor.book import storage as book_storage_module

    data_root = tmp_path / "data"
    book_storage_module._storages.clear()
    monkeypatch.setattr(book_storage_module, "get_path_service", _raise_local_path_unavailable)
    monkeypatch.setattr(
        book_storage_module, "get_runtime_data_root", lambda: data_root, raising=False
    )

    storage = book_storage_module.get_book_storage()

    assert storage.path_service.workspace_root == data_root.resolve()
    assert storage.list_book_ids() == []


def test_book_engine_uses_runtime_workspace_when_local_path_unavailable(
    monkeypatch, tmp_path
) -> None:
    from deeptutor.book import engine as book_engine_module
    from deeptutor.book import storage as book_storage_module
    from deeptutor.multi_user.context import reset_current_user, set_current_user
    from deeptutor.multi_user.models import CurrentUser, UserScope

    data_root = tmp_path / "data"
    book_engine_module._engines.clear()
    book_storage_module._storages.clear()
    monkeypatch.setattr(book_engine_module, "get_path_service", _raise_local_path_unavailable, raising=False)
    monkeypatch.setattr(book_storage_module, "get_path_service", _raise_local_path_unavailable)
    monkeypatch.setattr(book_engine_module, "get_runtime_data_root", lambda: data_root, raising=False)
    monkeypatch.setattr(
        book_storage_module, "get_runtime_data_root", lambda: data_root, raising=False
    )
    token = set_current_user(
        CurrentUser(
            id="user-1",
            username="user@example.test",
            role="tenant_admin",
            scope=UserScope(kind="tenant", tenant_id="tenant-1", user_id="user-1", root=None),
        )
    )

    try:
        engine = book_engine_module.get_book_engine()

        assert engine.storage.path_service.workspace_root == data_root.resolve()
        assert engine.list_books() == []
    finally:
        reset_current_user(token)


def test_co_writer_history_paths_use_runtime_workspace_when_local_path_unavailable(
    monkeypatch, tmp_path
) -> None:
    from deeptutor.co_writer import edit_agent

    data_root = tmp_path / "data"
    monkeypatch.setattr(edit_agent, "get_path_service", _raise_local_path_unavailable)
    monkeypatch.setattr(edit_agent, "get_runtime_data_root", lambda: data_root, raising=False)

    assert edit_agent._history_file() == (
        data_root / "user" / "workspace" / "co-writer" / "history.json"
    )
    assert edit_agent.load_history() == []


def test_memory_paths_use_runtime_memory_dir_when_local_path_unavailable(
    monkeypatch, tmp_path
) -> None:
    from deeptutor.services.memory import paths as memory_paths

    data_root = tmp_path / "data"
    monkeypatch.setattr(memory_paths, "get_path_service", _raise_local_path_unavailable)
    monkeypatch.setattr(memory_paths, "get_runtime_data_root", lambda: data_root, raising=False)

    assert memory_paths.memory_root() == data_root / "memory"
    assert memory_paths.backup_root() == data_root / "memory" / "backup"


def test_knowledge_paths_and_config_use_runtime_kb_root_when_local_path_unavailable(
    monkeypatch, tmp_path
) -> None:
    from deeptutor.multi_user import knowledge_access
    from deeptutor.services.config import knowledge_base_config

    data_root = tmp_path / "data"
    monkeypatch.setattr(knowledge_access, "get_current_path_service", _raise_local_path_unavailable)
    monkeypatch.setattr(knowledge_access, "get_runtime_data_root", lambda: data_root, raising=False)
    monkeypatch.setattr(
        knowledge_base_config, "get_path_service", _raise_local_path_unavailable
    )
    monkeypatch.setattr(
        knowledge_base_config, "get_runtime_data_root", lambda: data_root, raising=False
    )

    knowledge_base_config.KnowledgeBaseConfigService._instances.clear()
    service = knowledge_base_config.get_kb_config_service()

    assert knowledge_access.current_kb_base_dir() == data_root / "knowledge_bases"
    assert service.config_path == (data_root / "knowledge_bases" / "kb_config.json").resolve()
    assert service.get_all_configs()["knowledge_bases"] == {}


def test_partner_group_store_uses_runtime_user_root_when_local_path_unavailable(
    monkeypatch, tmp_path
) -> None:
    from deeptutor.multi_user.context import reset_current_user, set_current_user
    from deeptutor.multi_user.models import CurrentUser, UserScope
    from deeptutor.services.partner_groups import store as partner_group_store_module

    data_root = tmp_path / "data"
    token = set_current_user(
        CurrentUser(
            id="user-1",
            username="user@example.test",
            role="tenant_admin",
            scope=UserScope(kind="tenant", tenant_id="tenant-1", user_id="user-1", root=None),
        )
    )
    monkeypatch.setattr(
        partner_group_store_module, "get_current_path_service", _raise_local_path_unavailable
    )
    monkeypatch.setattr(
        partner_group_store_module, "get_runtime_data_root", lambda: data_root, raising=False
    )
    try:
        store = partner_group_store_module.PartnerGroupStore()
        assert store.root == data_root / "user" / "partner_groups"
        assert store.list() == []
    finally:
        reset_current_user(token)


def test_reading_store_uses_runtime_workspace_when_local_path_unavailable(
    monkeypatch, tmp_path
) -> None:
    from deeptutor.reading import store as reading_store_module

    data_root = tmp_path / "data"
    monkeypatch.setattr(reading_store_module, "get_path_service", _raise_local_path_unavailable)
    monkeypatch.setattr(reading_store_module, "get_runtime_data_root", lambda: data_root, raising=False)

    store = reading_store_module.ReadingStore()

    assert store.root == data_root / "user" / "workspace" / "reading"
