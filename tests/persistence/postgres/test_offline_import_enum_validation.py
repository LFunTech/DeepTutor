"""历史数据导入不得把未知业务状态默默映射成有效状态。"""

import pytest

from deeptutor.persistence.postgres.offline_import.pocketbase_import import _allowed_status


@pytest.mark.parametrize("status", [None, "", "paused", "COMPLETED", 123])
def test_pocketbase_unknown_turn_status_blocks_import(status):
    with pytest.raises(ValueError, match="unknown PocketBase turn status"):
        _allowed_status(status)


@pytest.mark.parametrize(
    "status", ["queued", "running", "waiting_input", "completed", "cancelled", "failed"]
)
def test_pocketbase_known_turn_status_is_preserved(status):
    assert _allowed_status(status) == status
