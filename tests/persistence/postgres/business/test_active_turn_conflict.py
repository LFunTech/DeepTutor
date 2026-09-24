import pytest

from deeptutor.services.session.protocol import ActiveTurnConflict

pytestmark = pytest.mark.asyncio


async def test_postgres_active_turn_conflict_has_stable_error_code(
    pg_session_store_factory, business_actors
) -> None:
    store = pg_session_store_factory(business_actors.tenants[0].owners[0])
    session = await store.create_session(session_id="active-turn-conflict")
    active = await store.begin_turn(session["id"], capability="chat")

    with pytest.raises(ActiveTurnConflict) as excinfo:
        await store.begin_request(
            {
                "session_id": session["id"],
                "content": "第二轮应被拒绝",
                "capability": "chat",
            }
        )

    assert str(excinfo.value) == "Session already has an active turn"
    assert excinfo.value.turn_id == active["id"]
    assert excinfo.value.error_code == "session_active_turn"
    assert excinfo.value.retryable is True
