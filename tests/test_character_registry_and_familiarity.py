from copy import deepcopy

from fastapi.testclient import TestClient

from app.config import Settings
from app.enhanced_writer_service import EnhancedWriterNovellaService
from app.main import app
from tests.conftest import (
    collect_packet,
    create_session,
    full_character_card,
    scene_state_update,
)


def _client(tmp_path) -> TestClient:
    app.state.service = EnhancedWriterNovellaService(
        Settings(
            data_dir=tmp_path / "character-registry-data",
            public_base_url="https://example.test",
            packet_chunk_chars=4000,
        )
    )
    return TestClient(app)


def _scene_output(turn: int, cycle: int, *, day: int = 1) -> str:
    return (
        "🎭 Тестовая новелла · осень\n"
        f"🕒 День {day} · Понедельник, 08.09.2025, 10:05 · 📍 Дом Эмили\n\n"
        "Сцена продолжается.\n\n"
        f"Ход {turn} · цикл {cycle}/15"
    )


def _commit(
    client: TestClient,
    session_id: str,
    packet: dict,
    *,
    event_text: str,
    character_updates: list[dict] | None = None,
):
    turn = packet["turn_number"]
    return client.post(
        f"/api/v1/sessions/{session_id}/turns/commit",
        json={
            "turn_id": packet["turn_id"],
            "expected_state_revision": packet["expected_state_revision"],
            "scene_output": _scene_output(turn, packet["cycle_position"]),
            "summary": event_text,
            "scene_id": f"scene_{turn:04d}",
            "story_datetime": "2025-09-08T10:05:00",
            "events": [
                {
                    "scene_id": f"scene_{turn:04d}",
                    "story_datetime": "2025-09-08T10:05:00",
                    "location_id": "loc_home",
                    "participants_present": ["char_emily", "char_chloe"],
                    "event": event_text,
                }
            ],
            "state_updates": {
                "scene_state": scene_state_update(
                    turn,
                    story_datetime="2025-09-08T10:05:00",
                    present_character_ids=["char_emily", "char_chloe"],
                ),
                "characters": character_updates or [],
            },
        },
    )


def _registry_entry(packet: dict, character_id: str) -> dict:
    registry = packet["story_bible"]["novel"]["character_registry"]
    return next(item for item in registry if item["character_id"] == character_id)


def test_old_session_recovers_explicit_acquaintance_from_chronology(
    tmp_path, session_payload
) -> None:
    client = _client(tmp_path)
    session_id = create_session(client, session_payload)

    first = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": "Продолжить"},
        ),
    )
    committed = _commit(
        client,
        session_id,
        first,
        event_text="Эмили и Хлоя познакомились и обменялись именами",
    )
    assert committed.status_code == 200, committed.text

    second = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": "Подойти к Хлое снова"},
        ),
    )
    chloe = _registry_entry(second, "char_chloe")
    assert chloe["continuity_status"] == "acquainted"
    assert chloe["familiarity_source"] == "legacy_chronology"
    assert chloe["legacy_familiarity_evidence"]["turn_number"] == 1
    assert chloe["encountered_with_pov"] is True

    reserved = second["reserved_character_names"]["names"]
    assert any(
        item["reserved_name"] == "хлоя" and item["character_id"] == "char_chloe"
        for item in reserved
    )


def test_old_session_with_shared_scene_and_real_relationship_is_not_reset_to_strangers(
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
                "relationship_type": "дружеское знакомство",
                "relationship_context": "Они уже общались раньше",
                "current_dynamic": "Хлоя относится к Эмили с доверием",
                "dimensions": [
                    {"key": "trust", "label": "доверие", "value": 42}
                ],
                "beliefs_about_target": ["Эмили говорит прямо"],
                "unresolved_between_them": [],
                "dynamic_constraints": [],
                "change_reasons": [],
                "last_changed_turn": 0,
            }
        ]
    }
    client = _client(tmp_path)
    session_id = create_session(client, payload)

    first = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": "Продолжить разговор"},
        ),
    )
    committed = _commit(
        client,
        session_id,
        first,
        event_text="Эмили и Хлоя продолжили разговор на кухне",
    )
    assert committed.status_code == 200, committed.text

    second = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": "Снова обратиться к Хлое"},
        ),
    )
    chloe_entry = _registry_entry(second, "char_chloe")
    assert chloe_entry["continuity_status"] == "legacy_known_relationship"
    assert chloe_entry["familiarity_source"] == "legacy_state_inference"
    assert chloe_entry["legacy_familiarity_evidence"][
        "directed_relationship_to_pov"
    ] is True


def test_reserved_name_cannot_be_reused_and_new_important_npc_enters_registry(
    tmp_path, session_payload
) -> None:
    client = _client(tmp_path)
    session_id = create_session(client, session_payload)
    packet = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": "Продолжить"},
        ),
    )

    duplicate_card = full_character_card(
        "char_duplicate", "Хлоя Рейн", "Новый важный NPC, которого система пытается назвать чужим именем."
    )
    duplicate_card["origin"] = "runtime"
    duplicate_card["card_level"] = "important"
    rejected = _commit(
        client,
        session_id,
        packet,
        event_text="Появился новый человек",
        character_updates=[
            {
                "character_id": "char_duplicate",
                "card": duplicate_card,
                "current_state": {"current_location_id": "loc_home"},
                "relationships": {"relations": []},
                "knowledge": {"entries": []},
            }
        ],
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "CHARACTER_NAME_RESERVED"

    nora_card = full_character_card(
        "char_nora", "Нора Рейн", "Новый важный NPC, связной соседнего подразделения."
    )
    nora_card["origin"] = "runtime"
    nora_card["card_level"] = "important"
    accepted = _commit(
        client,
        session_id,
        packet,
        event_text="Нора стала важным действующим лицом",
        character_updates=[
            {
                "character_id": "char_nora",
                "card": nora_card,
                "current_state": {"current_location_id": "loc_home"},
                "relationships": {"relations": []},
                "knowledge": {"entries": []},
            }
        ],
    )
    assert accepted.status_code == 200, accepted.text

    next_packet = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": "Продолжить"},
        ),
    )
    nora = _registry_entry(next_packet, "char_nora")
    assert nora["name"] == "Нора Рейн"
    assert nora["card_level"] == "important"
    assert nora["role"].startswith("Новый важный NPC")
