from copy import deepcopy

from fastapi.testclient import TestClient

from app.config import Settings
from app.enhanced_writer_service import EnhancedWriterNovellaService
from app.main import app
from tests.conftest import collect_packet, complete_checklist, full_character_card


def _client(tmp_path) -> TestClient:
    app.state.service = EnhancedWriterNovellaService(
        Settings(
            data_dir=tmp_path / "character-registry-data",
            public_base_url="https://example.test",
            packet_chunk_chars=4000,
        )
    )
    return TestClient(app)


def _add_character(payload, character_id: str, name: str, hint: str, *, origin="player", level="player_defined"):
    card = full_character_card(character_id, name, hint)
    card["origin"] = origin
    card["card_level"] = level
    payload["characters"].append(
        {
            "character_id": character_id,
            "card": card,
            "current_state": {"current_location_id": "loc_home"},
            "relationships": {"relations": []},
            "knowledge": {"entries": []},
        }
    )


def _create(client: TestClient, payload: dict) -> str:
    response = client.post("/api/v1/sessions", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


def _scene_output(title: str, turn: int, cycle: int, *, body: str = "Сцена продолжается.") -> str:
    return (
        f"🎭 {title} · осень\n"
        "🕒 День 1 · Понедельник, 08.09.2025, 10:00 · 📍 Дом Эмили\n"
        "🌦️ Погода: спокойно\n"
        "⚙️ Сцена: проверка непрерывности\n"
        "✦ Эмили\n"
        "🧥 Одежда, волосы: домашняя одежда, волосы распущены\n"
        "◈ Инвентарь: телефон\n"
        "--------------------------------------------------------\n\n"
        f"{body}\n\n"
        "Что я могу сделать:\n1. Остаться.\n2. Подойти.\n3. Отойти.\n\n"
        "Что я могу сказать:\n1. Хорошо.\n2. Понятно.\n3. Ладно.\n\n"
        "Что я могу подумать:\n1. Посмотрим.\n2. Любопытно.\n3. Хм.\n\n"
        "Состояние: спокойно\n"
        "Отношения: —\n\n"
        f"Ход {turn} · цикл {cycle}/15"
    )


def _commit_turn(
    client: TestClient,
    session_id: str,
    *,
    player_input: str,
    participants: list[str],
    event_text: str,
    state_character_updates: list[dict] | None = None,
):
    packet = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": player_input},
        ),
    )
    turn = packet["turn_number"]
    cycle = packet["cycle_position"]
    story_datetime = f"2025-09-08T10:{turn:02d}:00"
    response = client.post(
        f"/api/v1/sessions/{session_id}/turns/commit",
        json={
            "turn_id": packet["turn_id"],
            "expected_state_revision": packet["expected_state_revision"],
            "scene_output": _scene_output("Тестовая новелла", turn, cycle),
            "summary": event_text,
            "scene_id": f"scene_{turn:04d}",
            "story_datetime": story_datetime,
            "events": [
                {
                    "scene_id": f"scene_{turn:04d}",
                    "story_datetime": story_datetime,
                    "location_id": "loc_home",
                    "participants_present": participants,
                    "event": event_text,
                }
            ],
            "state_updates": {
                "scene_state": {
                    "turn_number": turn,
                    "scene_id": f"scene_{turn:04d}",
                    "story_datetime": story_datetime,
                    "location_id": "loc_home",
                    "present_character_ids": participants,
                    "entered_character_ids": [],
                    "left_character_ids": [],
                },
                "characters": state_character_updates or [],
            },
        },
    )
    assert response.status_code == 200, response.text
    return packet


def test_registry_contains_all_player_defined_and_important_runtime_characters(tmp_path, session_payload):
    client = _client(tmp_path)
    payload = deepcopy(session_payload)
    _add_character(
        payload,
        "char_nolan",
        "Нолан Ривз",
        "Сотрудник базы, важный свидетель текущего расследования.",
        origin="runtime",
        level="important",
    )
    session_id = _create(client, payload)

    packet = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": "Продолжить"},
        ),
    )
    registry = packet["story_bible"]["novel"]["character_registry"]
    by_id = {item["character_id"]: item for item in registry}

    assert {"char_emily", "char_chloe", "char_nolan"}.issubset(by_id)
    assert by_id["char_nolan"]["name"] == "Нолан Ривз"
    assert by_id["char_nolan"]["role"].startswith("Сотрудник базы")
    assert by_id["char_nolan"]["card_level"] == "important"


