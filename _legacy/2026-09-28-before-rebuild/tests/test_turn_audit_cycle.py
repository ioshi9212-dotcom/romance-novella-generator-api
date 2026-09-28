from tests.conftest import (
    collect_packet,
    commit_next_turn,
    complete_checklist,
    create_session,
)


def test_fifteen_turns_block_the_next_scene_until_full_audit(
    client, session_payload
) -> None:
    session_id = create_session(client, session_payload)

    for expected_turn in range(1, 16):
        packet, committed = commit_next_turn(
            client,
            session_id,
            player_input=f"Действие {expected_turn}",
        )
        assert packet["turn_number"] == expected_turn
        assert packet["cycle_position"] == expected_turn
        assert committed["last_completed_turn"] == expected_turn

    assert committed["audit_required"] is True
    assert committed["next_cycle_position"] is None

    blocked = client.post(
        f"/api/v1/sessions/{session_id}/turn-packet",
        json={"player_input": "Попытка написать ход 16"},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "AUDIT_REQUIRED"

    first = client.get(f"/api/v1/sessions/{session_id}/audit-packet")
    audit_packet = collect_packet(client, session_id, first)
    assert audit_packet["turn_from"] == 1
    assert audit_packet["turn_to"] == 15
    assert len(audit_packet["full_turns_current_revisions"]) == 15
    assert all(
        turn["scene_output"] for turn in audit_packet["full_turns_current_revisions"]
    )
    assert len(audit_packet["chronology"]) == 15

    checklist = complete_checklist()
    checklist["knowledge_boundaries"] = False
    rejected = client.post(
        f"/api/v1/sessions/{session_id}/audits/commit",
        json={
            "audit_id": audit_packet["audit_id"],
            "expected_state_revision": audit_packet["expected_state_revision"],
            "checklist": checklist,
            "findings": {"result": "Проверка намеренно не завершена"},
        },
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "AUDIT_CHECKLIST_INCOMPLETE"

    completed = client.post(
        f"/api/v1/sessions/{session_id}/audits/commit",
        json={
            "audit_id": audit_packet["audit_id"],
            "expected_state_revision": audit_packet["expected_state_revision"],
            "checklist": complete_checklist(),
            "findings": {"result": "Все 15 ходов сверены"},
            "state_updates": {
                "plot_state": {
                    "active_lines": [],
                    "resolved_history": ["Проверены ходы 1–15"],
                }
            },
        },
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["audit_complete"] is True
    assert completed.json()["last_audited_turn"] == 15
    assert completed.json()["next_turn_number"] == 16
    assert completed.json()["next_cycle_position"] == 1

    next_packet = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": "Продолжить после сверки"},
        ),
    )
    assert next_packet["turn_number"] == 16
    assert next_packet["cycle_position"] == 1
