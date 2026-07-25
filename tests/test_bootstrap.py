from __future__ import annotations

import json

from app.config import SESSIONS_DIR
from tests.conftest import activate_session, bootstrap_parts, create_session


def test_missing_optional_character_fields_are_warnings(client, auth_headers):
    session_id = create_session(client, auth_headers)
    parts = bootstrap_parts("W")
    for part in parts:
        if part.get("part_id") == "npc":
            part["content"].pop("voice")
        response = client.post(
            f"/v1/sessions/{session_id}/bootstrap/parts",
            headers=auth_headers,
            json=part,
        )
        assert response.status_code == 200, response.text
    validation = client.post(
        f"/v1/sessions/{session_id}/bootstrap/validate",
        headers=auth_headers,
    ).json()
    assert validation["ready"] is True
    assert "character.npc.voice is not specified" in validation["warnings"]


def test_hidden_keys_cannot_enter_public_review(client, auth_headers):
    session_id = create_session(client, auth_headers)
    response = client.post(
        f"/v1/sessions/{session_id}/bootstrap/parts",
        headers=auth_headers,
        json={
            "part_type": "review",
            "content": {"title": "Тест", "hidden_canon": {"culprit": "npc"}},
        },
    )
    assert response.status_code == 422


def test_bootstrap_part_accepts_json_text_content(client, auth_headers):
    session_id = create_session(client, auth_headers)
    response = client.post(
        f"/v1/sessions/{session_id}/bootstrap/parts",
        headers=auth_headers,
        json={
            "part_type": "profile",
            "content": json.dumps(
                {
                    "title": "Текстовый JSON",
                    "genre": ["романтика"],
                    "tone": ["живой"],
                    "pov_id": "pov",
                    "boundaries": ["без насилия"],
                    "start": {"situation": "Утро в кафе"},
                    "naming": {
                        "origin": "foreign",
                        "script": "cyrillic",
                        "avoid_russian_names": True,
                    },
                    "presentation": {
                        "layout": "standard_novella",
                        "header_enabled": True,
                        "scene_body_min_chars": 1500,
                        "scene_body_max_chars": 2500,
                        "dialogue_format": "bold_name_italic_parenthetical_regular_speech",
                        "guidance": {"enabled": True, "items_per_section": 3},
                        "footer_state": True,
                        "footer_relationships": True,
                        "footer_turn": True,
                    },
                    "prose_style": {
                        "mode": "serious_literary",
                        "seriousness": "serious",
                        "description_detail": "detailed",
                        "literary_density": "literary",
                        "pace": "balanced",
                        "directorial_irony": "subtle",
                    },
                },
                ensure_ascii=False,
            ),
        },
    )
    assert response.status_code == 200, response.text
    root = SESSIONS_DIR / session_id
    saved = json.loads((root / "bootstrap" / "draft" / "profile.json").read_text())
    assert saved["title"] == "Текстовый JSON"


def test_bootstrap_part_rejects_invalid_json_text_content(client, auth_headers):
    session_id = create_session(client, auth_headers)
    response = client.post(
        f"/v1/sessions/{session_id}/bootstrap/parts",
        headers=auth_headers,
        json={"part_type": "profile", "content": "{not valid json"},
    )
    assert response.status_code == 422


def test_bootstrap_requires_session_presentation_settings(client, auth_headers):
    session_id = create_session(client, auth_headers)
    parts = bootstrap_parts("FORMAT")
    for part in parts:
        if part["part_type"] == "profile":
            part["content"].pop("presentation")
        response = client.post(
            f"/v1/sessions/{session_id}/bootstrap/parts",
            headers=auth_headers,
            json=part,
        )
        assert response.status_code == 200, response.text
    validation = client.post(
        f"/v1/sessions/{session_id}/bootstrap/validate",
        headers=auth_headers,
    )
    assert validation.status_code == 200
    assert validation.json()["ready"] is False
    assert "profile.presentation is required" in validation.json()["errors"]


def test_confirmation_creates_per_session_state(client, auth_headers):
    session_id = activate_session(client, auth_headers, "C")
    root = SESSIONS_DIR / session_id
    assert json.loads((root / "state" / "lore.json").read_text())["summary"] == "Уникальный мир C"
    assert (root / "state" / "characters" / "pov.json").is_file()
    assert (root / "state" / "knowledge" / "npc.json").is_file()
    assert not (root / "state" / "canon_canvas.json").exists()


def test_sessions_do_not_share_lore(client, auth_headers):
    first = activate_session(client, auth_headers, "ONE")
    second = activate_session(client, auth_headers, "TWO")
    first_lore = json.loads((SESSIONS_DIR / first / "state" / "lore.json").read_text())
    second_lore = json.loads((SESSIONS_DIR / second / "state" / "lore.json").read_text())
    assert first_lore["summary"] == "Уникальный мир ONE"
    assert second_lore["summary"] == "Уникальный мир TWO"
    assert first_lore != second_lore
