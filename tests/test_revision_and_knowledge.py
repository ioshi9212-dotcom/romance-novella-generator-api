from copy import deepcopy

from tests.conftest import (
    collect_packet,
    commit_next_turn,
    complete_checklist,
    create_session,
    full_character_card,
    scene_output,
    scene_state_update,
)


def test_revision_does_not_increment_turn_and_supersedes_old_event(
    client, service, session_payload
) -> None:
    session_id = create_session(client, session_payload)
    _packet, first_commit = commit_next_turn(
        client,
        session_id,
        player_input="Первый вариант",
        event_text="Событие старой редакции",
    )
    assert first_commit["turn_number"] == 1

    revise_packet = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": "Стоп, перепиши", "mode": "revise_last"},
        ),
    )
    assert revise_packet["turn_number"] == 1
    assert revise_packet["turn_revision"] == 2
    assert revise_packet["cycle_position"] == 1

    revised = client.post(
        f"/api/v1/sessions/{session_id}/turns/commit",
        json={
            "turn_id": revise_packet["turn_id"],
            "expected_state_revision": revise_packet["expected_state_revision"],
            "scene_output": scene_output(1, 1, "Переписанная сцена."),
            "summary": "Исправленная версия первого хода",
            "scene_id": "scene_0001",
            "story_datetime": "2025-09-08T10:01:00",
            "events": [
                {
                    "scene_id": "scene_0001",
                    "story_datetime": "2025-09-08T10:01:00",
                    "location_id": "loc_home",
                    "participants_present": ["char_emily", "char_chloe"],
                    "event": "Событие новой редакции",
                }
            ],
            "state_updates": {"scene_state": scene_state_update(1)},
        },
    )
    assert revised.status_code == 200, revised.text
    assert revised.json()["turn_number"] == 1
    assert revised.json()["turn_revision"] == 2
    assert revised.json()["next_turn_number"] == 2

    chronology = client.get(
        f"/api/v1/sessions/{session_id}/chronology?include_inactive=true"
    ).json()["events"]
    assert [event["status"] for event in chronology] == ["superseded", "active"]
    assert chronology[1]["supersedes_event_id"] == chronology[0]["event_id"]


def test_knowledge_and_relationships_remain_character_scoped(
    client, service, session_payload
) -> None:
    session_id = create_session(client, session_payload)
    chloe_knowledge = {
        "entries": [
            {
                "knowledge_id": "know_0001",
                "fact": "Эмили получила странное уведомление",
                "acquisition_type": "told_directly",
                "source_character_id": "char_emily",
                "event_id": "event_pending",
                "belief_accuracy": "partial",
                "confidence": "high",
                "limits": ["Не знает отправителя"],
                "status": "active",
            }
        ]
    }
    emily_relations = {
        "relations": [
            {
                "target_character_id": "char_chloe",
                "relationship_type": "friend",
                "relationship_context": "Давняя дружба Эмили и Хлои",
                "current_dynamic": "Эмили доверяет Хлое личный разговор",
                "dimensions": [
                    {"key": "trust", "label": "доверие", "value": 60}
                ],
                "change_reasons": ["Хлоя сохранила разговор в тайне"],
                "last_changed_turn": 1,
            }
        ]
    }
    commit_next_turn(
        client,
        session_id,
        player_input="Рассказать Хлое",
        state_updates={
            "characters": [
                {"character_id": "char_chloe", "knowledge": chloe_knowledge},
                {"character_id": "char_emily", "relationships": emily_relations},
            ]
        },
    )

    chloe = service.storage.read_json(
        session_id, "characters/char_chloe/knowledge.json"
    )
    emily = service.storage.read_json(
        session_id, "characters/char_emily/knowledge.json"
    )
    emily_relationships = service.storage.read_json(
        session_id, "characters/char_emily/relationships.json"
    )
    chloe_relationships = service.storage.read_json(
        session_id, "characters/char_chloe/relationships.json"
    )
    assert chloe["character_id"] == "char_chloe"
    assert chloe["entries"][0]["knowledge_id"] == "know_0001"
    assert emily["entries"] == []
    assert emily_relationships["owner_character_id"] == "char_emily"
    assert emily_relationships["relations"][0]["target_character_id"] == "char_chloe"
    assert chloe_relationships["relations"] == []


