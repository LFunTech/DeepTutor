from __future__ import annotations

import math

import psycopg
import pytest

from deeptutor.capabilities.marginnote4.models import (
    CARD,
    MINDMAP_NODE,
    NOTE,
    MarginNoteObject,
    SyncBatch,
)
from deeptutor.persistence.postgres.marginnote import PostgresMarginNoteStore

pytestmark = pytest.mark.asyncio


def _seed_objects(device_id: str) -> list[MarginNoteObject]:
    return [
        MarginNoteObject(
            object_id="note1",
            object_type=NOTE,
            title="Photosynthesis",
            content="Plants convert light into chemical energy.",
            excerpt="Green plants use sunlight.",
            document_id="doc1",
            document_title="Biology Textbook",
            page=42,
            tags=["biology", "plants"],
            links=["card1"],
            color="yellow",
            created_at="2025-01-01T00:00:00Z",
            updated_at="2025-01-02T00:00:00Z",
            device_id=device_id,
            raw={"source": "mn4"},
        ),
        MarginNoteObject(
            object_id="card1",
            object_type=CARD,
            title="What is photosynthesis?",
            content="Process of converting light energy to chemical energy",
            tags=["biology"],
            links=["note1"],
            device_id=device_id,
        ),
        MarginNoteObject(
            object_id="node1",
            object_type=MINDMAP_NODE,
            title="Energy Conversion",
            content="Central concept linking photosynthesis and respiration",
            links=["note1", "card1"],
            device_id=device_id,
        ),
    ]


def test_pg_marginnote_pairing_hash_and_scope_isolation(
    migrated_pg, business_sync_database, business_actors
) -> None:
    owner = business_actors.tenants[0].owners[0]
    other_owner = business_actors.tenants[0].owners[1]
    store = PostgresMarginNoteStore(business_sync_database, owner.scope, kb_id="biology")

    device, token = store.pair_device(device_name="MacBook", device_kind="macos")

    assert len(token) > 20
    assert store.verify_token(device.device_id, token) is True
    assert store.verify_token(device.device_id, "wrong") is False
    assert PostgresMarginNoteStore(
        business_sync_database, other_owner.scope, kb_id="biology"
    ).verify_token(device.device_id, token) is False
    assert PostgresMarginNoteStore(
        business_sync_database, owner.scope, kb_id="chemistry"
    ).verify_token(device.device_id, token) is False

    with psycopg.connect(migrated_pg.admin_dsn, row_factory=psycopg.rows.dict_row) as connection:
        row = connection.execute(
            """
            SELECT tenant_id, owner_id, kb_id, device_id, token_hash, active
              FROM enterprise.marginnote_devices
             WHERE tenant_id=%s AND owner_id=%s AND kb_id=%s AND device_id=%s
            """,
            (owner.tenant_id, owner.user_id, "biology", device.device_id),
        ).fetchone()
    assert row is not None
    assert row["token_hash"] != token
    assert len(row["token_hash"]) == 64
    assert str(row["tenant_id"]) == owner.tenant_id
    assert row["owner_id"] == owner.user_id
    assert row["kb_id"] == "biology"
    assert row["active"] is True

    assert [d.device_id for d in store.list_devices()] == [device.device_id]
    assert store.revoke_device(device.device_id) is True
    assert store.verify_token(device.device_id, token) is False
    assert store.revoke_device(device.device_id) is False


