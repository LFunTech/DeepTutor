"""Matrix 信任状态由程序校验；移除数据库枚举约束后未知值仍须关闭访问。"""

from types import SimpleNamespace

import pytest

pytest.importorskip("nio")

from nio.crypto import TrustState  # noqa: E402

from deeptutor.persistence.postgres.matrix import PostgresMatrixStore  # noqa: E402


class _Connection:
    def __init__(self, state):
        self.state = state
        self.queries = []

    def execute(self, query, values):
        self.queries.append(query)
        return SimpleNamespace(fetchone=lambda: {"state": self.state})


def _store(connection):
    return SimpleNamespace(
        _run=lambda operation: operation(connection),
        _account_values=lambda: ("tenant", "owner", "partner", "user", "device"),
        _now_ms=lambda: 1,
        _device_exists=lambda _connection, _device: True,
    )


def test_unknown_persisted_matrix_trust_state_fails_closed_for_read_and_write():
    connection = _Connection("trusted-by-unknown-writer")
    store = _store(connection)
    device = SimpleNamespace(user_id="@alice:example", id="ALICE")

    with pytest.raises(RuntimeError, match="invalid Matrix device trust state"):
        PostgresMatrixStore._is_trust(store, device, TrustState.verified)
    with pytest.raises(RuntimeError, match="invalid Matrix device trust state"):
        PostgresMatrixStore._set_trust(store, device, TrustState.verified)
    assert all("INSERT INTO" not in query for query in connection.queries)


def test_invalid_matrix_trust_write_state_is_rejected_before_database_call():
    connection = _Connection("verified")
    store = _store(connection)
    device = SimpleNamespace(user_id="@alice:example", id="ALICE")

    with pytest.raises(ValueError, match="invalid Matrix device trust state"):
        PostgresMatrixStore._set_trust(store, device, "trusted")
    assert connection.queries == []