def test_revising_an_audited_turn_invalidates_audit_and_its_corrections(
    client, service, session_payload
) -> None:
    session_id = create_session(client, session_payload)
    for turn_number in range(1, 16):
        commit_next_turn(
            client,
            session_id,
            player_input=f"Ход {turn_number}",
            event_text=f"Событие {turn_number}",
        )

    chronology_before = client.get(f"/api/v1/sessions/{session_id}/chronology").json()[
        "events"
    ]
    event_to_correct = chronology_before[0]["event_id"]
    events_to_compact = [event["event_id"] for event in chronology_before[1:5]]
    audit_packet = collect_packet(
        client,
        session_id,
        client.get(f"/api/v1/sessions/{session_id}/audit-packet"),
    )
    audit_commit = client.post(
        f"/api/v1/sessions/{session_id}/audits/commit",
        json={
            "audit_id": audit_packet["audit_id"],
            "expected_state_revision": audit_packet["expected_state_revision"],
            "checklist": complete_checklist(),
            "findings": {"correction": "Уточнено первое событие"},
            "chronology_corrections": [
                {
                    "turn_number": 1,
                    "supersedes_event_id": event_to_correct,
                    "scene_id": "scene_0001",
                    "story_datetime": "2025-09-08T10:01:00",
                    "location_id": "loc_home",
                    "participants_present": ["char_emily", "char_chloe"],
                    "event": "Уточнённое событие первого хода",
                }
            ],
            "chronology_compactions": [
                {
                    "turn_number": 5,
                    "compacts_event_ids": events_to_compact,
                    "scene_id": "scene_0005",
                    "story_datetime": "2025-09-08T10:05:00",
                    "location_id": "loc_home",
                    "participants_present": ["char_emily", "char_chloe"],
                    "event": "Компактная сводка событий 2–5",
                }
            ],
        },
    )
    assert audit_commit.status_code == 200, audit_commit.text
    effective_after_audit = client.get(
        f"/api/v1/sessions/{session_id}/chronology"
    ).json()["events"]
    effective_ids = {event["event_id"] for event in effective_after_audit}
    assert not effective_ids.intersection(events_to_compact)

    revise_packet = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": "Переписать пятнадцатый ход", "mode": "revise_last"},
        ),
    )
    revised = client.post(
        f"/api/v1/sessions/{session_id}/turns/commit",
        json={
            "turn_id": revise_packet["turn_id"],
            "expected_state_revision": revise_packet["expected_state_revision"],
            "scene_output": scene_output(15, 15, "Новая версия пятнадцатого хода."),
            "summary": "Переписан пятнадцатый ход",
            "scene_id": "scene_0015",
            "story_datetime": "2025-09-08T10:15:00",
            "events": [
                {
                    "scene_id": "scene_0015",
                    "story_datetime": "2025-09-08T10:15:00",
                    "location_id": "loc_home",
                    "participants_present": ["char_emily", "char_chloe"],
                    "event": "Новая версия события 15",
                }
            ],
            "state_updates": {"scene_state": scene_state_update(15)},
        },
    )
    assert revised.status_code == 200, revised.text
    assert revised.json()["last_audited_turn"] == 0
    assert revised.json()["audit_required"] is True

    audit = service.storage.read_json(
        session_id, f"audits/{audit_packet['audit_id']}.json"
    )
    assert audit["status"] == "invalidated"
    chronology_after = client.get(
        f"/api/v1/sessions/{session_id}/chronology?include_inactive=true"
    ).json()["events"]
    correction_id = audit["created_correction_event_ids"][0]
    compaction_id = audit["created_compaction_event_ids"][0]
    correction = next(
        event for event in chronology_after if event["event_id"] == correction_id
    )
    compaction = next(
        event for event in chronology_after if event["event_id"] == compaction_id
    )
    assert correction["status"] == "superseded"
    assert compaction["status"] == "superseded"
    effective_after_invalidation = client.get(
        f"/api/v1/sessions/{session_id}/chronology"
    ).json()["events"]
    effective_ids = {event["event_id"] for event in effective_after_invalidation}
    assert set(events_to_compact).issubset(effective_ids)

    blocked = client.post(
        f"/api/v1/sessions/{session_id}/turn-packet",
        json={"player_input": "Нельзя писать ход 16 до повторной сверки"},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "AUDIT_REQUIRED"


def test_minor_npc_can_be_promoted_with_the_same_id(
    client, service, session_payload
) -> None:
    session_id = create_session(client, session_payload)
    packet = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": "Принять доставку"},
        ),
    )
    first = client.post(
        f"/api/v1/sessions/{session_id}/turns/commit",
        json={
            "turn_id": packet["turn_id"],
            "expected_state_revision": packet["expected_state_revision"],
            "scene_output": scene_output(1, 1),
            "summary": "Появился курьер",
            "scene_id": "scene_0001",
            "story_datetime": "2025-09-08T10:01:00",
            "events": [
                {
                    "scene_id": "scene_0001",
                    "story_datetime": "2025-09-08T10:01:00",
                    "location_id": "loc_home",
                    "participants_present": ["char_emily"],
                    "event": "Курьер передал пакет",
                    "minor_npcs": [
                        {
                            "npc_id": "npc_courier",
                            "role": "курьер",
                            "distinguishing_detail": "серебряное кольцо",
                            "first_appearance_turn": 1,
                        }
                    ],
                }
            ],
            "state_updates": {"scene_state": scene_state_update(1)},
        },
    )
    assert first.status_code == 200, first.text

    courier_card = full_character_card(
        "npc_courier", "unknown", "Повторяющийся курьер с собственной целью."
    )
    courier_card["card_level"] = "recurring"
    courier_card["origin"] = "runtime"

    commit_next_turn(
        client,
        session_id,
        player_input="Остановить курьера",
        state_updates={
            "characters": [
                {
                    "character_id": "npc_courier",
                    "card": courier_card,
                    "current_state": {"current_location_id": "loc_home"},
                    "relationships": {"relations": []},
                    "knowledge": {"entries": []},
                }
            ]
        },
    )
    manifest = service.storage.read_json(session_id, "manifest.json")
    assert "npc_courier" in manifest["character_ids"]
    card = service.storage.read_json(session_id, "characters/npc_courier/card.json")
    assert card["character_id"] == "npc_courier"


