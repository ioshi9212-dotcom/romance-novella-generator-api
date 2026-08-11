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
