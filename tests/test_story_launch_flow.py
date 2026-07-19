from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from tests.test_smoke import _valid_bootstrap


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


def test_random_launch_uses_one_preview_and_exposes_only_one_eligible_future_seed():
    client = TestClient(app)
    created = client.post(
        "/api/v1/sessions",
        json={"raw_start_text": "Рандом", "mode": "gpt_actions"},
    )
    assert created.status_code == 200, created.text
    session_id = created.json()["session_id"]

    bootstrap = _valid_bootstrap()
    bootstrap["future_locks"] = {
        "hidden_character_seeds": [
            {
                "id": "planned_guest_seed",
                "role": "будущий значимый незнакомец",
                "story_function": "создать личное препятствие и возможную медленную романтическую линию",
                "entry_condition": "после первого устойчивого мистического следа",
                "earliest_turn": 1,
                "priority": 100,
                "notes_for_engine": "PLANNED_SEED_MARKER",
            },
            {
                "id": "later_guest_seed",
                "role": "поздний участник конфликта",
                "story_function": "осложнить последствия в следующем акте",
                "entry_condition": "не раньше четвёртого хода",
                "earliest_turn": 4,
                "priority": 80,
                "notes_for_engine": "LATER_SEED_MARKER",
            },
        ],
        "do_not_reveal_yet": ["Не раскрывать источник мистики в первой сцене."],
    }

    preview = client.post(
        f"/api/v1/sessions/{session_id}/bootstrap-preview",
        json={"bootstrap_json": bootstrap},
    )
    assert preview.status_code == 200, preview.text
    visible_preview = preview.json()["message_to_user"]
    assert "planned_guest_seed" not in visible_preview
    assert "later_guest_seed" not in visible_preview

    confirmed = client.post(
        f"/api/v1/sessions/{session_id}/bootstrap-confirm",
        json={"confirmation_text": "подтверждаю"},
    )
    assert confirmed.status_code == 200, confirmed.text

    turn = client.post(
        f"/api/v1/sessions/{session_id}/turn",
        json={"player_input": "(начать первую сцену)", "mode": "gpt_actions"},
    )
    assert turn.status_code == 200, turn.text
    prompt = _collect_turn_prompt(client, session_id, turn.json())

    assert "planned_guest_seed" in prompt
    assert "PLANNED_SEED_MARKER" in prompt
    assert "source_seed_id" in prompt
    assert "later_guest_seed" not in prompt
    assert "LATER_SEED_MARKER" not in prompt
    assert "pending_character_seed_count" in prompt