def test_character_card_update_cannot_silently_change_established_facts(
    client, session_payload
) -> None:
    session_id = create_session(client, session_payload)
    packet = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": "Продолжить разговор"},
        ),
    )
    changed_card = deepcopy(session_payload["characters"][0]["card"])
    changed_card["appearance"]["eyes"] = "голубые"
    response = client.post(
        f"/api/v1/sessions/{session_id}/turns/commit",
        json={
            "turn_id": packet["turn_id"],
            "expected_state_revision": packet["expected_state_revision"],
            "scene_output": scene_output(1, 1),
            "summary": "Попытка незаметно изменить канон",
            "scene_id": "scene_0001",
            "story_datetime": "2025-09-08T10:01:00",
            "events": [
                {
                    "scene_id": "scene_0001",
                    "story_datetime": "2025-09-08T10:01:00",
                    "location_id": "loc_home",
                    "participants_present": ["char_emily", "char_chloe"],
                    "event": "Продолжился разговор",
                }
            ],
            "state_updates": {
                "scene_state": scene_state_update(1),
                "characters": [
                    {"character_id": "char_emily", "card": changed_card}
                ]
            },
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CHARACTER_CARD_FACT_LOSS"


def test_location_update_cannot_silently_replace_visual_canon(
    client, session_payload
) -> None:
    session_id = create_session(client, session_payload)
    packet = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": "Вернуться домой"},
        ),
    )
    changed_location = deepcopy(session_payload["locations"][0]["state"])
    changed_location["canon"]["layout"] = "три этажа и отдельное восточное крыло"
    response = client.post(
        f"/api/v1/sessions/{session_id}/turns/commit",
        json={
            "turn_id": packet["turn_id"],
            "expected_state_revision": packet["expected_state_revision"],
            "scene_output": scene_output(1, 1),
            "summary": "Попытка незаметно изменить планировку",
            "scene_id": "scene_0001",
            "story_datetime": "2025-09-08T10:01:00",
            "events": [
                {
                    "scene_id": "scene_0001",
                    "story_datetime": "2025-09-08T10:01:00",
                    "location_id": "loc_home",
                    "participants_present": ["char_emily", "char_chloe"],
                    "event": "Эмили вернулась домой",
                }
            ],
            "state_updates": {
                "scene_state": scene_state_update(1),
                "locations": [
                    {"location_id": "loc_home", "state": changed_location}
                ]
            },
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "LOCATION_CANON_CONFLICT"
