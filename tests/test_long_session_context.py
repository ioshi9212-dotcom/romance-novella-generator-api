from copy import deepcopy

from fastapi.testclient import TestClient

from app.config import Settings
from app.long_session_service import LongSessionNovellaService
from app.main import app
from tests.conftest import collect_packet, full_character_card


def _client(tmp_path) -> tuple[TestClient, LongSessionNovellaService]:
    service = LongSessionNovellaService(
        Settings(
            data_dir=tmp_path / "long-session-data",
            public_base_url="https://example.test",
            packet_chunk_chars=4000,
        )
    )
    app.state.service = service
    return TestClient(app), service


def _create(client: TestClient, payload: dict) -> str:
    response = client.post("/api/v1/sessions", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


def _large_knowledge(prefix: str, count: int = 90) -> dict:
    entries = []
    for index in range(count):
        entries.append(
            {
                "knowledge_id": f"{prefix}_{index:03d}",
                "fact": (
                    f"{prefix}: установленный факт номер {index}. "
                    + "Эта подробность сохраняется в долговременной памяти персонажа. " * 8
                ),
                "source": "confirmed_setup" if index == 0 else f"turn_{index + 1}",
                "importance": "core" if index == 0 else "normal",
            }
        )
    entries[37]["fact"] += " Здесь отдельно упомянут старый архив и символ цепи."
    return {"entries": entries}


def _offscreen_character(
    character_id: str,
    name: str,
    *,
    status: str,
) -> dict:
    card = full_character_card(
        character_id,
        name,
        f"{name}: важный персонаж длинной истории, которого нельзя терять из режиссуры.",
    )
    card["story_status"] = status
    card["immediate_scene_goal"] = "продолжать собственную линию вне кадра"
    card["goals"]["immediate"] = "продолжать собственную линию вне кадра"
    return {
        "character_id": character_id,
        "card": card,
        "current_state": {
            "current_location_id": "loc_elsewhere",
            "current_activity": "занимается собственной незакрытой линией",
        },
        "relationships": {"relations": []},
        "knowledge": {
            "entries": [
                {
                    "knowledge_id": f"knowledge_{character_id}",
                    "fact": f"{name} помнит установленный факт своей линии.",
                    "source": "confirmed_setup",
                }
            ]
        },
    }


def test_long_session_packet_projects_large_knowledge_without_deleting_storage(
    tmp_path, session_payload
):
    client, service = _client(tmp_path)
    payload = deepcopy(session_payload)
    payload["novel"]["genre"] = [
        "романтика",
        "триллер",
        "экшн",
        "сверхъестественное",
    ]
    payload["novel"]["story_focus"] = (
        "Романтика не должна вытеснять триллер, экшн и сверхъестественную линию."
    )
    payload["characters"][0]["knowledge"] = _large_knowledge("emily")
    payload["characters"][1]["knowledge"] = _large_knowledge("chloe")

    session_id = _create(client, payload)
    first = client.post(
        f"/api/v1/sessions/{session_id}/turn-packet",
        json={
            "player_input": "Проверить старый архив и символ цепи.",
            "mode": "new",
        },
    )
    assert first.status_code == 200, first.text
    final_chunk_count = first.json()["chunk_count"]
    packet = collect_packet(client, session_id, first)

    manifest = packet["context_manifest"]
    assert manifest["authoritative_data_deleted"] is False
    assert manifest["pre_compaction_chunk_count"] > final_chunk_count
    assert manifest["stored_character_knowledge_entries"] == 180

    packet_characters = {
        item["character_id"]: item for item in packet["state"]["characters"]
    }
    emily_view = packet_characters["char_emily"]["knowledge"]
    chloe_view = packet_characters["char_chloe"]["knowledge"]
    assert len(emily_view["entries"]) <= 18
    assert len(chloe_view["entries"]) <= 18
    assert emily_view["_working_view"]["total_entries"] == 90
    assert emily_view["_working_view"]["complete"] is False

    emily_ids = {item["knowledge_id"] for item in emily_view["entries"]}
    assert "emily_000" in emily_ids  # confirmed/core anchor survives projection
    assert "emily_037" in emily_ids  # current-input relevance survives projection
    assert "emily_089" in emily_ids  # recent memory survives projection

    pov_view = packet["active_memory"]["pov_long_term_memory"]["knowledge"]
    assert len(pov_view["entries"]) <= 18
    assert pov_view["_working_view"]["total_entries"] == 90

    # The compact writer packet must not mutate the authoritative pre-turn snapshot.
    pending = service.storage.read_json(session_id, "pending_turn.json")
    stored_emily = next(
        item
        for item in pending["before_state"]["characters"]
        if item["character_id"] == "char_emily"
    )
    assert len(stored_emily["knowledge"]["entries"]) == 90
    assert "story_compass" in packet["active_memory"]
    assert packet["story_bible"]["novel"]["genre"] == payload["novel"]["genre"]


def test_story_compass_cast_debt_and_resurfacing_keep_long_story_alive(
    session_payload,
):
    before_state = deepcopy(session_payload)
    before_state["novel"]["genre"] = [
        "романтика",
        "триллер",
        "экшн",
        "сверхъестественное",
        "драма",
    ]
    before_state["novel"]["genre_balance_rule"] = (
        "Тяжёлые и опасные события должны контрастировать с романтическими и бытовыми сценами."
    )

    adrian = _offscreen_character(
        "char_adrian",
        "Адриан",
        status="not_introduced",
    )
    rhea = _offscreen_character(
        "char_rhea",
        "Рэя",
        status="offstage",
    )
    before_state["characters"].extend([adrian, rhea])

    packet_stub = {
        "turn_number": 300,
        "story_bible": {"story_direction": {}},
        "character_continuity_index": [
            {
                "character_id": "char_emily",
                "first_seen_turn": 1,
                "last_seen_turn": 299,
                "last_shared_scene_with_pov_turn": 299,
            },
            {
                "character_id": "char_chloe",
                "first_seen_turn": 1,
                "last_seen_turn": 299,
                "last_shared_scene_with_pov_turn": 299,
            },
            {
                "character_id": "char_adrian",
                "first_seen_turn": None,
                "last_seen_turn": None,
                "last_shared_scene_with_pov_turn": None,
            },
            {
                "character_id": "char_rhea",
                "first_seen_turn": 8,
                "last_seen_turn": 210,
                "last_shared_scene_with_pov_turn": 210,
            },
        ],
    }

    memory = LongSessionNovellaService._build_active_memory(
        before_state=before_state,
        payload=packet_stub,
        chronology=[],
        player_input="Продолжить текущую сцену.",
    )

    compass = memory["story_compass"]
    assert compass["source_path"] == "story_bible.novel"
    assert any(
        item["path"] == "genre" for item in compass["declared_genre_fields"]
    )
    assert any(
        item["path"] == "genre_balance_rule"
        for item in compass["directional_questionnaire_fields"]
    )
    assert "romance+thriller+action+supernatural" in compass["instruction"]

    cast_debt = {item["character_id"]: item for item in memory["cast_debt"]}
    assert "char_adrian" in cast_debt
    assert cast_debt["char_adrian"]["unintroduced_for_turns"] == 299
    assert not cast_debt["char_adrian"]["director_agenda_matches"]

    resurfacing = {
        item["character_id"]: item for item in memory["resurfacing_debt"]
    }
    assert "char_rhea" in resurfacing
    assert resurfacing["char_rhea"]["turns_since_seen"] == 90

    pulse_ids = {
        item["character_id"] for item in memory["offscreen_cast_pulse"]
    }
    assert "char_rhea" in pulse_ids
    assert "char_adrian" not in pulse_ids
    assert "LONG-SESSION CONTRACT" in memory["memory_contract"]


def test_long_session_service_preserves_pending_turn_recovery(
    tmp_path, session_payload
):
    client, _service = _client(tmp_path)
    session_id = _create(client, deepcopy(session_payload))

    first = client.post(
        f"/api/v1/sessions/{session_id}/turn-packet",
        json={"player_input": "Первый незавершённый ход", "mode": "new"},
    )
    assert first.status_code == 200, first.text
    packet_id = first.json()["packet_id"]

    recovered = client.post(
        f"/api/v1/sessions/{session_id}/turn-packet",
        json={"player_input": "Новый ввод после сбоя", "mode": "new"},
    )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["packet_id"] == packet_id

    packet = collect_packet(client, session_id, recovered)
    assert packet["player_input"] == "Первый незавершённый ход"
    assert packet["context_manifest"]["authoritative_data_deleted"] is False
