from __future__ import annotations

from fastapi.testclient import TestClient

import app.main as main_module
from app.main import TURN_PROMPT_CHUNK_SIZE, app
from app.session_manager import SessionManager
from tests.test_smoke import _valid_bootstrap


SAFE_ACTION_RESPONSE_BYTES = 8_000
PLAYER_INPUT = "(начать первую сцену)"


def _create_active_session(client: TestClient) -> str:
    created = client.post(
        "/api/v1/sessions",
        json={
            "genre": "mystery drama",
            "setting_request": "stormy coastal town",
            "protagonist_request": "adult forensic photographer",
            "romance_request": "slow burn",
            "mode": "gpt_actions",
        },
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
    assert confirmed.json()["status"] == "active"
    return session_id


def _large_prompt_result(*_args, **_kwargs):
    return {
        "status": "gpt_actions_prompt_ready",
        "scene": None,
        "scene_prompt": ("PROMPT-LINE-" + "x" * 88 + "\n") * 180,
        "diagnostics": {
            "compact_prompt_chars": 18_000,
            "next_required_action": "read chunks then apply",
        },
    }


def test_process_turn_returns_one_small_copy_of_first_chunk(monkeypatch):
    client = TestClient(app)
    session_id = _create_active_session(client)
    monkeypatch.setattr(main_module, "process_turn_gpt_actions", _large_prompt_result)

    response = client.post(
        f"/api/v1/sessions/{session_id}/turn",
        json={"player_input": PLAYER_INPUT, "mode": "gpt_actions"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert "scene_prompt" not in payload
    assert "scene" not in payload
    assert len(payload["scene_prompt_chunk"]) <= TURN_PROMPT_CHUNK_SIZE
    assert payload["prompt_chunk_count"] > 1
    assert len(response.content) < SAFE_ACTION_RESPONSE_BYTES

    next_chunk = client.get(
        f"/api/v1/sessions/{session_id}/turn-prompt-chunk",
        params={"turn_id": payload["turn_id"], "chunk_index": 1},
    )
    assert next_chunk.status_code == 200, next_chunk.text
    assert len(next_chunk.json()["scene_prompt_chunk"]) <= TURN_PROMPT_CHUNK_SIZE
    assert len(next_chunk.content) < SAFE_ACTION_RESPONSE_BYTES


def test_retry_repairs_legacy_large_pending_chunks(monkeypatch):
    client = TestClient(app)
    session_id = _create_active_session(client)
    monkeypatch.setattr(main_module, "process_turn_gpt_actions", _large_prompt_result)

    first = client.post(
        f"/api/v1/sessions/{session_id}/turn",
        json={"player_input": PLAYER_INPUT, "mode": "gpt_actions"},
    )
    assert first.status_code == 200, first.text

    manager = SessionManager()
    pending = manager.storage.read_json(session_id, "pending_turn.json")
    full_prompt = "".join(pending["prompt_chunks"])
    pending["prompt_chunks"] = [full_prompt[:12_000], full_prompt[12_000:]]
    pending["prompt_chunk_count"] = len(pending["prompt_chunks"])
    pending["prompt_chunk_size"] = 12_000
    manager.storage.write_json(session_id, "pending_turn.json", pending)

    retried = client.post(
        f"/api/v1/sessions/{session_id}/turn",
        json={"player_input": PLAYER_INPUT, "mode": "gpt_actions"},
    )
    assert retried.status_code == 200, retried.text
    assert len(retried.json()["scene_prompt_chunk"]) <= TURN_PROMPT_CHUNK_SIZE
    assert len(retried.content) < SAFE_ACTION_RESPONSE_BYTES

    repaired = manager.storage.read_json(session_id, "pending_turn.json")
    assert repaired["prompt_chunk_size"] == TURN_PROMPT_CHUNK_SIZE
    assert max(map(len, repaired["prompt_chunks"])) <= TURN_PROMPT_CHUNK_SIZE
    assert repaired.get("prompt_chunks_repaired_at")
