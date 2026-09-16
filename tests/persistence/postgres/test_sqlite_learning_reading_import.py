# ruff: noqa: F811
"""SQLite mastery/reading 离线导入到 PG 学习与阅读域。"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import uuid

import psycopg
import pytest

from tests.fixtures.postgres import pg_cluster, pg_dsn  # noqa: F401
from tests.persistence.postgres.business.conftest import (  # noqa: F401
    business_actors,
    business_database,
    business_sync_database,
    migrated_pg,
    pg_scope_factory,
    pg_session_store_factory,
)

pytestmark = pytest.mark.asyncio


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_combined_manifest(path: Path, manifests: list[Path]) -> Path:
    payload = _read_json(manifests[-1])
    payload["sources"] = [source for manifest in manifests for source in _read_json(manifest)["sources"]]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _snapshot(
    source: Path,
    out: Path,
    *,
    source_id: str,
    source_version: str,
    tenant_id: str,
    source_owner: str,
    target_owner: str,
) -> Path:
    from deeptutor.persistence.postgres.offline_import import create_sqlite_source_snapshot

    result = create_sqlite_source_snapshot(
        source_db=source,
        output_dir=out,
        source_id=source_id,
        source_version=source_version,
        source_owner_id=source_owner,
        target_tenant_id=tenant_id,
        owner_mappings={source_owner: target_owner},
        freeze_id=f"freeze-{source_id}",
        stopped_writers=["web", "cli", "cron"],
        operator="unit-test",
    )
    stable_manifest = out / f"{source_id}.manifest.json"
    stable_manifest.write_text(result.manifest_path.read_text(encoding="utf-8"), encoding="utf-8")
    return stable_manifest


def _make_mastery_v2_source(root: Path) -> Path:
    from deeptutor.learning.models import (
        InteractionStatus,
        KnowledgePoint,
        KnowledgeType,
        LearningModule,
        LearningProgress,
        MasteryInteraction,
        PendingQuestion,
        TopicMetadata,
        TopicSource,
        TopicSourceKind,
    )
    from deeptutor.learning.storage import LearningStore

    store = LearningStore(root=root)
    progress = LearningProgress(
        book_id="legacy-path",
        name="Limits",
        modules=[
            LearningModule(
                id="module-one",
                name="Module",
                order=0,
                knowledge_points=[
                    KnowledgePoint(
                        id="kp-one",
                        name="Limit definition",
                        type=KnowledgeType.CONCEPT,
                        module_id="module-one",
                    )
                ],
            )
        ],
    )
    store.save(progress)
    store.bind_session("legacy-path", "legacy-session", owns_path=True)

    def write_interaction(tx):
        tx.put_interaction(
            MasteryInteraction(
                interaction_id="legacy-interaction",
                path_id="legacy-path",
                question=PendingQuestion(
                    question_id="legacy-question",
                    knowledge_point_id="kp-one",
                    prompt="What is a limit?",
                ),
                status=InteractionStatus.GRADED,
                session_id="legacy-session",
                user_answer="It approaches a value",
                result={"score": 1, "source_session_id": "ordinary text is not rewritten"},
            )
        )
        tx.emit("interaction.graded", {"note": "正文保留"}, session_id="legacy-session")

    store.mutate("legacy-path", write_interaction)
    store.put_topic(
        TopicMetadata(
            path_id="legacy-path",
            goal="Understand limits",
            description="source order matters",
            emoji="📈",
            map_seed=42,
            status="active",
            created_at=100.0,
            updated_at=200.0,
        ),
        [
            TopicSource(
                id="source-qb",
                kind=TopicSourceKind.QUESTION_BANK,
                source_id="legacy-entry",
                label="错题",
                position=0,
                created_at=101.0,
            ),
            TopicSource(
                id="source-chat",
                kind=TopicSourceKind.CHAT,
                source_id="legacy-session",
                label="会话",
                position=1,
                created_at=102.0,
            ),
        ],
    )
    with sqlite3.connect(root / "mastery.sqlite3") as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.commit()
    return root / "mastery.sqlite3"


def _make_mastery_v1_source(path: Path) -> None:
    from deeptutor.learning.models import LearningProgress

    state = LearningProgress(book_id="v1-path", name="Legacy V1").model_dump_json()
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE mastery_paths (
                path_id TEXT PRIMARY KEY,
                state_json TEXT NOT NULL,
                revision INTEGER NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE mastery_path_sessions (
                path_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                owns_path INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                last_seen_at REAL NOT NULL,
                PRIMARY KEY(path_id, session_id)
            );
            CREATE TABLE mastery_interactions (
                interaction_id TEXT PRIMARY KEY,
                path_id TEXT NOT NULL,
                status TEXT NOT NULL,
                question_json TEXT NOT NULL,
                session_id TEXT NOT NULL DEFAULT '',
                turn_id TEXT NOT NULL DEFAULT '',
                user_answer TEXT NOT NULL DEFAULT '',
                result_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE mastery_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path_id TEXT NOT NULL,
                revision INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                session_id TEXT NOT NULL DEFAULT '',
                turn_id TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL
            );
            CREATE TABLE mastery_path_leases (
                path_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                turn_id TEXT NOT NULL UNIQUE,
                acquired_at REAL NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT INTO mastery_paths(path_id,state_json,revision,created_at,updated_at) VALUES(?,?,?,?,?)",
            ("v1-path", state, 3, 10.0, 30.0),
        )
        connection.execute(
            "INSERT INTO mastery_path_sessions(path_id,session_id,owns_path,created_at,last_seen_at) VALUES(?,?,?,?,?)",
            ("v1-path", "legacy-session", 1, 11.0, 12.0),
        )
        connection.execute(
            "INSERT INTO mastery_events(path_id,revision,event_type,payload_json,session_id,created_at) VALUES(?,?,?,?,?,?)",
            ("v1-path", 3, "path.saved", "{}", "legacy-session", 30.0),
        )
        connection.commit()
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.commit()


def _make_reading_source(root: Path) -> Path:
    from deeptutor.reading.catalog_store import ReadingCatalogStore

    store = ReadingCatalogStore(root=root)
    store.upsert_material(
        content_id="content-two",
        material_id="mat-two",
        filename="two.pdf",
        title="Two",
        source_kind="file",
        status="ready",
    )
    store.upsert_material(
        content_id="content-one",
        material_id="mat-one",
        filename="one.pdf",
        title="One",
        source_kind="file",
        status="ready",
    )
    workspace = store.create_workspace("Reading", ["mat-two", "mat-one"], workspace_id="workspace-one")
    store.set_active_material(workspace.workspace_id, "mat-one")
    store.attach_session(
        "workspace-one", "legacy-session", title="Main reading", active_material_id="mat-one"
    )
    store.attach_session("workspace-one", "legacy-follow", title="Follow-up")
    store.link_session("workspace-one", "legacy-session", "legacy-follow")
    with sqlite3.connect(root / "_catalog.sqlite3") as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.commit()
    return root / "_catalog.sqlite3"


def _make_reading_duplicate_source(root: Path, *, title: str) -> Path:
    from deeptutor.reading.catalog_store import ReadingCatalogStore

    store = ReadingCatalogStore(root=root)
    store.upsert_material(
        content_id=f"content-{title}",
        material_id="dup-material",
        filename=f"{title}.pdf",
        title=title,
        source_kind="file",
        status="ready",
    )
    with sqlite3.connect(root / "_catalog.sqlite3") as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.commit()
    return root / "_catalog.sqlite3"


async def _seed_existing_mapping(migrated_pg, actor, pg_session_store_factory) -> int:
    sessions = pg_session_store_factory(actor)
    await sessions.create_session("Target", session_id="target-session")
    await sessions.create_session("Follow", session_id="target-follow")
    await sessions.upsert_notebook_entries(
        "target-session", [{"question_id": "legacy-q", "question": "Legacy?"}]
    )
    entry = await sessions.find_notebook_entry("target-session", "legacy-q")
    batch_id = str(uuid.uuid4())
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        async with connection.transaction():
            await connection.execute(
                """
                INSERT INTO migration_stage.batches(
                    batch_id,target_tenant_id,manifest_sha256,source_manifest,status,operator
                ) VALUES (%s,%s,%s,'{}'::jsonb,'published','unit-test')
                """,
                (batch_id, actor.tenant_id, "a" * 64),
            )
            await connection.execute(
                """
                INSERT INTO migration_stage.sources(
                    batch_id,source_id,source_type,source_version,source_owner_id,
                    target_owner_id,fingerprint,status,rows_total,rows_done
                ) VALUES (%s,'chat-source','sqlite','chat_history_sqlite/v1','legacy-user',%s,%s,'verified',3,3)
                """,
                (batch_id, actor.user_id, "b" * 64),
            )
            rows = [
                ("sessions", "legacy-session", "target-session", None),
                ("sessions", "legacy-follow", "target-follow", None),
                ("notebook_entries", "legacy-entry", None, entry["id"]),
            ]
            for domain, source_key, target_key, target_int in rows:
                await connection.execute(
                    """
                    INSERT INTO migration_stage.id_mappings(
                        batch_id,domain,source_id,source_owner_id,source_key,target_key,target_int
                    ) VALUES (%s,%s,'chat-source','legacy-user',%s,%s,%s)
                    """,
                    (batch_id, domain, source_key, target_key, target_int),
                )
    return int(entry["id"])


async def test_mastery_v2_and_reading_import_rewrites_links_and_preserves_order_versions(
    tmp_path: Path,
    migrated_pg,
    business_actors,
    business_database,
    business_sync_database,
    pg_scope_factory,
    pg_session_store_factory,
) -> None:
    """生产导入若不走既有映射、不保留正文/source/阅读排序和 CAS 版本应失败。"""

    from deeptutor.persistence.postgres.offline_import.learning_reading_sqlite import (
        SQLiteLearningReadingImporter,
    )
    from deeptutor.persistence.postgres.reading import AsyncReadingCatalogStore
    from deeptutor.reading.catalog_contracts import ReadingConflictError

    actor = business_actors.tenants[0].owners[0]
    entry_id = await _seed_existing_mapping(migrated_pg, actor, pg_session_store_factory)
    artifact = tmp_path / "artifact"
    mastery_manifest = _snapshot(
        _make_mastery_v2_source(tmp_path / "mastery"),
        artifact,
        source_id="legacy-mastery",
        source_version="mastery_sqlite/v2",
        tenant_id=actor.tenant_id,
        source_owner="legacy-user",
        target_owner=actor.user_id,
    )
    reading_manifest = _snapshot(
        _make_reading_source(tmp_path / "reading"),
        artifact,
        source_id="legacy-reading",
        source_version="reading_catalog_sqlite/v1",
        tenant_id=actor.tenant_id,
        source_owner="legacy-user",
        target_owner=actor.user_id,
    )
    manifest = _write_combined_manifest(artifact / "combined.json", [mastery_manifest, reading_manifest])

    report = await SQLiteLearningReadingImporter(migrated_pg.admin_dsn).import_manifest(
        manifest, operator="unit-test"
    )

    assert report["imported"] == {
        "mastery_paths": 1,
        "mastery_interactions": 1,
        "mastery_events": 3,
        "reading_materials": 2,
        "reading_workspaces": 1,
        "reading_sessions": 2,
        "reading_links": 1,
    }
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        path = await (
            await connection.execute(
                """
                SELECT path_id,state,revision,creator_session_id,creator_assigned
                  FROM enterprise.mastery_paths
                 WHERE tenant_id=%s AND owner_id=%s AND state->>'name'='Limits'
                """,
                (actor.tenant_id, actor.user_id),
            )
        ).fetchone()
        sources = await (
            await connection.execute(
                """
                SELECT id,kind,external_id,position
                  FROM enterprise.mastery_topic_sources
                 WHERE tenant_id=%s AND owner_id=%s AND path_id=%s
                 ORDER BY position
                """,
                (actor.tenant_id, actor.user_id, path[0]),
            )
        ).fetchall()
        interaction = await (
            await connection.execute(
                """
                SELECT question,session_id,user_answer,result
                  FROM enterprise.mastery_interactions
                 WHERE tenant_id=%s AND owner_id=%s AND path_id=%s
                """,
                (actor.tenant_id, actor.user_id, path[0]),
            )
        ).fetchone()
        tabs = await (
            await connection.execute(
                """
                SELECT material_id,tab_order
                  FROM enterprise.reading_workspace_materials
                 WHERE tenant_id=%s AND owner_id=%s AND workspace_id='workspace-one'
                 ORDER BY tab_order
                """,
                (actor.tenant_id, actor.user_id),
            )
        ).fetchall()
        reading_sessions = await (
            await connection.execute(
                """
                SELECT session_id,title,active_material_id,version
                  FROM enterprise.reading_workspace_sessions
                 WHERE tenant_id=%s AND owner_id=%s AND workspace_id='workspace-one'
                 ORDER BY session_id
                """,
                (actor.tenant_id, actor.user_id),
            )
        ).fetchall()
        link = await (
            await connection.execute(
                """
                SELECT target_session_id
                  FROM enterprise.reading_session_links
                 WHERE tenant_id=%s AND owner_id=%s AND workspace_id='workspace-one'
                   AND source_session_id='target-session'
                """,
                (actor.tenant_id, actor.user_id),
            )
        ).fetchone()

    assert path[1]["book_id"] == path[0]
    assert path[1]["modules"][0]["knowledge_points"][0]["id"] == "kp-one"
    assert path[2] == path[1]["version"]
    assert path[3:] == ("target-session", True)
    assert [(row[1], row[2], row[3]) for row in sources] == [
        ("question_bank", str(entry_id), 0),
        ("chat", "target-session", 1),
    ]
    assert interaction[0]["prompt"] == "What is a limit?"
    assert interaction[1:] == ("target-session", "It approaches a value", {"score": 1, "source_session_id": "ordinary text is not rewritten"})
    assert tabs == [("mat-two", 0), ("mat-one", 1)]
    assert reading_sessions == [
        ("target-follow", "Follow-up", None, 1),
        ("target-session", "Main reading", "mat-one", 1),
    ]
    assert link[0] == "target-follow"

    store = AsyncReadingCatalogStore(business_sync_database, pg_scope_factory(actor))
    updated = await store.run(
        lambda unit: unit.update_workspace("workspace-one", title="After import", expected_version=1)
    )
    assert updated.version == 2
    with pytest.raises(ReadingConflictError):
        await store.run(
            lambda unit: unit.update_workspace("workspace-one", title="stale", expected_version=1)
        )


async def test_mastery_v1_import_uses_default_topic_metadata_and_mapped_owner_session(
    tmp_path: Path, migrated_pg, business_actors, pg_session_store_factory
) -> None:
    from deeptutor.persistence.postgres.offline_import.learning_reading_sqlite import (
        SQLiteLearningReadingImporter,
    )

    actor = business_actors.tenants[0].owners[0]
    await _seed_existing_mapping(migrated_pg, actor, pg_session_store_factory)
    source = tmp_path / "mastery-v1.sqlite3"
    _make_mastery_v1_source(source)
    manifest = _snapshot(
        source,
        tmp_path / "artifact-v1",
        source_id="legacy-v1",
        source_version="mastery_sqlite/v1",
        tenant_id=actor.tenant_id,
        source_owner="legacy-user",
        target_owner=actor.user_id,
    )

    await SQLiteLearningReadingImporter(migrated_pg.admin_dsn).import_manifest(
        manifest, operator="unit-test"
    )

    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        row = await (
            await connection.execute(
                """
                SELECT p.state,p.revision,p.creator_session_id,m.goal,m.emoji,m.map_seed,count(s.id)
                  FROM enterprise.mastery_paths p
                  JOIN enterprise.mastery_topic_meta m USING (tenant_id,owner_id,path_id)
                  LEFT JOIN enterprise.mastery_topic_sources s USING (tenant_id,owner_id,path_id)
                 WHERE p.tenant_id=%s AND p.owner_id=%s AND p.path_id='v1-path'
                 GROUP BY p.state,p.revision,p.creator_session_id,m.goal,m.emoji,m.map_seed
                """,
                (actor.tenant_id, actor.user_id),
            )
        ).fetchone()
    assert row[0]["book_id"] == "v1-path"
    assert row[0]["version"] == row[1] == 3
    assert row[2:] == ("target-session", "", "🧭", row[5], 0)
    assert row[5] > 0


async def test_bad_reading_session_reference_rolls_back_all_sources(
    tmp_path: Path, migrated_pg, business_actors
) -> None:
    from deeptutor.persistence.postgres.offline_import.learning_reading_sqlite import (
        SQLiteLearningReadingImporter,
    )

    actor = business_actors.tenants[0].owners[0]
    artifact = tmp_path / "artifact-bad"
    mastery_manifest = _snapshot(
        _make_mastery_v2_source(tmp_path / "bad-mastery"),
        artifact,
        source_id="bad-mastery",
        source_version="mastery_sqlite/v2",
        tenant_id=actor.tenant_id,
        source_owner="legacy-user",
        target_owner=actor.user_id,
    )
    reading_manifest = _snapshot(
        _make_reading_source(tmp_path / "bad-reading"),
        artifact,
        source_id="bad-reading",
        source_version="reading_catalog_sqlite/v1",
        tenant_id=actor.tenant_id,
        source_owner="legacy-user",
        target_owner=actor.user_id,
    )
    manifest = _write_combined_manifest(artifact / "combined-bad.json", [mastery_manifest, reading_manifest])

    with pytest.raises(ValueError, match="missing mapping for sessions"):
        await SQLiteLearningReadingImporter(migrated_pg.admin_dsn).import_manifest(
            manifest, operator="unit-test"
        )

    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        mastery_count = await (
            await connection.execute(
                "SELECT count(*) FROM enterprise.mastery_paths WHERE tenant_id=%s AND owner_id=%s",
                (actor.tenant_id, actor.user_id),
            )
        ).fetchone()
        reading_count = await (
            await connection.execute(
                "SELECT count(*) FROM enterprise.reading_materials WHERE tenant_id=%s AND owner_id=%s",
                (actor.tenant_id, actor.user_id),
            )
        ).fetchone()
    assert mastery_count[0] == 0
    assert reading_count[0] == 0


async def test_different_reading_sources_with_conflicting_material_id_are_rejected_atomically(
    tmp_path: Path, migrated_pg, business_actors
) -> None:
    from deeptutor.persistence.postgres.offline_import.learning_reading_sqlite import (
        SQLiteLearningReadingImporter,
    )

    actor = business_actors.tenants[0].owners[0]
    artifact = tmp_path / "artifact-dup"
    manifest_a = _snapshot(
        _make_reading_duplicate_source(tmp_path / "reading-a", title="A"),
        artifact,
        source_id="reading-a",
        source_version="reading_catalog_sqlite/v1",
        tenant_id=actor.tenant_id,
        source_owner="legacy-user",
        target_owner=actor.user_id,
    )
    manifest_b = _snapshot(
        _make_reading_duplicate_source(tmp_path / "reading-b", title="B"),
        artifact,
        source_id="reading-b",
        source_version="reading_catalog_sqlite/v1",
        tenant_id=actor.tenant_id,
        source_owner="legacy-user",
        target_owner=actor.user_id,
    )
    manifest = _write_combined_manifest(artifact / "combined-dup.json", [manifest_a, manifest_b])

    with pytest.raises(ValueError, match="conflicting reading material"):
        await SQLiteLearningReadingImporter(migrated_pg.admin_dsn).import_manifest(
            manifest, operator="unit-test"
        )

    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as connection:
        row = await (
            await connection.execute(
                "SELECT count(*) FROM enterprise.reading_materials WHERE tenant_id=%s AND owner_id=%s",
                (actor.tenant_id, actor.user_id),
            )
        ).fetchone()
    assert row[0] == 0
