import json
from copy import deepcopy
from pathlib import Path

import yaml

from app.main import app
from tests.conftest import create_current_session


def _finalize_current_payload(client, payload):
    current = deepcopy(payload)
    current["runtime_contract_version"] = "2.0"
    raw = json.dumps(current, ensure_ascii=False, separators=(",", ":"))
    chunks = [raw[index : index + 1000] for index in range(0, len(raw), 1000)]
    started = client.post(
        "/api/v1/session-transfers", json={"total_chunks": len(chunks)}
    )
    assert started.status_code == 200, started.text
    transfer_id = started.json()["transfer_id"]
    for index, content in enumerate(chunks):
        uploaded = client.post(
            f"/api/v1/session-transfers/{transfer_id}/chunks",
            json={"chunk_index": index, "content": content},
        )
        assert uploaded.status_code == 200, uploaded.text
    return client.post(f"/api/v1/session-transfers/{transfer_id}/finalize")


def test_actions_have_no_auth_and_only_session_scoped_runtime_operations() -> None:
    app.openapi_schema = None
    schema = app.openapi()
    assert schema["security"] == []
    assert "securitySchemes" not in schema.get("components", {})

    operation_ids = {
        operation["operationId"]
        for path_item in schema["paths"].values()
        for operation in path_item.values()
    }
    assert operation_ids == {
        "createSession",
        "startSessionTransfer",
        "uploadSessionTransferChunk",
        "finalizeSessionTransfer",
        "getTurnPacket",
        "getTurnPacketChunk",
        "getSceneCharacterBundle",
        "getSceneCharacterBundleChunk",
        "commitTurn",
        "getAuditPacket",
        "getAuditPacketChunk",
        "commitAudit",
        "getChronologyPage",
    }
    assert not any("latest" in path.lower() for path in schema["paths"])
    assert not any("list" in operation.lower() for operation in operation_ids)
    for path_item in schema["paths"].values():
        for operation in path_item.values():
            assert operation["security"] == []


def test_every_openapi_array_has_items_and_object_has_properties() -> None:
    app.openapi_schema = None
    schema = app.openapi()

    def walk(value):
        if isinstance(value, dict):
            if value.get("type") == "array":
                assert "items" in value
            if value.get("type") == "object":
                assert "properties" in value
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(schema)


def test_committed_actions_schema_matches_application() -> None:
    app.openapi_schema = None
    generated = app.openapi()
    committed = yaml.safe_load(Path("openapi.yaml").read_text(encoding="utf-8"))
    assert committed == generated


def test_create_session_requires_positive_player_confirmation(
    client, session_payload
) -> None:
    missing = dict(session_payload)
    missing.pop("player_confirmation")
    assert client.post("/api/v1/sessions", json=missing).status_code == 422

    negative = {
        **session_payload,
        "player_confirmation": "Не подтверждаю, исправь превью",
    }
    response = client.post("/api/v1/sessions", json=negative)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PLAYER_CONFIRMATION_REQUIRED"


def test_create_session_rejects_incomplete_player_character_and_location(
    client, session_payload
) -> None:
    incomplete_character = deepcopy(session_payload)
    incomplete_character["characters"][0]["card"].pop("appearance")
    assert client.post("/api/v1/sessions", json=incomplete_character).status_code == 422

    incomplete_location = deepcopy(session_payload)
    incomplete_location["locations"][0]["state"]["canon"].pop("layout")
    assert client.post("/api/v1/sessions", json=incomplete_location).status_code == 422



def test_create_session_accepts_legacy_action_without_director_plan(
    client, service, session_payload
) -> None:
    legacy_payload = deepcopy(session_payload)
    legacy_payload.pop("director_plan")

    response = client.post("/api/v1/sessions", json=legacy_payload)

    assert response.status_code == 200, response.text
    stored = service.storage.read_json(
        response.json()["session_id"], "state/director_plan.json"
    )
    assert stored["active_threads"] == []
    assert stored["character_agendas"] == []
    assert stored["event_windows"] == []
    assert stored["collision_points"] == []
    assert stored["offscreen_events"] == []
    assert stored["consequences_without_pov"] == []
    assert stored["possible_pov_contacts"] == []