def test_registered_first_name_cannot_be_reused_for_another_character(tmp_path, session_payload):
    client = _client(tmp_path)
    payload = deepcopy(session_payload)
    _add_character(payload, "char_rhea", "Рэя Кейн", "Офицер базы.")
    _add_character(payload, "char_other", "Рэя Мор", "Другой персонаж.")

    response = client.post("/api/v1/sessions", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CHARACTER_NAME_RESERVED"


def test_legacy_introduction_is_exposed_as_acquainted_and_never_reset_to_stranger(tmp_path, session_payload):
    client = _client(tmp_path)
    payload = deepcopy(session_payload)
    _add_character(payload, "char_rhea", "Рэя Кейн", "Офицер базы, знакомая POV.")
    payload["scene_state"]["present_character_ids"] = ["char_emily", "char_rhea"]
    session_id = _create(client, payload)

    _commit_turn(
        client,
        session_id,
        player_input="Познакомиться с Рэей",
        participants=["char_emily", "char_rhea"],
        event_text="Эмили и Рэя познакомились, представились друг другу и обменялись именами.",
    )

    packet = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": "Снова встретить Рэю"},
        ),
    )
    rhea = next(
        item
        for item in packet["story_bible"]["novel"]["character_registry"]
        if item["character_id"] == "char_rhea"
    )
    assert rhea["continuity_status"] == "acquainted"
    assert rhea["familiarity_source"] == "legacy_chronology"
    assert rhea["encountered_with_pov"] is True
    assert rhea["legacy_familiarity_evidence"]["turn_number"] == 1


def test_fifteen_turn_audit_forces_legacy_familiarity_to_be_persisted(tmp_path, session_payload):
    client = _client(tmp_path)
    payload = deepcopy(session_payload)
    _add_character(payload, "char_rhea", "Рэя Кейн", "Офицер базы, знакомая POV.")
    payload["scene_state"]["present_character_ids"] = ["char_emily", "char_rhea"]
    session_id = _create(client, payload)

    for turn in range(1, 16):
        text = (
            "Эмили и Рэя познакомились, представились друг другу и обменялись именами."
            if turn == 1
            else f"Эмили и Рэя продолжают уже существующее знакомство, ход {turn}."
        )
        _commit_turn(
            client,
            session_id,
            player_input=f"Продолжить разговор {turn}",
            participants=["char_emily", "char_rhea"],
            event_text=text,
        )

    audit = collect_packet(
        client,
        session_id,
        client.get(f"/api/v1/sessions/{session_id}/audit-packet"),
    )
    targets = audit["character_familiarity_audit"]["backfill_targets"]
    rhea_target = next(item for item in targets if item["character_id"] == "char_rhea")
    assert rhea_target["required_status"] == "acquainted"

    base_verification = {
        "turns_checked": audit["audit_targets"]["turn_numbers"],
        "chronology_event_ids_checked": audit["audit_targets"]["chronology_event_ids"],
        "characters_checked": audit["audit_targets"]["character_ids"],
        "knowledge_checked_character_ids": audit["audit_targets"]["knowledge_character_ids"],
        "familiarity_checked_character_ids": [item["character_id"] for item in targets],
        "final_consistency_pass": True,
        "unresolved_issues": [],
    }

    rejected = client.post(
        f"/api/v1/sessions/{session_id}/audits/commit",
        json={
            "audit_id": audit["audit_id"],
            "expected_state_revision": audit["expected_state_revision"],
            "checklist": complete_checklist(),
            "findings": {"verification": base_verification},
            "state_updates": {},
        },
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "AUDIT_FAMILIARITY_BACKFILL_REQUIRED"

    completed = client.post(
        f"/api/v1/sessions/{session_id}/audits/commit",
        json={
            "audit_id": audit["audit_id"],
            "expected_state_revision": audit["expected_state_revision"],
            "checklist": complete_checklist(),
            "findings": {"verification": base_verification},
            "state_updates": {
                "characters": [
                    {
                        "character_id": "char_rhea",
                        "current_state": {
                            "pov_familiarity": {
                                "status": "acquainted",
                                "since_turn": 1,
                                "source": "legacy_audit",
                            }
                        },
                    }
                ]
            },
        },
    )
    assert completed.status_code == 200, completed.text

    packet = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": "Встретить Рэю снова"},
        ),
    )
    rhea = next(
        item
        for item in packet["story_bible"]["novel"]["character_registry"]
        if item["character_id"] == "char_rhea"
    )
    assert rhea["continuity_status"] == "acquainted"
    assert rhea["familiarity_source"] == "stored"
