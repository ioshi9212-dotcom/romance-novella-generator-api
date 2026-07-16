from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.session_manager import SessionManager
from tests.test_turn_persistence_audit import (
    _create_active_session,
    _read_full_prompt,
    _scene_for_turn,
)


def _apply_turn(client: TestClient, session_id: str, turn_number: int) -> str:
    player_input = f"(повторный контрольный ход {turn_number})"
    turn = client.post(
        f"/api/v1/sessions/{session_id}/turn",
        json={"player_input": player_input, "mode": "gpt_actions"},
    )
    assert turn.status_code == 200, turn.text
    turn_payload = turn.json()
    full_prompt = _read_full_prompt(client, session_id, turn_payload)

    applied = client.post(
        f"/api/v1/sessions/{session_id}/apply-turn-result",
        json={
            "turn_id": turn_payload["turn_id"],
            "scene_response": _scene_for_turn(player_input, turn_number),
        },
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "applied", applied.text
    return full_prompt


def test_turn_maintenance_repeats_at_every_ten_and_fifteen_turns():
    client = TestClient(app)
    session_id = _create_active_session(client)
    manager = SessionManager()

    prompts_after_completed_checkpoints: dict[int, str] = {}
    for turn_number in range(1, 31):
        full_prompt = _apply_turn(client, session_id, turn_number)
        if turn_number in {11, 16, 21}:
            prompts_after_completed_checkpoints[turn_number] = full_prompt

        current_state = manager.storage.read_json(session_id, "current_state.json")
        maintenance = current_state["maintenance"]

        if turn_number == 10:
            assert maintenance["state_recovery_audit_completed_turn"] == 10
            assert maintenance["state_recovery_audit_due"] is False
        elif turn_number == 15:
            assert maintenance["state_compaction_cleanup_completed_turn"] == 15
            assert maintenance["state_compaction_cleanup_due"] is False
        elif turn_number == 20:
            assert maintenance["state_recovery_audit_completed_turn"] == 20
            assert maintenance["state_recovery_audit_due"] is False
        elif turn_number == 30:
            assert maintenance["state_recovery_audit_completed_turn"] == 30
            assert maintenance["state_compaction_cleanup_completed_turn"] == 30
            assert maintenance["state_recovery_audit_due"] is False
            assert maintenance["state_compaction_cleanup_due"] is False

    continuity = manager.storage.read_json(session_id, "continuity.json")
    audits = continuity["state_recovery_audits"]
    compaction_reports = continuity["state_compaction_reports"]

    assert [item["turn"] for item in audits] == [10, 20, 30]
    assert [item["status"] for item in audits] == ["ok", "ok", "ok"]
    assert [item["turn"] for item in compaction_reports] == [15, 30]
    assert [item["status"] for item in compaction_reports] == ["ok", "ok"]

    maintenance_events = [
        (item.get("turn"), item.get("type"), item.get("status"))
        for item in continuity["maintenance_events"]
        if item.get("type") in {"state_recovery_audit", "state_compaction_cleanup"}
    ]
    assert maintenance_events == [
        (10, "state_recovery_audit", "ok"),
        (15, "state_compaction_cleanup", "ok"),
        (20, "state_recovery_audit", "ok"),
        (30, "state_recovery_audit", "ok"),
        (30, "state_compaction_cleanup", "ok"),
    ]

    assert '"state_recovery_audit_due":false' in prompts_after_completed_checkpoints[11]
    assert '"state_recovery_audit_completed_turn":10' in prompts_after_completed_checkpoints[11]
    assert '"state_compaction_cleanup_due":false' in prompts_after_completed_checkpoints[16]
    assert '"state_compaction_cleanup_completed_turn":15' in prompts_after_completed_checkpoints[16]
    assert '"state_recovery_audit_due":false' in prompts_after_completed_checkpoints[21]
    assert '"state_recovery_audit_completed_turn":20' in prompts_after_completed_checkpoints[21]

    # Build the next real processTurn prompt after the double checkpoint at turn 30.
    turn_31 = client.post(
        f"/api/v1/sessions/{session_id}/turn",
        json={"player_input": "(проверить контекст после тридцатого хода)", "mode": "gpt_actions"},
    )
    assert turn_31.status_code == 200, turn_31.text
    prompt_31 = _read_full_prompt(client, session_id, turn_31.json())
    assert '"state_recovery_audit_due":false' in prompt_31
    assert '"state_compaction_cleanup_due":false' in prompt_31
    assert '"state_recovery_audit_completed_turn":30' in prompt_31
    assert '"state_compaction_cleanup_completed_turn":30' in prompt_31

    scene_history = manager.storage.read_json(session_id, "scene_history.json")
    turns = manager.storage.read_json(session_id, "turns.json")
    knowledge = manager.storage.read_knowledge(session_id)["coworker_01"]

    assert len(scene_history) <= 6
    assert len(turns) <= 8
    assert scene_history[-1]["turn"] == 30
    assert turns[-1]["turn"] == 30
    assert "Рен знает устойчивый факт хода 1" in knowledge["knows"]
    assert "Рен знает устойчивый факт хода 30" in knowledge["knows"]
