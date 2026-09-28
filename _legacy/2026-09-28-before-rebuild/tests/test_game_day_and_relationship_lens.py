from copy import deepcopy

from fastapi.testclient import TestClient

from app.config import Settings
from app.enhanced_writer_service import EnhancedWriterNovellaService
from app.main import app
from tests.conftest import collect_packet, create_session, scene_state_update


def _client(tmp_path) -> TestClient:
    app.state.service = EnhancedWriterNovellaService(
        Settings(
            data_dir=tmp_path / "enhanced-writer-data",
            public_base_url="https://example.test",
            packet_chunk_chars=4000,
        )
    )
    return TestClient(app)


def _scene_output(day: int, turn: int, cycle: int) -> str:
    return (
        f"🎭 Тестовая новелла · осень\n"
        f"🕒 День {day} · Понедельник, 08.09.2025, 23:50 · 📍 Дом Эмили\n\n"
        f"Сцена продолжается.\n\nХод {turn} · цикл {cycle}/15"
    )


def _commit(
    client: TestClient,
    session_id: str,
    packet: dict,
    *,
    story_datetime: str,
    day: int,
) -> object:
    turn = packet["turn_number"]
    return client.post(
        f"/api/v1/sessions/{session_id}/turns/commit",
        json={
            "turn_id": packet["turn_id"],
            "expected_state_revision": packet["expected_state_revision"],
            "scene_output": _scene_output(day, turn, packet["cycle_position"]),
            "summary": f"Событие хода {turn}",
            "scene_id": f"scene_{turn:04d}",
            "story_datetime": story_datetime,
            "events": [
                {
                    "scene_id": f"scene_{turn:04d}",
                    "story_datetime": story_datetime,
                    "location_id": "loc_home",
                    "participants_present": ["char_emily", "char_chloe"],
                    "event": f"Событие хода {turn}",
                }
            ],
            "state_updates": {
                "scene_state": scene_state_update(
                    turn,
                    story_datetime=story_datetime,
                    present_character_ids=["char_emily", "char_chloe"],
                )
            },
        },
    )


def test_game_day_is_calendar_day_from_story_start_and_commit_rejects_wrong_day(
    tmp_path, session_payload
) -> None:
    payload = deepcopy(session_payload)
    payload["world_state"]["story_datetime"] = "2025-09-08T23:40:00"
    client = _client(tmp_path)
    session_id = create_session(client, payload)

    first = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": "Продолжить"},
        ),
    )
    assert first["game_clock"]["game_day_at_turn_start"] == 1
    assert first["game_clock"]["story_start_datetime"] == "2025-09-08T23:40:00"

    committed = _commit(
        client,
        session_id,
        first,
        story_datetime="2025-09-08T23:50:00",
        day=1,
    )
    assert committed.status_code == 200, committed.text

    second = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": "Перейти через полночь"},
        ),
    )
    assert second["game_clock"]["game_day_at_turn_start"] == 1

    wrong = _commit(
        client,
        session_id,
        second,
        story_datetime="2025-09-09T00:05:00",
        day=1,
    )
    assert wrong.status_code == 422
    assert wrong.json()["error"]["code"] == "GAME_DAY_HEADER_MISMATCH"

    # The rejected commit remains pending, so the same packet can be corrected and retried.
    correct = _commit(
        client,
        session_id,
        second,
        story_datetime="2025-09-09T00:05:00",
        day=2,
    )
    assert correct.status_code == 200, correct.text

    third = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": "Продолжить утром"},
        ),
    )
    assert third["game_clock"]["game_day_at_turn_start"] == 2


def test_relationship_lens_keeps_multiple_causal_dimensions_instead_of_generic_interest(
    tmp_path, session_payload
) -> None:
    payload = deepcopy(session_payload)
    chloe = next(
        item for item in payload["characters"] if item["character_id"] == "char_chloe"
    )
    chloe["relationships"] = {
        "relations": [
            {
                "target_character_id": "char_emily",
                "relationship_type": "сложная дружба",
                "relationship_context": "Они давно знакомы и много пережили вместе",
                "current_dynamic": "Хлоя доверяет Эмили, но ревнует к новому знакомому",
                "dimensions": [
                    {"key": "trust", "label": "доверие", "value": 68},
                    {"key": "jealousy", "label": "ревность", "value": 31},
                    {"key": "sympathy", "label": "симпатия", "value": 74},
                ],
                "beliefs_about_target": ["Эмили обычно говорит прямо"],
                "unresolved_between_them": ["Хлоя не сказала о ревности"],
                "dynamic_constraints": ["Хлоя скрывает ревность шутками"],
                "change_reasons": [],
                "last_changed_turn": 0,
            }
        ]
    }
    client = _client(tmp_path)
    session_id = create_session(client, payload)

    packet = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": "Спросить Хлою, почему она молчит"},
        ),
    )
    relations = packet["relationship_lens"]["relations_in_current_scene"]
    relation = next(item for item in relations if item["owner_character_id"] == "char_chloe")
    labels = {item["label"] for item in relation["dimensions"]}
    assert labels == {"доверие", "ревность", "симпатия"}
    assert "интерес" not in labels
    assert "causal state" in packet["relationship_lens"]["instruction"]
    assert "generic fallback" in packet["relationship_lens"]["instruction"]

    builder = packet["scene_builder"]
    assert "День {game_day}" in builder
    assert "Отношения NPC — часть причин их поведения" in builder
    assert "Не используй `интерес` как универсальный показатель" in builder
