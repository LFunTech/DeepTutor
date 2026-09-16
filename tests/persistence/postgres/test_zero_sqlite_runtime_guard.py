# ruff: noqa: F811
"""新进程默认 PG runtime 的零 SQLite 访问门禁。"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import textwrap
import uuid

import pytest

from tests.fixtures.postgres import pg_cluster, pg_dsn  # noqa: F401


def _write_postgres_config(path: Path, tenant_id: str) -> Path:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "tenant_id": tenant_id,
                "resource": "zero-sqlite-runtime-test",
                "signing_secret": "env:TEST_SIGNING_SECRET",
                "auth_epoch_secret": "env:TEST_AUTH_EPOCH_SECRET",
                "bootstrap_secret": "env:TEST_BOOTSTRAP_SECRET",
            }
        ),
        encoding="utf-8",
    )
    return path


async def _bootstrap_pg(pg_dsn: str, *, tenant_id: str) -> None:
    from deeptutor.persistence.postgres.connection import Database
    from deeptutor.persistence.postgres.identity.service import IdentityService
    from deeptutor.persistence.postgres.migrations.runner import MigrationRunner

    await MigrationRunner(pg_dsn).apply()
    runtime_dsn = pg_dsn.replace("user=postgres", "user=dt_enterprise_app")
    async with Database(runtime_dsn, resource="bootstrap-zero-sqlite-runtime") as db:
        identity = IdentityService(
            db,
            tenant_id=tenant_id,
            signing_key="s" * 48,
            auth_epoch="epoch-zero-sqlite-runtime",
            bootstrap_secret="b" * 48,
        )
        await identity.bootstrap("admin", "administrator-123", secret="b" * 48)


@pytest.mark.asyncio
async def test_default_runtime_child_process_exercises_all_pg_domains_without_sqlite(
    pg_dsn: str, tmp_path: Path
) -> None:
    tenant_id = str(uuid.uuid4())
    await _bootstrap_pg(pg_dsn, tenant_id=tenant_id)
    config = _write_postgres_config(tmp_path / "postgres.json", tenant_id)
    home = tmp_path / "home"
    home.mkdir()
    sqlite_probe = tmp_path / "forbidden.sqlite3"
    runtime_dsn = pg_dsn.replace("user=postgres", "user=dt_enterprise_app")
    script = textwrap.dedent(
        f"""
        import asyncio
        from pathlib import Path
        import sqlite3

        guard_hits = []

        def forbidden_sqlite_connect(database, *args, **kwargs):
            guard_hits.append(str(database))
            raise AssertionError(f"SQLite runtime access blocked: {{database!r}}")

        sqlite3.connect = forbidden_sqlite_connect
        for candidate in (":memory:", {str(sqlite_probe)!r}):
            try:
                sqlite3.connect(candidate)
            except AssertionError:
                pass
            else:
                raise AssertionError("sqlite3.connect guard did not reject " + candidate)
        expected_guard_hits = list(guard_hits)

        async def main():
            from deeptutor.app.container import get_application_container
            from deeptutor.capabilities.marginnote4.models import MarginNoteObject, SyncBatch
            from deeptutor.learning.models import LearningProgress
            from deeptutor.multi_user.context import (
                reset_current_user,
                set_current_user,
                user_from_token_payload,
            )
            from deeptutor.persistence.postgres.matrix import PostgresMatrixStore
            from deeptutor.reading.catalog_models import IngestionStatus, SourceKind
            from deeptutor.services.cron import get_cron_service
            from deeptutor.services.cron.service import CronOwner, CronSchedule
            from deeptutor.services.partners.runtime_status import (
                get_partner_runtime_status_repository,
            )
            from nio.crypto import OlmAccount

            container = get_application_container()
            await container.start()
            token_context = None
            try:
                token = await container.auth_provider.identity.login(
                    "admin", "administrator-123", client="zero-sqlite-runtime"
                )
                user = user_from_token_payload(await container.auth_provider.decode(token))
                token_context = set_current_user(user)

                store = container.store_provider.get()
                session = await store.create_session(title="zero sqlite")
                await store.add_message(session["id"], "user", "hello")
                turn = await store.create_turn(session["id"], capability="chat")
                await store.upsert_notebook_entries(
                    session["id"],
                    [
                        {{
                            "turn_id": turn["turn_id"],
                            "question_id": "q-zero",
                            "question": "2+2?",
                            "correct_answer": "4",
                            "user_answer": "4",
                            "is_correct": True,
                        }}
                    ],
                )
                assert (await store.list_notebook_entries())["total"] == 1

                learning = container.learning_provider.get()
                progress = LearningProgress(book_id="path-zero")
                await learning.run(lambda unit: unit.save(progress))
                loaded = await learning.run(lambda unit: unit.load("path-zero"))
                assert loaded.book_id == "path-zero"

                reading = container.reading_provider.get()
                await reading.run(
                    lambda unit: unit.upsert_material(
                        content_id="content-zero",
                        filename="zero.txt",
                        title="Zero SQLite",
                        source_kind=SourceKind.FILE,
                        status=IngestionStatus.READY,
                        material_id="material-zero",
                    )
                )
                workspace = await reading.run(
                    lambda unit: unit.create_workspace(
                        "Zero workspace", ["material-zero"], workspace_id="workspace-zero"
                    )
                )
                assert workspace.workspace_id == "workspace-zero"

                cron = get_cron_service()
                job = await cron.add_job(
                    name="zero-cron",
                    message="ping",
                    schedule=CronSchedule(kind="every", every_seconds=3600),
                    owner=CronOwner(kind="chat", session_id=session["id"]),
                )
                assert (await cron.get_job(job.id)).id == job.id

                partner_status = get_partner_runtime_status_repository()
                partner_status.set(
                    "partner-zero",
                    owner_id=user.id,
                    running=True,
                    state="running",
                    payload={{"channels": ["secret"], "public": "ok"}},
                )
                assert partner_status.get("partner-zero", owner_id=user.id)["running"] is True

                mn = container.postgres_runtime.marginnote_store_for_current_user("kb-zero")
                device, _token = mn.pair_device(device_name="Mac", device_kind="macos")
                result = mn.ingest(
                    SyncBatch(
                        device_id=device.device_id,
                        objects=[
                            MarginNoteObject(
                                object_id="note-zero",
                                object_type="note",
                                title="Matrix and PG",
                                content="stored in PG",
                                device_id=device.device_id,
                            )
                        ],
                    )
                )
                assert result.stored == 1
                assert mn.search("PG")[0]["object_id"] == "note-zero"

                matrix = PostgresMatrixStore(
                    "@bot:example.org",
                    "DEVICE-Z",
                    "ignored-by-pg",
                    "matrix-pickle-secret-000000000000000001",
                    "",
                    database=container.postgres_runtime.sync_db,
                    scope=container.postgres_runtime.scope_for_current_user(),
                    partner_id="matrix-zero",
                    encryption_secret="matrix-store-envelope-secret-000000000001",
                    secret_id="matrix-store:zero",
                    secret_version=1,
                )
                account = OlmAccount()
                matrix.save_account(account)
                matrix.save_encrypted_rooms({{"!room:example.org"}})
                matrix.save_sync_token("sync-zero")
                assert matrix.load_account().identity_keys == account.identity_keys
                assert matrix.load_encrypted_rooms() == {{"!room:example.org"}}
                assert matrix.load_sync_token() == "sync-zero"
            finally:
                if token_context is not None:
                    reset_current_user(token_context)
                await container.close()

        asyncio.run(main())

        if guard_hits != expected_guard_hits:
            raise AssertionError(f"business runtime attempted SQLite: {{guard_hits}}")

        home = Path({str(home)!r})
        leftovers = [
            str(path)
            for pattern in ("*.sqlite", "*.sqlite3", "*.db")
            for path in home.rglob(pattern)
        ]
        if leftovers:
            raise AssertionError("default runtime created SQLite artifacts: " + repr(leftovers))
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[3],
        env={
            "DEEPTUTOR_HOME": str(home),
            "DEEPTUTOR_POSTGRES_CONFIG": str(config),
            "DEEPTUTOR_DATABASE_URL": runtime_dsn,
            "DEEPTUTOR_MIGRATION_DATABASE_URL": pg_dsn,
            "TEST_SIGNING_SECRET": "s" * 48,
            "TEST_AUTH_EPOCH_SECRET": "epoch-zero-sqlite-runtime",
            "TEST_BOOTSTRAP_SECRET": "b" * 48,
            "PYTHONPATH": ".:extensions/enterprise/src",
        },
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr
