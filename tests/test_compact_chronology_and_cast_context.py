from copy import deepcopy

from fastapi.testclient import TestClient

from app.config import Settings
from app.fast_audit_service import FastAuditNovellaService
from app.main import app
from tests.conftest import (
    collect_packet,
    create_session,
    full_character_card,
    scene_output,
    scene_state_update,
)


def _client(tmp_path) -> TestClient:
    app.state.service = FastAuditNovellaService(
        Settings(
            data_dir=tmp_path / "compact-memory-data",
            public_base_url="https://example.test",
            packet_chunk_chars=4000,
        )
    )
    return TestClient(app)


def _payload_with_offstage_character(session_payload):
    payload = deepcopy(session_payload)
    ethan = {
        "character_id": "char_ethan",
        "card": full_character_card(
            "char_ethan",
            "Итан",
            "Важный персонаж с собственной линией; действует независимо от POV.",
        ),
        "current_state": {
            "current_location_id": "loc_home",
            "current_goal": "добиться разговора с Эмили, когда появится естественный повод",
            "activity": "занимается своими делами вне текущей сцены",
        },
        "relationships": {
            "relations": [
                {
                    "target_character_id": "char_emily",
                    "relationship_type": "сложная личная связь",
                    "relationship_context": "отношения развиваются через реальные сцены",
                    "current_dynamic": "Итан хочет сблизиться, но не давит напрямую",
                    "dimensions": [
                        {"key": "sympathy", "label": "симпатия", "value": 62}
                    ],
                    "beliefs_about_target": ["Эмили не любит давление"],
                    "unresolved_between_them": ["неоконченный разговор"],
                    "dynamic_constraints": ["не навязываться без повода"],
                    "change_reasons": [],
                    "last_changed_turn": 0,
                }
            ]
        },
        "knowledge": {"entries": []},
    }
    ethan["card"]["story_status"] = "offstage"
    ethan["card"]["goals"]["immediate"] = "найти естественный повод снова связаться с Эмили"
    ethan["card"]["goals"]["story_function"] = "важная самостоятельная романтическая линия"
    payload["characters"].append(ethan)
    payload["plot_state"] = {
        "active_lines": [
            {
                "line_id": "line_ethan",
                "character_id": "char_ethan",
                "status": "active",
                "summary": "Линия Итана остаётся незавершённой",
            }
        ]
    }
    payload["director_plan"]["character_agendas"] = [
        {
            "character_id": "char_ethan",
            "status": "active",
            "goal": "самостоятельно искать подходящий момент для контакта",
        }
    ]
    return payload


def _commit_turn(client, session_id, packet, *, event_text):
    turn_number = packet["turn_number"]
    cycle_position = packet["cycle_position"]
    story_datetime = f"2025-09-08T10:{turn_number:02d}:00"
    response = client.post(
        f"/api/v1/sessions/{session_id}/turns/commit",
        json={
            "turn_id": packet["turn_id"],
            "expected_state_revision": packet["expected_state_revision"],
            "scene_output": scene_output(
                turn_number,
                cycle_position,
                body="День 1\nСцена продолжается без смены календарной даты.",
            ),
            "summary": f"Краткое содержание хода {turn_number}",
            "scene_id": f"scene_{turn_number:04d}",
            "story_datetime": story_datetime,
            "events": [
                {
                    "scene_id": f"scene_{turn_number:04d}",
                    "story_datetime": story_datetime,
                    "location_id": "loc_home",
                    "participants_present": ["char_emily", "char_chloe"],
                    "event": event_text,
                }
            ],
            "state_updates": {
                "scene_state": scene_state_update(
                    turn_number,
                    story_datetime=story_datetime,
                )
            },
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_turn_packet_surfaces_offstage_character_questionnaire(tmp_path, session_payload):
    client = _client(tmp_path)
    session_id = create_session(client, _payload_with_offstage_character(session_payload))

    packet = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": "Продолжить сцену естественно"},
        ),
    )

    assert packet["chronology_policy"]["skip_event_sentinel"] == "__NO_CHRONOLOGY_EVENT__"
    candidates = {
        item["character_id"]: item
        for item in packet["offstage_cast_context"]["candidates"]
    }
    assert "char_ethan" in candidates
    ethan = candidates["char_ethan"]
    assert ethan["active_story_reference"] is True
    assert "самостоятель" in ethan["personality"]["inner_character"]
    assert "романтическая линия" in ethan["goals"]["story_function"]
    assert ethan["current_state"]["current_goal"]
    assert ethan["relationship_to_pov"]["current_dynamic"]


def test_no_chronology_sentinel_is_removed_before_persistence(tmp_path, session_payload):
    client = _client(tmp_path)
    session_id = create_session(client, session_payload)
    packet = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": "Просто лечь спать, ничего больше не происходит"},
        ),
    )
    story_datetime = "2025-09-08T10:01:00"

    committed = client.post(
        f"/api/v1/sessions/{session_id}/turns/commit",
        json={
            "turn_id": packet["turn_id"],
            "expected_state_revision": packet["expected_state_revision"],
            "scene_output": scene_output(
                1,
                1,
                body="День 1\nЭмили закончила обычный вечер и легла спать.",
            ),
            "summary": "Обычный бытовой переход без сюжетно значимого нового факта.",
            "scene_id": "scene_0001",
            "story_datetime": story_datetime,
            "events": [
                {
                    "scene_id": "scene_0001",
                    "story_datetime": story_datetime,
                    "location_id": "loc_home",
                    "participants_present": ["char_emily", "char_chloe"],
                    "event": "__NO_CHRONOLOGY_EVENT__",
                }
            ],
            "state_updates": {
                "scene_state": scene_state_update(
                    1,
                    story_datetime=story_datetime,
                )
            },
        },
    )
    assert committed.status_code == 200, committed.text
    assert committed.json()["created_event_ids"] == []

    chronology = client.get(
        f"/api/v1/sessions/{session_id}/chronology"
    )
    assert chronology.status_code == 200, chronology.text
    assert chronology.json()["events"] == []


def test_fast_audit_flags_long_absent_important_cast(tmp_path, session_payload):
    client = _client(tmp_path)
    session_id = create_session(client, _payload_with_offstage_character(session_payload))

    for turn_number in range(1, 16):
        packet = collect_packet(
            client,
            session_id,
            client.post(
                f"/api/v1/sessions/{session_id}/turn-packet",
                json={"player_input": f"Продолжить текущую сцену, ход {turn_number}"},
            ),
        )
        _commit_turn(
            client,
            session_id,
            packet,
            event_text=f"Значимый тестовый факт хода {turn_number}",
        )

    audit = collect_packet(
        client,
        session_id,
        client.get(f"/api/v1/sessions/{session_id}/audit-packet"),
    )
    candidates = {
        item["character_id"]: item
        for item in audit["cast_continuity_audit"]["candidates"]
    }
    assert "char_ethan" in candidates
    assert candidates["char_ethan"]["never_seen"] is True
    assert candidates["char_ethan"]["active_story_reference"] is True
    assert "silently" in audit["cast_continuity_audit"]["instruction"]
