import json
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


def _turn_commit_body(packet: dict, *, participants: list[str]) -> dict:
    return {
        "turn_id": packet["turn_id"],
        "expected_state_revision": packet["expected_state_revision"],
        "scene_output": scene_output(packet["turn_number"], packet["cycle_position"]),
        "summary": "Проверена целостность пакета и финального кадра",
        "scene_id": f"scene_{packet['turn_number']:04d}",
        "story_datetime": f"2025-09-08T10:{packet['turn_number']:02d}:00",
        "events": [
            {
                "scene_id": f"scene_{packet['turn_number']:04d}",
                "story_datetime": f"2025-09-08T10:{packet['turn_number']:02d}:00",
                "location_id": "loc_home",
                "participants_present": participants,
                "event": "Установлен факт тестового хода",
            }
        ],
        "state_updates": {
            "scene_state": scene_state_update(
                packet["turn_number"], present_character_ids=participants
            )
        },
    }


def test_turn_commit_is_blocked_until_every_chunk_is_delivered_in_order(
    client, service, session_payload
) -> None:
    session_id = create_session(client, session_payload)
    first = client.post(
        f"/api/v1/sessions/{session_id}/turn-packet",
        json={"player_input": "Продолжить разговор"},
    )
    assert first.status_code == 200, first.text
    first_meta = first.json()
    assert first_meta["chunk_count"] > 1
    assert first_meta["delivered_chunk_count"] == 1
    assert first_meta["all_chunks_delivered"] is False

    pending = service.storage.read_json(session_id, "pending_turn.json")
    early_bundle = client.post(
        f"/api/v1/sessions/{session_id}/turn-packets/{first_meta['packet_id']}"
        "/scene-characters/char_chloe/bundle",
        json={
            "turn_id": pending["turn_id"],
            "entry_reason": "Проверка запрета до полного чтения turn packet",
        },
    )
    assert early_bundle.status_code == 409
    assert early_bundle.json()["error"]["code"] == "TURN_PACKET_INCOMPLETE"

    out_of_order = client.get(
        f"/api/v1/sessions/{session_id}/turn-packets/"
        f"{first_meta['packet_id']}/chunks/2"
    )
    assert out_of_order.status_code == 409
    assert out_of_order.json()["error"]["code"] == (
        "TURN_PACKET_CHUNK_OUT_OF_ORDER"
    )

    blocked_packet = {
        "turn_id": pending["turn_id"],
        "turn_number": pending["turn_number"],
        "cycle_position": pending["cycle_position"],
        "expected_state_revision": pending["expected_state_revision"],
    }
    blocked = client.post(
        f"/api/v1/sessions/{session_id}/turns/commit",
        json=_turn_commit_body(
            blocked_packet, participants=["char_emily", "char_chloe"]
        ),
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "TURN_PACKET_INCOMPLETE"

    packet = collect_packet(client, session_id, first)
    assert "Режиссёрский план и автономное время" in packet["rules"]
    assert "Режиссёрская цель" in packet["scene_builder"]
    assert packet["scene_focus"]["required_full_character_ids"] == [
        "char_emily",
        "char_chloe",
    ]
    committed = client.post(
        f"/api/v1/sessions/{session_id}/turns/commit",
        json=_turn_commit_body(packet, participants=["char_emily", "char_chloe"]),
    )
    assert committed.status_code == 200, committed.text


def test_audit_commit_is_blocked_until_every_audit_chunk_is_delivered(
    client, service, session_payload
) -> None:
    session_id = create_session(client, session_payload)
    for turn_number in range(1, 16):
        commit_next_turn(
            client,
            session_id,
            player_input=f"Ход {turn_number}",
        )

    first = client.get(f"/api/v1/sessions/{session_id}/audit-packet")
    assert first.status_code == 200, first.text
    assert first.json()["chunk_count"] > 1
    pending = service.storage.read_json(session_id, "pending_audit.json")
    body = {
        "audit_id": pending["audit_id"],
        "expected_state_revision": pending["expected_state_revision"],
        "checklist": complete_checklist(),
        "findings": {"result": "Все категории проверены"},
    }
    blocked = client.post(
        f"/api/v1/sessions/{session_id}/audits/commit", json=body
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "AUDIT_PACKET_INCOMPLETE"

    collect_packet(client, session_id, first)
    completed = client.post(
        f"/api/v1/sessions/{session_id}/audits/commit", json=body
    )
    assert completed.status_code == 200, completed.text


def test_known_offscreen_character_requires_and_receives_only_its_own_bundle(
    client, session_payload
) -> None:
    offscreen = {
        "character_id": "char_ryan",
        "card": full_character_card(
            "char_ryan", "Райан", "Знакомый Эмили, который сейчас находится вне сцены."
        ),
        "current_state": {"current_location_id": "loc_elsewhere"},
        "relationships": {"relations": []},
        "knowledge": {"entries": []},
    }
    session_payload["characters"].append(offscreen)
    session_id = create_session(client, session_payload)

    first = client.post(
        f"/api/v1/sessions/{session_id}/turn-packet",
        json={"player_input": "Поехать поговорить с Райаном"},
    )
    first_meta = first.json()
    packet = collect_packet(client, session_id, first)
    assert {
        item["character_id"] for item in packet["state"]["characters"]
    } == {"char_emily", "char_chloe"}

    body = _turn_commit_body(packet, participants=["char_emily", "char_ryan"])
    body["state_updates"]["scene_state"]["entered_character_ids"] = ["char_ryan"]
    body["state_updates"]["scene_state"]["left_character_ids"] = ["char_chloe"]
    rejected = client.post(
        f"/api/v1/sessions/{session_id}/turns/commit", json=body
    )
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "SCENE_CHARACTER_BUNDLE_REQUIRED"

    first_bundle = client.post(
        f"/api/v1/sessions/{session_id}/turn-packets/{first_meta['packet_id']}"
        "/scene-characters/char_ryan/bundle",
        json={
            "turn_id": packet["turn_id"],
            "entry_reason": "Эмили приехала к Райану, и он участвует в разговоре",
        },
    )
    assert first_bundle.status_code == 200, first_bundle.text
    bundle_meta = first_bundle.json()
    assert bundle_meta["chunk_count"] > 1
    incomplete = client.post(
        f"/api/v1/sessions/{session_id}/turns/commit", json=body
    )
    assert incomplete.status_code == 409
    assert incomplete.json()["error"]["code"] == (
        "SCENE_CHARACTER_BUNDLE_INCOMPLETE"
    )
    chunks = [bundle_meta["content"]]
    for index in range(1, bundle_meta["chunk_count"]):
        response = client.get(
            f"/api/v1/sessions/{session_id}/turn-packets/{first_meta['packet_id']}"
            f"/scene-character-bundles/{bundle_meta['bundle_id']}/chunks/{index}"
        )
        assert response.status_code == 200, response.text
        chunks.append(response.json()["content"])
    raw_bundle = "".join(chunks)
    assert bundle_meta["content_sha256"] == __import__("hashlib").sha256(
        raw_bundle.encode()
    ).hexdigest()
    bundle = json.loads(raw_bundle)
    assert bundle["character_id"] == "char_ryan"
    assert bundle["character"]["character_id"] == "char_ryan"
    assert "char_chloe" not in "".join(chunks)

    committed = client.post(
        f"/api/v1/sessions/{session_id}/turns/commit", json=body
    )
    assert committed.status_code == 200, committed.text


def test_scene_state_must_match_turn_and_keep_pov_present(
    client, session_payload
) -> None:
    session_id = create_session(client, session_payload)
    packet = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": "Продолжить"},
        ),
    )
    body = _turn_commit_body(packet, participants=["char_emily", "char_chloe"])

    wrong_turn = deepcopy(body)
    wrong_turn["state_updates"]["scene_state"]["turn_number"] = 2
    rejected_turn = client.post(
        f"/api/v1/sessions/{session_id}/turns/commit", json=wrong_turn
    )
    assert rejected_turn.status_code == 422
    assert rejected_turn.json()["error"]["code"] == "SCENE_STATE_TURN_MISMATCH"

    missing_pov = deepcopy(body)
    missing_pov["events"][0]["participants_present"] = ["char_chloe"]
    missing_pov["state_updates"]["scene_state"]["present_character_ids"] = [
        "char_chloe"
    ]
    rejected_pov = client.post(
        f"/api/v1/sessions/{session_id}/turns/commit", json=missing_pov
    )
    assert rejected_pov.status_code == 422
    assert rejected_pov.json()["error"]["code"] == "POV_MISSING_FROM_SCENE_STATE"

    committed = client.post(
        f"/api/v1/sessions/{session_id}/turns/commit", json=body
    )
    assert committed.status_code == 200, committed.text


def test_relationship_document_rejects_more_than_eight_dimensions(
    client, session_payload
) -> None:
    session_id = create_session(client, session_payload)
    packet = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": "Проверить отношения"},
        ),
    )
    body = _turn_commit_body(packet, participants=["char_emily", "char_chloe"])
    body["state_updates"]["characters"] = [
        {
            "character_id": "char_emily",
            "relationships": {
                "relations": [
                    {
                        "target_character_id": "char_chloe",
                        "relationship_type": "friend",
                        "relationship_context": "Давняя дружба",
                        "current_dynamic": "Обычный разговор",
                        "dimensions": [
                            {
                                "key": f"metric_{index}",
                                "label": f"Показатель {index}",
                                "value": index,
                            }
                            for index in range(9)
                        ],
                    }
                ]
            },
        }
    ]
    rejected = client.post(
        f"/api/v1/sessions/{session_id}/turns/commit", json=body
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "REQUEST_VALIDATION_FAILED"
