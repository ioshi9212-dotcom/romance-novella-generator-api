from __future__ import annotations

import json

from app.config import SESSIONS_DIR
from tests.conftest import (
    activate_session,
    bootstrap_parts,
    create_empty_legacy_session,
    create_session,
)


def _save_minimal_questionnaire(client, headers, session_id):
    response = client.put(
        f"/v1/sessions/{session_id}/questionnaire",
        headers=headers,
        json={"phase": "initial", "raw_answers": "Остальное придумай сам."},
    )
    assert response.status_code == 200, response.text


def test_missing_generated_character_fields_require_director_repair(client, auth_headers):
    session_id = create_session(client, auth_headers)
    _save_minimal_questionnaire(client, auth_headers, session_id)
    parts = bootstrap_parts("W")
    npc_save = None
    for part in parts:
        if part.get("part_id") == "npc":
            part["content"].pop("voice")
        response = client.post(
            f"/v1/sessions/{session_id}/bootstrap/parts",
            headers=auth_headers,
            json=part,
        )
        assert response.status_code == 200, response.text
        if part.get("part_id") == "npc":
            npc_save = response.json()
    assert npc_save is not None
    assert "Director must invent character.npc.voice before confirmation" in npc_save["warnings"]
    validation = client.post(
        f"/v1/sessions/{session_id}/bootstrap/validate",
        headers=auth_headers,
    ).json()
    assert validation["ready"] is False
    repair = "character.npc.voice must be invented and saved by the director"
    assert repair in validation["errors"]
    assert repair in validation["director_repairs"]
    assert validation["user_questions"] == []
    assert validation["next_action"] == "repair_bootstrap"

    repaired = client.post(
        f"/v1/sessions/{session_id}/bootstrap/parts",
        headers=auth_headers,
        json={
            "part_type": "character",
            "part_id": "npc",
            "merge": True,
            "content": json.dumps(
                {"voice": {"style": "спокойный, без лишней откровенности"}},
                ensure_ascii=False,
            ),
        },
    )
    assert repaired.status_code == 200, repaired.text
    assert repaired.json()["merged"] is True
    after_repair = client.post(
        f"/v1/sessions/{session_id}/bootstrap/validate",
        headers=auth_headers,
    ).json()
    assert after_repair["ready"] is True
    assert after_repair["next_action"] == "show_review"
    confirmation = client.post(
        f"/v1/sessions/{session_id}/bootstrap/confirm",
        headers=auth_headers,
    )
    assert confirmation.status_code == 200, confirmation.text
    assert confirmation.json()["status"] == "active"
    saved_card = json.loads(
        (SESSIONS_DIR / session_id / "state" / "characters" / "npc.json").read_text()
    )
    assert saved_card["voice"]["style"] == "спокойный, без лишней откровенности"


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


def test_missing_session_presentation_uses_safe_defaults(client, auth_headers):
    session_id = create_session(client, auth_headers)
    _save_minimal_questionnaire(client, auth_headers, session_id)
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
    assert validation.json()["ready"] is True
    root = SESSIONS_DIR / session_id
    profile = json.loads((root / "bootstrap" / "draft" / "profile.json").read_text())
    assert profile["presentation"]["scene_body_min_chars"] == 1500
    assert profile["presentation"]["footer_relationships"] is True
    assert profile["pov_control"]["allow_minor_dialogue"] is True
    assert profile["pov_control"]["user_only_consequential_choices"] is True


