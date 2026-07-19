from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.main import app
from app.novella_openapi_actions import build_openapi_actions
from app.session_manager import SessionManager
from tests.test_smoke import _long_scene_response, _valid_bootstrap


def _active_session(client: TestClient) -> str:
    created = client.post(
        "/api/v1/sessions",
        json={"raw_start_text": "Современная романтическая мистика", "mode": "gpt_actions"},
    )
    assert created.status_code == 200, created.text
    session_id = created.json()["session_id"]
    preview = client.post(
        f"/api/v1/sessions/{session_id}/bootstrap-preview",
        json={"bootstrap_json": _valid_bootstrap()},
    )
    assert preview.status_code == 200, preview.text
    confirmed = client.post(
        f"/api/v1/sessions/{session_id}/bootstrap-confirm",
        json={"confirmation_text": "подтверждаю"},
    )
    assert confirmed.status_code == 200, confirmed.text
    return session_id


def _pending_turn(client: TestClient, session_id: str, player_input: str) -> str:
    response = client.post(
        f"/api/v1/sessions/{session_id}/turn",
        json={"player_input": player_input, "mode": "gpt_actions"},
    )
    assert response.status_code == 200, response.text
    return response.json()["turn_id"]


def test_apply_accepts_flat_scene_fields_and_builds_rendered_text_server_side():
    client = TestClient(app)
    session_id = _active_session(client)
    player_input = "(идти на смену к восьми утра)"
    turn_id = _pending_turn(client, session_id, player_input)
    scene_response = _long_scene_response(player_input)
    scene_response["scene"].pop("rendered_text", None)

    applied = client.post(
        f"/api/v1/sessions/{session_id}/apply-turn-result",
        json={"turn_id": turn_id, **scene_response},
    )

    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert body["turn_id"] == turn_id
    assert body["replayed"] is False
    assert body["must_show_to_user"] is True
    assert len(body["message_to_user"]) >= 1000
    assert "rendered_text" not in body


def test_apply_accepts_legacy_wrapper_with_spilled_root_fields():
    client = TestClient(app)
    session_id = _active_session(client)
    player_input = "(посмотреть на часы)"
    turn_id = _pending_turn(client, session_id, player_input)
    response = _long_scene_response(player_input)
    wrapped = {
        "turn_id": turn_id,
        "scene_response": {
            "response_version": response["response_version"],
            "player_input": response["player_input"],
            "scene": response["scene"],
        },
        "summary": response["summary"],
        "important_facts": response["important_facts"],
        "witnesses": response["witnesses"],
        "proposed_updates": response["proposed_updates"],
        "safety_checks": response["safety_checks"],
    }

    applied = client.post(
        f"/api/v1/sessions/{session_id}/apply-turn-result",
        json=wrapped,
    )

    assert applied.status_code == 200, applied.text


def test_empty_director_patch_array_is_normalized_to_an_empty_object():
    client = TestClient(app)
    session_id = _active_session(client)
    player_input = "(открыть дверь)"
    turn_id = _pending_turn(client, session_id, player_input)
    response = _long_scene_response(player_input)
    response["proposed_updates"]["director_bible_patches"] = []

    applied = client.post(
        f"/api/v1/sessions/{session_id}/apply-turn-result",
        json={"turn_id": turn_id, **response},
    )

    assert applied.status_code == 200, applied.text


def test_duplicate_apply_replays_saved_output_without_advancing_state_twice():
    client = TestClient(app)
    session_id = _active_session(client)
    player_input = "(взять сумку)"
    turn_id = _pending_turn(client, session_id, player_input)
    response = _long_scene_response(player_input)
    payload = {"turn_id": turn_id, **response}

    first = client.post(f"/api/v1/sessions/{session_id}/apply-turn-result", json=payload)
    second = client.post(f"/api/v1/sessions/{session_id}/apply-turn-result", json=payload)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["replayed"] is True
    assert second.json()["message_to_user"] == first.json()["message_to_user"]
    state = SessionManager().storage.read_json(session_id, "current_state.json")
    assert state["turn_number"] == 1


def test_get_last_scene_recovers_the_exact_saved_visible_output():
    client = TestClient(app)
    session_id = _active_session(client)
    player_input = "(выйти из квартиры)"
    turn_id = _pending_turn(client, session_id, player_input)
    response = _long_scene_response(player_input)
    applied = client.post(
        f"/api/v1/sessions/{session_id}/apply-turn-result",
        json={"turn_id": turn_id, **response},
    )
    assert applied.status_code == 200, applied.text

    recovered = client.get(f"/api/v1/sessions/{session_id}/last-scene")

    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["available"] is True
    assert recovered.json()["turn_id"] == turn_id
    assert recovered.json()["message_to_user"] == applied.json()["message_to_user"]


def test_debug_dump_is_bounded_and_contains_transport_state_not_full_cards():
    client = TestClient(app)
    session_id = _active_session(client)
    debug = client.get(f"/api/v1/sessions/{session_id}/debug-dump")

    assert debug.status_code == 200, debug.text
    body = debug.json()
    assert len(json.dumps(body, ensure_ascii=False)) < 24_000
    assert isinstance(body["characters"].get("count"), int)
    assert "inner_logic" not in json.dumps(body["characters"], ensure_ascii=False)
    assert "last_scene_available" in body["pending_turn"]


def test_actions_use_flat_apply_payload_and_publish_single_bootstrap_preview_action():
    contract = build_openapi_actions("https://example.invalid")
    paths = contract["paths"]
    schema = contract["components"]["schemas"]["ApplyTurnResultRequest"]

    assert "/api/v1/sessions/{session_id}/bootstrap-preview" in paths
    assert "/api/v1/sessions/{session_id}/bootstrap-part" not in paths
    assert "/api/v1/sessions/{session_id}/bootstrap-preview-finalize" not in paths
    assert "/api/v1/sessions/{session_id}/last-scene" in paths
    assert "scene_response" not in schema["required"]
    assert "scene_response" not in schema["properties"]
    assert {
        "turn_id",
        "response_version",
        "player_input",
        "scene",
        "summary",
        "important_facts",
        "witnesses",
        "proposed_updates",
        "safety_checks",
    } <= set(schema["required"])
    assert "rendered_text" not in schema["properties"]["scene"]["properties"]
    assert len(json.dumps(contract, ensure_ascii=False)) < 55_000
