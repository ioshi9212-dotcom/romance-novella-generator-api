from __future__ import annotations

from copy import deepcopy

from fastapi.testclient import TestClient

from app.main import _prepare_bootstrap_preview_payload, app
from app.validators import validate_bootstrap_result
from tests.test_smoke import _valid_bootstrap


FORBIDDEN_PLACEHOLDER_BITS = (
    "будет уточняться",
    "не указано",
    "не задано",
    "стартовая локация",
    "начало истории",
)


def _broken_but_repairable_bootstrap() -> dict:
    bootstrap = deepcopy(_valid_bootstrap())
    for card in bootstrap["characters"].values():
        card["goal"] = ""
        card["past_short"] = "прошлое будет уточняться сценами"

    # A second same-role NPC reproduces duplicate fallback behavior profiles.
    bootstrap["characters"]["coworker_02"] = {
        "id": "coworker_02",
        "name": "Jules Mercer",
        "role": "coworker",
        "age": 31,
        "introduced": True,
        "known_to_player": True,
        "appearance": {
            "height": "medium",
            "build": "compact",
            "hair": "brown",
            "eyes": "hazel",
            "face": "alert",
            "style": "work shirt and dark trousers",
        },
        "personality": {"core": ["practical"], "flaws": ["pushes too hard"], "speech": "brief"},
        "goal": "личная цель будет уточняться сценами",
        "past_short": "",
        "habits": [],
        "skills": [],
        "connections": [],
    }

    bootstrap["story_plan"]["setting_summary"] = "сеттинг будет уточняться"
    bootstrap["story_plan"]["main_premise"] = "будет уточняться"
    bootstrap["story_plan"]["protagonist_start"] = "—"
    bootstrap["story_plan"]["player_goal"] = "не указано"
    bootstrap["story_plan"]["central_conflict"] = "будет уточняться"
    bootstrap["story_plan"]["central_question"] = "—"
    bootstrap["story_plan"]["opening_scene_intent"] = "начать первую сцену"

    bootstrap["current_state"]["time"] = "не задано"
    bootstrap["current_state"]["location"] = "стартовая локация"
    bootstrap["current_state"]["weather"] = "не указано"
    bootstrap["current_state"]["scene_state"] = "начало истории"
    bootstrap["current_state"]["scene_goal"] = "начать первую сцену"
    bootstrap["current_state"]["outfit"] = "не задано"
    return bootstrap


def _assert_concrete(value: object) -> None:
    text = str(value or "").strip().lower()
    assert text
    assert not any(bit in text for bit in FORBIDDEN_PLACEHOLDER_BITS)


def test_prepare_bootstrap_preview_repairs_all_validator_placeholder_conflicts():
    prepared = _prepare_bootstrap_preview_payload(_broken_but_repairable_bootstrap())

    errors = validate_bootstrap_result(prepared)
    assert errors == []

    for card in prepared["characters"].values():
        _assert_concrete(card["goal"])
        _assert_concrete(card["past_short"])

    for key in (
        "setting_summary",
        "main_premise",
        "protagonist_start",
        "player_goal",
        "central_conflict",
        "central_question",
        "opening_scene_intent",
    ):
        _assert_concrete(prepared["story_plan"][key])

    for key in ("time", "location", "weather", "scene_state", "outfit"):
        _assert_concrete(prepared["current_state"][key])

    significant_npc_signatures = []
    for character_id, card in prepared["characters"].items():
        if character_id == prepared["protagonist"]["id"]:
            continue
        if card.get("cast_status") not in {"known_core", "known_support", "hidden_core"}:
            continue
        behavior = card["behavior"]
        speech = card["speech_profile"]
        significant_npc_signatures.append((
            behavior["care_style"],
            behavior["conflict_style"],
            behavior["stress_response"],
            speech["baseline"],
        ))
    assert len(significant_npc_signatures) == len(set(significant_npc_signatures))


def test_bootstrap_preview_returns_user_visible_preview_instead_of_422_for_repairable_draft():
    client = TestClient(app)
    created = client.post("/api/v1/sessions", json={
        "genre": "romance with urban mysticism",
        "setting_request": "modern city and ordinary work",
        "protagonist_request": "adult heroine with a difficult private life",
        "mode": "gpt_actions",
    })
    assert created.status_code == 200
    session_id = created.json()["session_id"]

    response = client.post(
        f"/api/v1/sessions/{session_id}/bootstrap-preview",
        json={"bootstrap_json": _broken_but_repairable_bootstrap()},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "bootstrap_review_pending"
    assert body["must_show_to_user"] is True
    assert body["can_confirm"] is True
    assert "Черновик новеллы" in body["message_to_user"]
    assert "будет уточняться" not in body["message_to_user"].lower()