def test_openapi_requires_current_contract_but_runtime_keeps_legacy_compatibility() -> None:
    app.openapi_schema = None
    schema = app.openapi()
    request_schema = schema["components"]["schemas"]["CreateSessionRequest"]

    assert "director_plan" in request_schema["properties"]
    assert "director_plan" in request_schema["required"]
    assert "setup_source" in request_schema["properties"]
    assert "setup_source" in request_schema["required"]
    assert "runtime_contract_version" in request_schema["required"]
    assert request_schema["properties"]["runtime_contract_version"]["enum"] == [
        "2.0"
    ]


def test_current_contract_rejects_empty_director_plan(
    client, session_payload
) -> None:
    current = deepcopy(session_payload)
    current["runtime_contract_version"] = "2.0"

    direct = client.post("/api/v1/sessions", json=current)
    assert direct.status_code == 409
    assert direct.json()["error"]["code"] == "SESSION_TRANSFER_REQUIRED"

    rejected = _finalize_current_payload(client, current)
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "DIRECTOR_PLAN_INCOMPLETE"

    current["director_plan"]["active_threads"] = [
        {
            "thread_id": "thread_main",
            "current_question": "Что нарушило обычное утро?",
            "current_pressure": "Начальная ситуация требует реакции",
            "status": "active",
        }
    ]
    current["director_plan"]["character_agendas"] = [
        {
            "character_id": "char_chloe",
            "current_goal": "Поговорить с Эмили",
            "next_plausible_action": "Начать неудобный разговор",
            "conditions": [],
        }
    ]
    accepted = create_current_session(client, current)
    assert accepted["creation_verified"] is True


def test_turn_packet_marks_full_character_bundles_required_for_scene(
    client, session_payload
) -> None:
    offscreen = deepcopy(session_payload["characters"][1])
    offscreen["character_id"] = "char_ryan"
    offscreen["card"]["character_id"] = "char_ryan"
    offscreen["card"]["identity"]["name"] = "Райан"
    offscreen["current_state"]["current_location_id"] = "loc_elsewhere"
    session_payload["characters"].append(offscreen)
    created = client.post("/api/v1/sessions", json=session_payload)
    assert created.status_code == 200, created.text
    session_id = created.json()["session_id"]

    first = client.post(
        f"/api/v1/sessions/{session_id}/turn-packet",
        json={"player_input": "Продолжить разговор", "mode": "new"},
    )
    assert first.status_code == 200, first.text
    chunks = [first.json()["content"]]
    for index in range(1, first.json()["chunk_count"]):
        chunk = client.get(
            f"/api/v1/sessions/{session_id}/turn-packets/"
            f"{first.json()['packet_id']}/chunks/{index}"
        )
        assert chunk.status_code == 200, chunk.text
        chunks.append(chunk.json()["content"])
    packet = json.loads("".join(chunks))

    assert packet["scene_focus"]["pov_character_id"] == "char_emily"
    assert packet["scene_focus"]["required_full_character_ids"] == [
        "char_emily",
        "char_chloe",
    ]
    emily = next(
        item for item in packet["state"]["characters"]
        if item["character_id"] == "char_emily"
    )
    assert emily["card"]["personality"]["inner_character"]
    assert "current_state" in emily
    assert "knowledge" in emily
    assert "relationships" in emily
    assert {
        item["character_id"] for item in packet["state"]["characters"]
    } == {"char_emily", "char_chloe"}
    assert "char_ryan" in packet["state"]["manifest"]["character_ids"]

def test_validation_error_does_not_echo_large_rejected_payload(
    client, session_payload
) -> None:
    invalid = deepcopy(session_payload)
    invalid["characters"][0]["card"]["card_hint"] = "x" * 3000
    invalid["characters"][0]["card"]["biography"] = ["x" * 100_000]
    invalid["characters"][0]["card"]["personality"] = None

    response = client.post("/api/v1/sessions", json=invalid)

    assert response.status_code == 422
    assert len(response.content) < 10_000
    body = response.json()
    assert body["error"]["code"] == "REQUEST_VALIDATION_FAILED"
    assert body["error"]["issues"] == [
        {
            "location": "body.characters.0.card",
            "message": (
                "Value error, important and player-defined cards require: personality"
            ),
            "type": "value_error",
        }
    ]
    assert "input" not in response.text
