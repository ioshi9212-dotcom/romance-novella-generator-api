from fastapi.testclient import TestClient

from app.config import Settings
from app.fast_audit_service import FastAuditNovellaService
from app.main import app
from tests.conftest import collect_packet, commit_next_turn, complete_checklist, create_session


def _client(tmp_path) -> TestClient:
    app.state.service = FastAuditNovellaService(
        Settings(
            data_dir=tmp_path / "fast-audit-data",
            public_base_url="https://example.test",
            packet_chunk_chars=4000,
        )
    )
    return TestClient(app)


def test_fast_audit_uses_compact_snapshot_and_releases_turn_16(tmp_path, session_payload) -> None:
    client = _client(tmp_path)
    session_id = create_session(client, session_payload)

    for turn_number in range(1, 16):
        commit_next_turn(
            client,
            session_id,
            player_input=f"Тестовый ход {turn_number}",
            event_text=f"Событие {turn_number}",
        )

    packet = collect_packet(
        client,
        session_id,
        client.get(f"/api/v1/sessions/{session_id}/audit-packet"),
    )

    assert packet["audit_mode"] == "fast_chat_reconciliation"
    assert packet["chat_turns_are_primary_review_source"] is True
    assert "full_turns_current_revisions" not in packet
    assert "character_familiarity_audit" not in packet
    assert len(packet["turn_summaries_backup"]) == 15
    assert all("scene_output" not in item for item in packet["turn_summaries_backup"])
    assert len(packet["persisted_chronology_for_cycle"]) == 15

    completed = client.post(
        f"/api/v1/sessions/{session_id}/audits/commit",
        json={
            "audit_id": packet["audit_id"],
            "expected_state_revision": packet["expected_state_revision"],
            "checklist": complete_checklist(),
            "findings": {"result": "Быстрая сверка: пропусков не найдено"},
        },
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["audit_complete"] is True
    assert completed.json()["next_turn_number"] == 16

    next_packet = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": "Продолжить после быстрой сверки"},
        ),
    )
    assert next_packet["turn_number"] == 16
    assert next_packet["cycle_position"] == 1
