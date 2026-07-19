from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.bootstrap_setup import build_setup_preview
from app.session_manager import SessionManager


def test_partial_raw_questionnaire_answer_starts_session_and_is_preserved_exactly():
    raw_start_text = (
        "Хочу современную романтическую мистику.\n"
        "Героине 21 год, она работает в кофейне.\n"
        "Характер и остальных персонажей придумай сам.\n"
        "Нельзя: архивы, организации и магические коробки."
    )

    response = TestClient(app).post(
        "/api/v1/sessions",
        json={"raw_start_text": raw_start_text, "mode": "gpt_actions"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "bootstrap_pending"
    assert body["session_id"]
    assert all(line in body["bootstrap_prompt"] for line in raw_start_text.splitlines())

    stored = SessionManager().storage.read_json(body["session_id"], "user_request.json")
    assert stored["raw_start_text"] == raw_start_text


def test_any_explicit_partial_field_is_enough_to_start_bootstrap():
    response = TestClient(app).post(
        "/api/v1/sessions",
        json={"genre": "медленный роман", "mode": "gpt_actions"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "bootstrap_pending"


def test_explicit_request_to_invent_everything_is_not_treated_as_missing_input():
    response = TestClient(app).post(
        "/api/v1/sessions",
        json={"raw_start_text": "Придумай всё сам, но сделай персонажей живыми.", "mode": "gpt_actions"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "bootstrap_pending"


def test_random_choice_starts_bootstrap_and_is_preserved_as_the_source_request():
    response = TestClient(app).post(
        "/api/v1/sessions",
        json={"raw_start_text": "Рандом", "mode": "gpt_actions"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "bootstrap_pending"
    assert "Рандом" in body["bootstrap_prompt"]
    assert "всё неуказанное придумай" in body["bootstrap_prompt"]
    stored = SessionManager().storage.read_json(body["session_id"], "user_request.json")
    assert stored["raw_start_text"] == "Рандом"


def test_questionnaire_visibly_offers_random_generation():
    response = TestClient(app).post(
        "/api/v1/sessions",
        json={"raw_start_text": "начнем", "mode": "gpt_actions"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "needs_questionnaire"
    assert "Рандом" in body["questionnaire"]


def test_custom_gpt_passes_the_exact_questionnaire_answer_to_create_session():
    instructions = Path("gpt/custom_gpt_instructions.md").read_text(encoding="utf-8")

    assert 'createSession(raw_start_text="<точный полный ответ пользователя>"' in instructions
    assert "Незаполненные пункты не являются ошибкой" in instructions


def test_setup_preview_reviews_structured_canon_without_echoing_raw_questionnaire():
    raw_start_text = (
        "Героине 21 год, у неё зелёно-янтарные глаза.\n"
        "Характер: гиперзабота, мягкий юмор, не умеет отказывать.\n"
        "Остальных персонажей придумай сам."
    )
    bootstrap = {
        "protagonist": {"id": "pc_01"},
        "characters": {
            "pc_01": {
                "id": "pc_01",
                "name": "Mira Vale",
                "display_name": "Мира Вейл",
                "role": "player_character",
                "cast_status": "player",
                "age": 21,
                "appearance": {"eyes": "зелёно-янтарные"},
                "personality": {
                    "core": ["гиперзабота", "мягкий юмор"],
                    "flaws": ["не умеет отказывать"],
                },
            }
        },
        "current_state": {"player_character_id": "pc_01"},
        "story_plan": {},
        "relationships": {},
    }

    preview = build_setup_preview(bootstrap, user_request={"raw_start_text": raw_start_text})

    assert "### Исходная анкета пользователя" not in preview
    assert raw_start_text not in preview
    for fact in ("21", "зелёно-янтарные", "гиперзабота", "мягкий юмор", "не умеет отказывать"):
        assert fact in preview
