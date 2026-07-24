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
