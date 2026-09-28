"""治理报表不得把数据库中的未知旧枚举当作正常结果返回。"""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from deeptutor.persistence.postgres.governance import RuntimeGovernanceStore
from deeptutor.persistence.postgres.scope import TenantScope


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, *, audits=(), objects=(), cleanup=()):
        self.audits = list(audits)
        self.objects = list(objects)
        self.cleanup = list(cleanup)

    async def execute(self, statement, _params):
        if "FROM enterprise.runtime_audit_events" in statement:
            return _Cursor(self.audits)
        if "FROM enterprise.resource_objects" in statement:
            return _Cursor(self.objects)
        if "FROM enterprise.resource_cleanup_jobs" in statement:
            return _Cursor(self.cleanup)
        raise AssertionError(f"unexpected governance query: {statement}")


class _Database:
    def __init__(self, connection):
        self.connection = connection

    @asynccontextmanager
    async def transaction(self, _scope):
        yield self.connection


def _governance(connection):
    scope = TenantScope("10000000-0000-0000-0000-000000000001", "owner")
    return RuntimeGovernanceStore(SimpleNamespace(db=_Database(connection), scope=scope))


@pytest.mark.asyncio
async def test_audit_list_rejects_unknown_persisted_scope_kind():
    row = {
        "id": "audit-1",
        "event_kind": "settings.saved",
        "actor_id": "owner",
        "scope_kind": "future-scope",
        "scope_id": "",
        "resource_kind": "runtime_setting",
        "resource_id": "key",
        "summary": {},
        "created_at": "2026-09-28T00:00:00Z",
    }
    with pytest.raises(ValueError, match="unsupported governance scope"):
        await _governance(_Connection(audits=[row])).list_audit()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("objects", "cleanup", "message"),
    [
        (
            [{"resource_kind": "generated_artifact", "state": "future-state", "count": 1, "size_bytes": 1}],
            [],
            "resource state is unknown",
        ),
        (
            [],
            [{"state": "future-state", "count": 1}],
            "resource cleanup job state is unknown",
        ),
    ],
)
async def test_usage_summary_rejects_unknown_persisted_resource_states(objects, cleanup, message):
    with pytest.raises(ValueError, match=message):
        await _governance(_Connection(objects=objects, cleanup=cleanup)).usage_summary()
