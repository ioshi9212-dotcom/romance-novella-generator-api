from copy import deepcopy

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app
from app.writer_service import WriterFirstNovellaService
from tests.conftest import (
    collect_packet,
    commit_next_turn,
    create_session,
    full_character_card,
)


def _writer_client(tmp_path) -> TestClient:
    app.state.service = WriterFirstNovellaService(
        Settings(
            data_dir=tmp_path / "causal-cast-data",
            public_base_url="https://example.test",
            packet_chunk_chars=4000,
        )
    )
    return TestClient(app)


def _offscreen_character(character_id: str, name: str) -> dict:
    return {
        "character_id": character_id,
        "card": full_character_card(
            character_id,
            name,
            f"{name} — постоянный NPC со своей ролью вне текущего кадра.",
        ),
        "current_state": {
            "current_location_id": "loc_elsewhere",
            "current_goal": "решить собственную текущую задачу",
            "offscreen_activity": "занимается своими делами вне сцены",
            "available_now": True,
        },
        "relationships": {"owner_character_id": character_id, "relations": []},
        "knowledge": {"entries": []},
    }


def test_writer_packet_has_causal_full_cast_index_without_rotation_metadata(
    tmp_path, session_payload
) -> None:
    client = _writer_client(tmp_path)
    payload = deepcopy(session_payload)
    payload["runtime_contract_version"] = "2.0"
    payload["director_plan"]["active_threads"] = [
        {
            "thread_id": "thread_ryan_work",
            "status": "active",
            "character_ids": ["char_ryan"],
            "current_question": "Когда рабочая линия Райана пересечётся с основной историей?",
        }
    ]
    ryan = _offscreen_character("char_ryan", "Райан")
    ryan["relationships"] = {
        "owner_character_id": "char_ryan",
        "relations": [
            {
                "target_character_id": "char_chloe",
                "relationship_type": "знакомые",
                "relationship_context": "пересекаются по работе",
                "current_dynamic": "есть незакрытый рабочий вопрос",
                "dimensions": [],
                "beliefs_about_target": [],
                "unresolved_between_them": ["нужно передать документы"],
                "dynamic_constraints": [],
                "change_reasons": [],
                "last_changed_turn": 0,
            }
        ],
    }
    payload["characters"].append(ryan)

    session_id = create_session(client, payload)
    packet = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": "Продолжить текущую сцену"},
        ),
    )

    # Full dossiers remain limited to POV + current physical participants.
    assert {
        item["character_id"] for item in packet["state"]["characters"]
    } == {"char_emily", "char_chloe"}

    # Director still sees every permanent NPC before choosing who may enter.
    cast_rows = {
        item["character_id"]: item for item in packet["cast_index"]["characters"]
    }
    assert set(cast_rows) == {"char_chloe", "char_ryan"}
    assert cast_rows["char_ryan"]["current_state"]["offscreen_activity"]
    assert cast_rows["char_ryan"]["agendas"]
    assert cast_rows["char_ryan"]["relationship_links"][0][
        "target_character_id"
    ] == "char_chloe"
    assert cast_rows["char_ryan"]["active_threads"][0]["thread_id"] == (
        "thread_ryan_work"
    )

    # Missing agendas are automatically seeded for the whole permanent NPC cast.
    agenda_ids = {
        item["character_id"]
        for item in packet["story_bible"]["story_direction"]["character_agendas"]
    }
    assert {"char_chloe", "char_ryan"} <= agenda_ids

    # The director index must not become a recency/rotation queue.
    serialized = str(packet["cast_index"]).lower()
    assert "last_appearance" not in serialized
    assert "turns_since" not in serialized
    assert "days_since" not in serialized
    assert "not a rotation queue" in packet["cast_index"]["instruction"].lower()
    assert "it is valid to choose nobody" in packet["cast_index"]["instruction"].lower()


def test_new_permanent_npc_gets_agenda_after_commit(
    tmp_path, session_payload
) -> None:
    client = _writer_client(tmp_path)
    payload = deepcopy(session_payload)
    session_id = create_session(client, payload)

    silas = _offscreen_character("char_silas", "Сайлас")
    commit_next_turn(
        client,
        session_id,
        player_input="Продолжить сцену",
        state_updates={
            "characters": [
                {
                    "character_id": "char_silas",
                    "card": silas["card"],
                    "current_state": silas["current_state"],
                    "relationships": silas["relationships"],
                    "knowledge": silas["knowledge"],
                }
            ]
        },
    )

    packet = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": "Продолжить дальше"},
        ),
    )
    cast_rows = {
        item["character_id"]: item for item in packet["cast_index"]["characters"]
    }
    assert "char_silas" in cast_rows
    assert cast_rows["char_silas"]["agendas"]
    assert cast_rows["char_silas"]["agendas"][0]["character_id"] == "char_silas"