def test_pg_marginnote_ingest_search_cursor_tombstone_and_atomicity(
    migrated_pg, business_sync_database, business_actors
) -> None:
    owner = business_actors.tenants[0].owners[0]
    store = PostgresMarginNoteStore(business_sync_database, owner.scope, kb_id="biology")
    device, _token = store.pair_device(device_name="iPad", device_kind="ipados")

    result = store.ingest(SyncBatch(device_id=device.device_id, objects=_seed_objects(device.device_id)))

    assert result.stored == 3
    assert result.updated == 0
    assert result.deleted == 0
    assert result.new_cursor
    assert store.get_cursor(device.device_id) == result.new_cursor
    assert store.count(device_id=device.device_id) == 3
    assert {hit["object_id"] for hit in store.search("photosynthesis")} == {
        "note1",
        "card1",
        "node1",
    }
    assert store.list_documents(device_id=device.device_id) == [
        {"document_id": "doc1", "title": "Biology Textbook", "count": 1}
    ]
    assert {tag["tag"]: tag["count"] for tag in store.collect_tags(device_id=device.device_id)} == {
        "biology": 2,
        "plants": 1,
    }
    assert {item["object_id"] for item in store.linked_objects("note1", device_id=device.device_id)} == {
        "card1",
        "node1",
    }

    deleted = store.ingest(SyncBatch(device_id=device.device_id, cursor=result.new_cursor, deleted_ids=["note1"]))
    assert deleted.deleted == 1
    assert store.get("note1", device_id=device.device_id) is None
    with psycopg.connect(migrated_pg.admin_dsn, row_factory=psycopg.rows.dict_row) as connection:
        tombstone = connection.execute(
            """
            SELECT deleted_at FROM enterprise.marginnote_tombstones
             WHERE tenant_id=%s AND owner_id=%s AND kb_id=%s
               AND device_id=%s AND object_id='note1'
            """,
            (owner.tenant_id, owner.user_id, "biology", device.device_id),
        ).fetchone()
    assert tombstone is not None

    cursor_before = store.get_cursor(device.device_id)
    bad_tags = MarginNoteObject(
        object_id="bad-tags",
        object_type=NOTE,
        title="bad",
        tags={"not": "a-list"},  # type: ignore[arg-type]
        device_id=device.device_id,
    )
    good_after_bad = MarginNoteObject(
        object_id="must-rollback",
        object_type=NOTE,
        title="must not persist",
        device_id=device.device_id,
    )
    with pytest.raises(psycopg.errors.CheckViolation):
        store.ingest(SyncBatch(device_id=device.device_id, cursor=cursor_before, objects=[good_after_bad, bad_tags]))
    assert store.get_cursor(device.device_id) == cursor_before
    assert store.get("must-rollback", device_id=device.device_id) is None
    assert store.get("bad-tags", device_id=device.device_id) is None


def test_pg_marginnote_requires_existing_device_and_preserves_device_dimension(
    business_sync_database, business_actors
) -> None:
    owner = business_actors.tenants[0].owners[0]
    store = PostgresMarginNoteStore(business_sync_database, owner.scope, kb_id="biology")
    first, _ = store.pair_device(device_name="Mac")
    second, _ = store.pair_device(device_name="iPad")

    obj_one = MarginNoteObject(
        object_id="shared-id",
        object_type=NOTE,
        title="from first",
        device_id=first.device_id,
    )
    obj_two = MarginNoteObject(
        object_id="shared-id",
        object_type=NOTE,
        title="from second",
        device_id=second.device_id,
    )
    store.ingest(SyncBatch(device_id=first.device_id, objects=[obj_one]))
    store.ingest(SyncBatch(device_id=second.device_id, objects=[obj_two]))

    assert store.get("shared-id", device_id=first.device_id).title == "from first"
    assert store.get("shared-id", device_id=second.device_id).title == "from second"
    assert store.count() == 2

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        store.ingest(
            SyncBatch(
                device_id="unknown-device",
                objects=[
                    MarginNoteObject(
                        object_id="orphan",
                        object_type=NOTE,
                        title="orphan",
                        device_id="unknown-device",
                    )
                ],
            )
        )
    assert store.get_cursor("unknown-device") == ""

    invalid_clock_store = PostgresMarginNoteStore(
        business_sync_database,
        owner.scope,
        kb_id="biology",
        clock=lambda: math.nan,
    )
    with pytest.raises(ValueError, match="finite non-negative"):
        invalid_clock_store.touch_device(first.device_id)
