from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.bootstrap_normalizer import normalize_bootstrap_json
from app.bootstrap_staging import STAGED_BOOTSTRAP_FILE
from app.session_manager import SessionManager
from app.novella_openapi_actions import build_openapi_actions
from tests.test_smoke import _valid_bootstrap


def _create_session(client: TestClient) -> str:
    response = client.post(
        "/api/v1/sessions",
        json={
            "genre": "melodrama",
            "setting_request": "modern office with quiet mysticism",
            "protagonist_request": "adult woman avoiding home after work",
            "romance_request": "slow burn with an inconvenient coworker",
            "mode": "gpt_actions",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "bootstrap_pending"
    return payload["session_id"]


def test_actions_schema_exposes_small_staged_bootstrap_calls():
    contract = build_openapi_actions("https://example.invalid")
    paths = contract["paths"]
    schemas = contract["components"]["schemas"]

    save_action = paths["/api/v1/sessions/{session_id}/bootstrap-part"]["post"]
    finalize_action = paths["/api/v1/sessions/{session_id}/bootstrap-preview-finalize"]["post"]
    assert save_action["operationId"] == "saveBootstrapPart"
    assert finalize_action["operationId"] == "finalizeBootstrapPreview"
    assert save_action["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SaveBootstrapPartRequest"
    }

    request_schema = schemas["SaveBootstrapPartRequest"]
    assert request_schema["required"] == ["section", "value"]
    assert request_schema["properties"]["value"]["type"] == "object"
    assert "bootstrap_json" not in request_schema["properties"]
    assert request_schema["properties"]["delete_fields"]["items"]["type"] == "string"
    assert request_schema["properties"]["replace"]["type"] == "boolean"


def test_repeated_character_part_deep_merges_instead_of_erasing_card_fields():
    client = TestClient(app)
    session_id = _create_session(client)
    original = {
        "id": "pc_01",
        "name": "Mira Vale",
        "role": "player_character",
        "behavior": {
            "care_style": "приносит еду без просьбы",
            "stress_response": "пытается всё удержать сама",
        },
    }

    first = client.post(
        f"/api/v1/sessions/{session_id}/bootstrap-part",
        json={"section": "characters", "item_id": "pc_01", "value": original},
    )
    assert first.status_code == 200

    edit = client.post(
        f"/api/v1/sessions/{session_id}/bootstrap-part",
        json={
            "section": "characters",
            "item_id": "pc_01",
            "value": {"behavior": {"stress_response": "резко замолкает и уходит в работу"}},
        },
    )
    assert edit.status_code == 200

    draft = SessionManager().storage.read_json(session_id, STAGED_BOOTSTRAP_FILE)
    stored = draft["characters"]["pc_01"]
    assert stored["name"] == "Mira Vale"
    assert stored["role"] == "player_character"
    assert stored["behavior"] == {
        "care_style": "приносит еду без просьбы",
        "stress_response": "резко замолкает и уходит в работу",
    }


def test_bootstrap_part_supports_explicit_nested_field_deletion():
    client = TestClient(app)
    session_id = _create_session(client)
    client.post(
        f"/api/v1/sessions/{session_id}/bootstrap-part",
        json={
            "section": "characters",
            "item_id": "pc_01",
            "value": {"id": "pc_01", "name": "Mira Vale", "temporary": {"note": "remove me"}},
        },
    )

    edit = client.post(
        f"/api/v1/sessions/{session_id}/bootstrap-part",
        json={
            "section": "characters",
            "item_id": "pc_01",
            "value": {},
            "delete_fields": ["temporary.note"],
        },
    )

    assert edit.status_code == 200
    stored = SessionManager().storage.read_json(session_id, STAGED_BOOTSTRAP_FILE)
    assert stored["characters"]["pc_01"]["temporary"] == {}


def test_relationship_item_id_recovers_from_character_fields():
    client = TestClient(app)
    session_id = _create_session(client)

    response = client.post(
        f"/api/v1/sessions/{session_id}/bootstrap-part",
        json={
            "section": "relationships",
            "item_id": "elena_voss_lucas_hale",
            "value": {
                "pair_id": "elena_voss_lucas_hale",
                "character_a": "elena_voss",
                "character_b": "lucas_hale",
                "type": "colleagues",
            },
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["stored"] is True
    assert payload["item_id"] == "elena_voss__lucas_hale"
    assert payload["progress"]["entry_counts"]["relationships"] == 1


def test_relationship_item_id_conflict_is_rejected():
    client = TestClient(app)
    session_id = _create_session(client)

    response = client.post(
        f"/api/v1/sessions/{session_id}/bootstrap-part",
        json={
            "section": "relationships",
            "item_id": "elena_voss__lucas_hale",
            "value": {
                "pair_id": "elena_voss__marcus_hale",
                "character_a": "elena_voss",
                "character_b": "lucas_hale",
            },
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "relationship_id_conflict"


def test_relationship_item_id_without_recovery_fields_is_rejected():
    client = TestClient(app)
    session_id = _create_session(client)

    response = client.post(
        f"/api/v1/sessions/{session_id}/bootstrap-part",
        json={
            "section": "relationships",
            "item_id": "elena_voss_lucas_hale",
            "value": {"type": "colleagues"},
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "invalid_relationship_item_id"
    assert detail["expected"] == "<character_a>__<character_b>"


def test_finalize_rejects_incomplete_staged_bootstrap():
    client = TestClient(app)
    session_id = _create_session(client)

    stored = client.post(
        f"/api/v1/sessions/{session_id}/bootstrap-part",
        json={"section": "protagonist", "value": {"id": "pc_01", "name": "Mira Vale", "role": "player_character"}},
    )
    assert stored.status_code == 200
    assert stored.json()["progress"]["ready_to_finalize"] is False

    final = client.post(f"/api/v1/sessions/{session_id}/bootstrap-preview-finalize")
    assert final.status_code == 409
    detail = final.json()["detail"]
    assert detail["code"] == "bootstrap_parts_incomplete"
    assert "characters" in detail["missing_sections"]


def test_normalizer_uses_the_single_player_card_without_a_protagonist_copy():
    normalized = normalize_bootstrap_json({
        "characters": {
            "emily_hart": {
                "name": "Emily Hart",
                "role": "player_character",
                "cast_status": "player",
                "appearance": {"eyes": "зелёно-янтарные"},
            },
        },
        "story_plan": {},
        "current_state": {},
    })

    assert normalized["protagonist"]["id"] == "emily_hart"
    assert normalized["current_state"]["player_character_id"] == "emily_hart"
    assert normalized["characters"]["emily_hart"]["appearance"]["eyes"] == "зелёно-янтарные"
    assert "pc_01" not in normalized["characters"]


def test_normalizer_deep_merges_legacy_split_player_cards():
    normalized = normalize_bootstrap_json({
        "protagonist": {
            "id": "emily_hart",
            "name": "Emily Hart",
            "past_short": "Конкретная биография из анкеты.",
            "appearance": {"height": "невысокая", "build": "миниатюрная"},
        },
        "characters": {
            "emily_hart": {
                "role": "player_character",
                "cast_status": "player",
                "appearance": {"eyes": "зелёно-янтарные"},
            },
        },
        "story_plan": {},
        "current_state": {"player_character_id": "emily_hart"},
    })

    card = normalized["characters"]["emily_hart"]
    assert card["past_short"] == "Конкретная биография из анкеты."
    assert card["appearance"]["height"] == "невысокая"
    assert card["appearance"]["build"] == "миниатюрная"
    assert card["appearance"]["eyes"] == "зелёно-янтарные"


def test_minimal_staged_core_creates_playable_preview_and_derives_runtime_state():
    client = TestClient(app)
    session_id = _create_session(client)
    bootstrap = _valid_bootstrap()

    for item_id, value in bootstrap["characters"].items():
        response = client.post(
            f"/api/v1/sessions/{session_id}/bootstrap-part",
            json={"section": "characters", "item_id": item_id, "value": value},
        )
        assert response.status_code == 200, response.text
    for section in ("story_plan", "current_state"):
        response = client.post(
            f"/api/v1/sessions/{session_id}/bootstrap-part",
            json={"section": section, "value": bootstrap[section]},
        )
        assert response.status_code == 200, response.text

    progress = response.json()["progress"]
    assert progress["ready_to_finalize"] is True
    assert progress["entry_counts"]["characters"] == len(bootstrap["characters"])
    assert progress["stored_sections"] == ["characters", "current_state", "story_plan"]

    final = client.post(f"/api/v1/sessions/{session_id}/bootstrap-preview-finalize")
    assert final.status_code == 200, final.text
    payload = final.json()
    assert payload["status"] == "bootstrap_review_pending"
    assert payload["must_show_to_user"] is True
    assert payload["wait_for_confirmation"] is True
    assert payload["message_to_user"] == payload["preview"]
    assert payload["diagnostics"]["staged_bootstrap"] is True
    assert "### Исходные пожелания пользователя" in payload["message_to_user"]
    assert "modern office with quiet mysticism" in payload["message_to_user"]

    pending = SessionManager().storage.read_json(session_id, "pending_bootstrap.json")
    player_id = pending["current_state"]["player_character_id"]
    assert pending["protagonist"]["id"] == player_id
    assert set(pending["knowledge"]) >= set(pending["characters"])
    assert pending["relationships"]
    assert pending["npc_state"]
    assert pending["director_bible"]["event_queue"]
    assert isinstance(pending["future_locks"], dict)
    assert isinstance(pending["continuity"], dict)

    session = client.get(f"/api/v1/sessions/{session_id}")
    assert session.status_code == 200
    assert session.json()["status"] == "bootstrap_review_pending"
