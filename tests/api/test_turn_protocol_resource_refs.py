from __future__ import annotations

from pydantic import TypeAdapter

from deeptutor.api.contracts.turn_protocol import ClientCommand


def test_start_turn_accepts_empty_resource_ids_for_ws_contract():
    command = TypeAdapter(ClientCommand).validate_python(
        {
            "type": "start_turn",
            "protocol_version": "2.0",
            "content": "hello",
            "resource_ids": [],
        }
    )

    assert command.to_payload()["resource_ids"] == []
