from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app
from app.writer_service import WriterFirstNovellaService
from tests.conftest import (
    collect_packet,
    commit_next_turn,
    complete_checklist,
    create_session,
)


def _writer_client(tmp_path) -> TestClient:
    app.state.service = WriterFirstNovellaService(
        Settings(
            data_dir=tmp_path / "writer-memory-data",
            public_base_url="https://example.test",
            packet_chunk_chars=4000,
        )
    )
    return TestClient(app)


def test_turn_packet_separates_spoken_text_from_parenthesized_action_and_tracks_continuity(
    tmp_path, session_payload
) -> None:
    client = _writer_client(tmp_path)
    session_id = create_session(client, session_payload)
    commit_next_turn(
        client,
        session_id,
        player_input="Поздороваться с Хлоей",
        event_text="Эмили и Хлоя продолжили уже начатое знакомство",
    )

    packet = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={
                "player_input": "Я сказала это вслух. (достать телефон и открыть переписку)"
            },
        ),
    )

    assert packet["player_input_map"]["spoken_segments"] == ["Я сказала это вслух."]
    assert packet["player_input_map"]["stage_directions"] == [
        "достать телефон и открыть переписку"
    ]
    assert packet["player_input_map"]["ordered_segments"] == [
        {"kind": "spoken", "text": "Я сказала это вслух."},
        {"kind": "stage_direction", "text": "достать телефон и открыть переписку"},
    ]

    assert len(packet["continuity_window"]) == 1
    assert packet["continuity_window"][0]["turn_number"] == 1
    assert packet["continuity_window"][0]["events"][0]["event"] == (
        "Эмили и Хлоя продолжили уже начатое знакомство"
    )

    chloe = next(
        item
        for item in packet["character_continuity_index"]
        if item["character_id"] == "char_chloe"
    )
    assert chloe["has_shared_scene_with_pov"] is True
    assert chloe["last_shared_scene_with_pov_turn"] == 1


def test_writer_memory_updates_preserve_existing_knowledge_entries(
    tmp_path, session_payload
) -> None:
    client = _writer_client(tmp_path)
    session_id = create_session(client, session_payload)

    first_knowledge = {
        "entries": [
            {
                "knowledge_id": "know_first",
                "fact": "Хлоя слышала первый факт",
                "source": "лично услышала от Эмили",
                "status": "active",
            }
        ]
    }
    second_knowledge = {
        "entries": [
            {
                "knowledge_id": "know_second",
                "fact": "Хлоя увидела второй факт",
                "source": "лично увидела",
                "status": "active",
            }
        ]
    }

    commit_next_turn(
        client,
        session_id,
        player_input="Сообщить первый факт",
        state_updates={
            "characters": [
                {"character_id": "char_chloe", "knowledge": first_knowledge}
            ]
        },
    )
    commit_next_turn(
        client,
        session_id,
        player_input="Показать второй факт",
        state_updates={
            "characters": [
                {"character_id": "char_chloe", "knowledge": second_knowledge}
            ]
        },
    )

    stored = app.state.service.storage.read_json(
        session_id, "characters/char_chloe/knowledge.json"
    )
    assert {entry["knowledge_id"] for entry in stored["entries"]} == {
        "know_first",
        "know_second",
    }


def test_production_audit_requires_explicit_coverage_of_all_fifteen_turns_and_knowledge_targets(
    tmp_path, session_payload
) -> None:
    client = _writer_client(tmp_path)
    session_id = create_session(client, session_payload)

    for turn_number in range(1, 16):
        commit_next_turn(
            client,
            session_id,
            player_input=f"Тестовый ход {turn_number}",
            event_text=f"Значимое событие {turn_number}",
        )

    audit_packet = collect_packet(
        client,
        session_id,
        client.get(f"/api/v1/sessions/{session_id}/audit-packet"),
    )
    targets = audit_packet["audit_targets"]
    assert targets["turn_numbers"] == list(range(1, 16))
    assert {"char_emily", "char_chloe"}.issubset(set(targets["character_ids"]))
    assert {"char_emily", "char_chloe"}.issubset(
        set(targets["knowledge_character_ids"])
    )
    assert len(targets["chronology_event_ids"]) == 15

    rejected = client.post(
        f"/api/v1/sessions/{session_id}/audits/commit",
        json={
            "audit_id": audit_packet["audit_id"],
            "expected_state_revision": audit_packet["expected_state_revision"],
            "checklist": complete_checklist(),
            "findings": {"result": "Просто поставили галочки без реальной сверки"},
        },
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "AUDIT_EVIDENCE_INCOMPLETE"

    verification = {
        "turns_checked": targets["turn_numbers"],
        "chronology_event_ids_checked": targets["chronology_event_ids"],
        "characters_checked": targets["character_ids"],
        "knowledge_checked_character_ids": targets["knowledge_character_ids"],
        "final_consistency_pass": True,
        "unresolved_issues": [],
    }
    completed = client.post(
        f"/api/v1/sessions/{session_id}/audits/commit",
        json={
            "audit_id": audit_packet["audit_id"],
            "expected_state_revision": audit_packet["expected_state_revision"],
            "checklist": complete_checklist(),
            "findings": {
                "result": "Все цели аудита сверены после финального прохода",
                "verification": verification,
            },
        },
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["audit_complete"] is True
    assert completed.json()["last_audited_turn"] == 15