def test_long_questionnaire_json_text_normalization_and_retry_are_safe(client, auth_headers):
    session_id = create_empty_legacy_session(client, auth_headers)
    raw_answers = "Романтика, современный город. " + "я" * 60000
    payload = {
        "phase": "initial",
        "raw_answers": raw_answers,
        "normalized": json.dumps({"genre": "романтика"}, ensure_ascii=False),
        "unknown_fields": "внешность второстепенного персонажа",
    }

    first = client.put(
        f"/v1/sessions/{session_id}/questionnaire",
        headers=auth_headers,
        json=payload,
    )
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "building"
    assert first.json()["questionnaire_entry_count"] == 1
    assert first.json()["last_questionnaire_entry_id"]

    retry = client.put(
        f"/v1/sessions/{session_id}/questionnaire",
        headers=auth_headers,
        json=payload,
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["questionnaire_entry_count"] == 1
    assert retry.json()["last_questionnaire_entry_id"] == first.json()[
        "last_questionnaire_entry_id"
    ]

    questionnaire = json.loads(
        (SESSIONS_DIR / session_id / "bootstrap" / "questionnaire.json").read_text()
    )
    entry = questionnaire["entries"][0]
    assert entry["raw_answers"] == raw_answers
    assert entry["normalized"] == {"genre": "романтика"}
    assert entry["unknown_fields"] == ["внешность второстепенного персонажа"]
    assert questionnaire["completion_policy"]["ordinary_missing_fields"] == (
        "director_invents_and_saves"
    )

    recovery_session = create_empty_legacy_session(client, auth_headers)
    malformed = client.put(
        f"/v1/sessions/{recovery_session}/questionnaire",
        headers=auth_headers,
        json={
            "phase": "initial",
            "raw_answers": "Мой полный ответ остаётся видимым и сохранённым.",
            "normalized": "{broken wrapper",
        },
    )
    assert malformed.status_code == 200, malformed.text
    recovered = json.loads(
        (
            SESSIONS_DIR
            / recovery_session
            / "bootstrap"
            / "questionnaire.json"
        ).read_text()
    )
    assert recovered["entries"][0]["normalized"] == {}


def test_only_material_contradictions_request_user_clarification(client, auth_headers):
    session_id = create_empty_legacy_session(client, auth_headers)
    response = client.put(
        f"/v1/sessions/{session_id}/questionnaire",
        headers=auth_headers,
        json={
            "phase": "initial",
            "raw_answers": "Пусть остальное генератор придумает сам",
            "unknown_fields": ["точная дата", "имена NPC", "место"],
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "building"

    conflicted_session = create_empty_legacy_session(client, auth_headers)
    conflicted = client.put(
        f"/v1/sessions/{conflicted_session}/questionnaire",
        headers=auth_headers,
        json={
            "phase": "initial",
            "raw_answers": "Рейтинг одновременно 12+ и максимально откровенный 18+",
            "contradictions": "Какой рейтинг считать обязательным?",
        },
    )
    assert conflicted.status_code == 200
    assert conflicted.json()["status"] == "clarification"
    validation = client.post(
        f"/v1/sessions/{conflicted_session}/bootstrap/validate",
        headers=auth_headers,
    ).json()
    assert validation["next_action"] == "ask_user"
    assert validation["user_questions"] == ["Какой рейтинг считать обязательным?"]


def test_bootstrap_merge_preserves_existing_generated_and_user_fields(client, auth_headers):
    session_id = create_session(client, auth_headers)
    initial = client.post(
        f"/v1/sessions/{session_id}/bootstrap/parts",
        headers=auth_headers,
        json={
            "part_type": "profile",
            "content": json.dumps(
                {
                    "title": "Гроза",
                    "genre": ["романтика", "мистика"],
                    "tone": ["напряжённый"],
                    "pov_id": "emily",
                    "boundaries": [],
                    "start": {"situation": "утро перед сменой"},
                },
                ensure_ascii=False,
            ),
        },
    )
    assert initial.status_code == 200, initial.text
    repair = client.post(
        f"/v1/sessions/{session_id}/bootstrap/parts",
        headers=auth_headers,
        json={
            "part_type": "profile",
            "merge": True,
            "content": json.dumps(
                {"prose_style": {"pace": "slow"}},
                ensure_ascii=False,
            ),
        },
    )
    assert repair.status_code == 200, repair.text
    profile = json.loads(
        (SESSIONS_DIR / session_id / "bootstrap" / "draft" / "profile.json").read_text()
    )
    assert profile["title"] == "Гроза"
    assert profile["genre"] == ["романтика", "мистика"]
    assert profile["boundaries"] == []
    assert profile["prose_style"]["pace"] == "slow"
    assert profile["prose_style"]["mode"] == "serious_literary"


def test_invalid_initial_relationship_is_rejected_before_confirmation(client, auth_headers):
    session_id = create_session(client, auth_headers)
    response = client.post(
        f"/v1/sessions/{session_id}/bootstrap/parts",
        headers=auth_headers,
        json={
            "part_type": "character",
            "part_id": "npc",
            "content": json.dumps(
                {
                    "id": "npc",
                    "name": "Николь",
                    "initial_relationships": [
                        {
                            "to_character_id": "pov",
                            "metric": "trust",
                            "value": "сильное доверие",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
        },
    )
    assert response.status_code == 422
    assert "must be an integer" in response.text


def test_normalized_questionnaire_fact_must_reach_bootstrap_state(client, auth_headers):
    session_id = create_empty_legacy_session(client, auth_headers)
    questionnaire = client.put(
        f"/v1/sessions/{session_id}/questionnaire",
        headers=auth_headers,
        json={
            "phase": "initial",
            "raw_answers": "Главной героине 37 лет.",
            "normalized": {"pov": {"age": 37}},
        },
    )
    assert questionnaire.status_code == 200, questionnaire.text

    for part in bootstrap_parts("AGE"):
        if part.get("part_id") == "pov":
            part["content"]["age"] = 19
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
    assert validation["ready"] is False
    mismatch = "questionnaire.normalized.pov.age=37 must be represented"
    assert any(mismatch in item for item in validation["director_repairs"])
    assert validation["user_questions"] == []

    repaired = client.post(
        f"/v1/sessions/{session_id}/bootstrap/parts",
        headers=auth_headers,
        json={
            "part_type": "character",
            "part_id": "pov",
            "merge": True,
            "content": json.dumps({"age": 37}, ensure_ascii=False),
        },
    )
    assert repaired.status_code == 200, repaired.text
    after = client.post(
        f"/v1/sessions/{session_id}/bootstrap/validate",
        headers=auth_headers,
    ).json()
    assert after["ready"] is True


def test_confirmation_creates_per_session_state(client, auth_headers):
    session_id = activate_session(client, auth_headers, "C")
    root = SESSIONS_DIR / session_id
    assert json.loads((root / "state" / "lore.json").read_text())["summary"] == "Уникальный мир C"
    assert (root / "state" / "characters" / "pov.json").is_file()
    assert (root / "state" / "knowledge" / "npc.json").is_file()
    source = json.loads((root / "state" / "questionnaire_source.json").read_text())
    assert source["entries"][0]["raw_answers"] == "Романтика в современном городе"
    assert not (root / "state" / "canon_canvas.json").exists()


def test_sessions_do_not_share_lore(client, auth_headers):
    first = activate_session(client, auth_headers, "ONE")
    second = activate_session(client, auth_headers, "TWO")
    first_lore = json.loads((SESSIONS_DIR / first / "state" / "lore.json").read_text())
    second_lore = json.loads((SESSIONS_DIR / second / "state" / "lore.json").read_text())
    assert first_lore["summary"] == "Уникальный мир ONE"
    assert second_lore["summary"] == "Уникальный мир TWO"
    assert first_lore != second_lore
