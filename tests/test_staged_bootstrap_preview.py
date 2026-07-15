from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.novella_openapi_actions import build_openapi_actions
from tests.test_smoke import _valid_bootstrap


SINGLE_SECTIONS = (
    "protagonist",
    "story_plan",
    "director_bible",
    "current_state",
    "future_locks",
    "continuity",
)
ENTRY_SECTIONS = ("characters", "relationships", "knowledge", "npc_state")


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


def test_staged_bootstrap_end_to_end_creates_visible_preview():
    client = TestClient(app)
    session_id = _create_session(client)
    bootstrap = _valid_bootstrap()
    bootstrap.setdefault("director_bible", {})

    for section in SINGLE_SECTIONS:
        response = client.post(
            f"/api/v1/sessions/{session_id}/bootstrap-part",
            json={"section": section, "value": bootstrap[section]},
        )
        assert response.status_code == 200, response.text

    for section in ENTRY_SECTIONS:
        entries = bootstrap[section]
        if not entries:
            response = client.post(
                f"/api/v1/sessions/{session_id}/bootstrap-part",
                json={"section": section, "value": {}},
            )
            assert response.status_code == 200, response.text
            continue
        for item_id, value in entries.items():
            response = client.post(
                f"/api/v1/sessions/{session_id}/bootstrap-part",
                json={"section": section, "item_id": item_id, "value": value},
            )
            assert response.status_code == 200, response.text

    progress = response.json()["progress"]
    assert progress["ready_to_finalize"] is True
    assert progress["entry_counts"]["characters"] == len(bootstrap["characters"])

    final = client.post(f"/api/v1/sessions/{session_id}/bootstrap-preview-finalize")
    assert final.status_code == 200, final.text
    payload = final.json()
    assert payload["status"] == "bootstrap_review_pending"
    assert payload["must_show_to_user"] is True
    assert payload["wait_for_confirmation"] is True
    assert payload["message_to_user"] == payload["preview"]
    assert payload["diagnostics"]["staged_bootstrap"] is True

    session = client.get(f"/api/v1/sessions/{session_id}")
    assert session.status_code == 200
    assert session.json()["status"] == "bootstrap_review_pending"
