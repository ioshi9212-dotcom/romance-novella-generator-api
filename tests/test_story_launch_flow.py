from __future__ import annotations

from copy import deepcopy

from fastapi.testclient import TestClient

from app.main import app
from tests.test_smoke import _valid_bootstrap


def _hidden_card(character_id: str, name: str, marker: str) -> dict:
    card = deepcopy(_valid_bootstrap()["characters"]["coworker_01"])
    card.update({
        "id": character_id,
        "name": name,
        "display_name": name,
        "role": "future significant stranger",
        "cast_status": "hidden_core",
        "introduced": False,
        "known_to_player": False,
        "show_in_preview": False,
        "available_to_scene": False,
        "connections": [],
    })
    card["behavior"] = {
        "conflict_style": marker,
        "care_style": "проверяет безопасность действием, не объясняя мотив",
        "closeness_style": "держится рядом только пока решает собственную задачу",
        "touch_style": "останавливает жестом лишь при непосредственной опасности",
        "stress_response": "ускоряется и отдаёт короткие конкретные команды",
        "rejection_response": "отступает в моменте и меняет маршрут без объяснений",
        "change_inertia": "после ошибки сначала меняет тактику, но не убеждение",
        "inconvenient_pattern": "скрывает часть плана и этим создаёт недоверие",
    }
    return card


def _collect_turn_prompt(client: TestClient, session_id: str, response_body: dict) -> str:
    chunks = [response_body["scene_prompt"]]
    for chunk_index in range(1, response_body["prompt_chunk_count"]):
        chunk = client.get(
            f"/api/v1/sessions/{session_id}/turn-prompt-chunk",
            params={"turn_id": response_body["turn_id"], "chunk_index": chunk_index},
        )
        assert chunk.status_code == 200, chunk.text
        chunks.append(chunk.json()["scene_prompt_chunk"])
    return "".join(chunks)


def test_random_launch_preview_confirm_and_first_scene_load_only_relevant_cards():
    client = TestClient(app)
    created = client.post(
        "/api/v1/sessions",
        json={"raw_start_text": "Рандом", "mode": "gpt_actions"},
    )
    assert created.status_code == 200, created.text
    session_id = created.json()["session_id"]

    bootstrap = _valid_bootstrap()
    bootstrap["characters"]["planned_guest"] = _hidden_card(
        "planned_guest",
        "Adrian Cross",
        "PLANNED_CARD_BEHAVIOR_MARKER",
    )
    bootstrap["characters"]["unrelated_guest"] = _hidden_card(
        "unrelated_guest",
        "Nolan Pierce",
        "UNRELATED_CARD_BEHAVIOR_MARKER",
    )
    director_bible = {
        "world_truth": {
            "core_truth": "Офисные сбои имеют одну заранее определённую причину.",
            "hidden_cause": "Причина связана с прошлым героини, а не создаётся по ходу.",
            "world_rules": ["Каждый сбой оставляет наблюдаемый след."],
        },
        "planned_reveals": [
            {
                "id": "reveal_planned_guest",
                "reveal": "Разрешённое первое появление участника события.",
                "status": "available",
                "earliest_turn": 1,
                "related_character_ids": ["planned_guest"],
            },
            {
                "id": "reveal_unrelated_guest",
                "reveal": "Другой персонаж остаётся закрыт.",
                "status": "locked",
                "earliest_turn": 4,
                "related_character_ids": ["unrelated_guest"],
            },
        ],
        "event_queue": [
            {
                "id": "event_guest_entry",
                "title": "Причинный вход",
                "status": "ready",
                "priority": 100,
                "earliest_turn": 1,
                "participants": ["planned_guest"],
            },
            {
                "id": "event_office_cost",
                "title": "Цена задержки",
                "status": "planned",
                "priority": 70,
                "earliest_turn": 2,
                "participants": ["coworker_01"],
            },
            {
                "id": "event_later_guest",
                "title": "Поздний вход",
                "status": "planned",
                "priority": 60,
                "earliest_turn": 4,
                "participants": ["unrelated_guest"],
            },
        ],
    }

    for character_id, card in bootstrap["characters"].items():
        saved = client.post(
            f"/api/v1/sessions/{session_id}/bootstrap-part",
            json={"section": "characters", "item_id": character_id, "value": card},
        )
        assert saved.status_code == 200, saved.text
    for section, value in (
        ("story_plan", bootstrap["story_plan"]),
        ("current_state", bootstrap["current_state"]),
        ("director_bible", director_bible),
    ):
        saved = client.post(
            f"/api/v1/sessions/{session_id}/bootstrap-part",
            json={"section": section, "value": value},
        )
        assert saved.status_code == 200, saved.text

    preview = client.post(f"/api/v1/sessions/{session_id}/bootstrap-preview-finalize")
    assert preview.status_code == 200, preview.text
    assert "Adrian Cross" not in preview.json()["preview"]
    assert "Nolan Pierce" not in preview.json()["preview"]

    confirmed = client.post(
        f"/api/v1/sessions/{session_id}/bootstrap-confirm",
        json={"confirmation_text": "подтверждаю"},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "active"

    turn = client.post(
        f"/api/v1/sessions/{session_id}/turn",
        json={"player_input": "(начать первую сцену)", "mode": "gpt_actions"},
    )
    assert turn.status_code == 200, turn.text
    prompt = _collect_turn_prompt(client, session_id, turn.json())

    assert "PLANNED_CARD_BEHAVIOR_MARKER" in prompt
    assert "candidate_not_present_yet" in prompt
    assert "UNRELATED_CARD_BEHAVIOR_MARKER" not in prompt
