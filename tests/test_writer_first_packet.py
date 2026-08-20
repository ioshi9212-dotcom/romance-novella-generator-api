from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app
from app.writer_service import WriterFirstNovellaService
from tests.conftest import (
    collect_packet,
    commit_next_turn,
    create_session,
    scene_state_update,
)


def _writer_client(tmp_path) -> TestClient:
    app.state.service = WriterFirstNovellaService(
        Settings(
            data_dir=tmp_path / "writer-first-data",
            public_base_url="https://example.test",
            packet_chunk_chars=4000,
        )
    )
    return TestClient(app)


def test_opening_packet_keeps_exact_confirmed_setup_source(
    tmp_path, session_payload
) -> None:
    client = _writer_client(tmp_path)
    session_id = create_session(client, session_payload)

    packet = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": "Начать стартовую сцену по подтверждённым данным"},
        ),
    )

    source = packet["story_bible"]["confirmed_setup_source"]
    assert source["messages"] == session_payload["setup_source"]["messages"]
    assert source["coverage"] == session_payload["setup_source"]["coverage"]


def test_normal_turn_packet_is_writer_sized_not_audit_sized(
    tmp_path, session_payload
) -> None:
    client = _writer_client(tmp_path)
    session_id = create_session(client, session_payload)

    for turn_number in range(1, 5):
        commit_next_turn(
            client,
            session_id,
            player_input=f"Продолжить сцену {turn_number}",
            event_text=f"Установлен важный факт {turn_number}",
        )

    first = client.post(
        f"/api/v1/sessions/{session_id}/turn-packet",
        json={"player_input": "Продолжить разговор с Хлоей"},
    )
    packet = collect_packet(client, session_id, first)

    assert "chronology" not in packet
    assert "chronology_manifest" not in packet
    assert "turns_since_last_audit" not in packet
    assert len(packet["recent_scene_history"]) <= 2
    assert packet["recent_scene_history"][-1]["turn_number"] == 4
    assert packet["story_memory"]
    assert all("session_id" not in event for event in packet["story_memory"])

    assert set(packet["story_bible"]) == {
        "novel",
        "hidden_lore",
        "active_plot",
        "story_direction",
    }
    assert "director_plan" not in packet["state"]
    assert "hidden_lore" not in packet["state"]
    assert "plot_state" not in packet["state"]
    assert "world_state" not in packet["state"]
    assert {
        item["character_id"] for item in packet["state"]["characters"]
    } == {"char_emily", "char_chloe"}
    assert [item["location_id"] for item in packet["state"]["locations"]] == [
        "loc_home"
    ]


def test_active_arc_update_is_visible_in_the_next_writer_packet(
    tmp_path, session_payload
) -> None:
    client = _writer_client(tmp_path)
    session_id = create_session(client, session_payload)
    arc = {
        "arc_id": "arc_rescue",
        "status": "active",
        "started_turn": 1,
        "premise": "Группа прибыла на вызов",
        "anchor_facts": ["По исходным данным подтверждены четыре заложника"],
        "goal": "Завершить операцию и установить судьбу заложников",
        "current_phase": "проникновение",
        "unresolved": ["Не найден четвёртый заложник"],
        "end_conditions": ["Судьба четырёх исходных заложников установлена"],
        "possible_routes": ["продолжить проникновение", "сменить подход"],
        "discoveries": [],
        "last_progress_turn": 1,
    }
    commit_next_turn(
        client,
        session_id,
        player_input="Продолжить операцию",
        state_updates={
            "plot_state": {
                "active_lines": [],
                "active_arcs": [arc],
                "resolved_arcs": [],
            }
        },
    )

    packet = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": "Осмотреть следующий проход"},
        ),
    )
    active_arcs = packet["story_bible"]["active_plot"]["active_arcs"]
    assert active_arcs[0]["arc_id"] == "arc_rescue"
    assert active_arcs[0]["anchor_facts"] == [
        "По исходным данным подтверждены четыре заложника"
    ]
    assert active_arcs[0]["unresolved"] == ["Не найден четвёртый заложник"]


def test_writer_runtime_does_not_require_visible_audit_reminder(
    tmp_path, session_payload
) -> None:
    client = _writer_client(tmp_path)
    session_id = create_session(client, session_payload)
    packet = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": "Продолжить"},
        ),
    )

    response = client.post(
        f"/api/v1/sessions/{session_id}/turns/commit",
        json={
            "turn_id": packet["turn_id"],
            "expected_state_revision": packet["expected_state_revision"],
            "scene_output": "Сцена продолжается.\n\nХод 1 · цикл 1/15",
            "summary": "Сцена продолжилась без служебного текста для игрока",
            "scene_id": "scene_0001",
            "story_datetime": "2025-09-08T10:01:00",
            "events": [
                {
                    "scene_id": "scene_0001",
                    "story_datetime": "2025-09-08T10:01:00",
                    "location_id": "loc_home",
                    "participants_present": ["char_emily", "char_chloe"],
                    "event": "Сцена продолжилась",
                }
            ],
            "state_updates": {
                "scene_state": scene_state_update(
                    1,
                    story_datetime="2025-09-08T10:01:00",
                    present_character_ids=["char_emily", "char_chloe"],
                )
            },
        },
    )

    assert response.status_code == 200, response.text
