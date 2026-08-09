from tests.conftest import collect_packet, create_session, scene_output


def test_turn_packet_and_commit_are_idempotent(client, session_payload) -> None:
    session_id = create_session(client, session_payload)
    request_body = {
        "player_input": "Открыть дверь",
        "client_request_id": "request_0001",
    }
    first_response = client.post(
        f"/api/v1/sessions/{session_id}/turn-packet", json=request_body
    )
    first_packet = collect_packet(client, session_id, first_response)
    repeated_packet = collect_packet(
        client,
        session_id,
        client.post(f"/api/v1/sessions/{session_id}/turn-packet", json=request_body),
    )
    assert repeated_packet["turn_id"] == first_packet["turn_id"]

    different = client.post(
        f"/api/v1/sessions/{session_id}/turn-packet",
        json={"player_input": "Другой ход", "client_request_id": "request_0002"},
    )
    assert different.status_code == 409
    assert different.json()["error"]["code"] == "TURN_ALREADY_PENDING"

    commit_body = {
        "turn_id": first_packet["turn_id"],
        "expected_state_revision": first_packet["expected_state_revision"],
        "scene_output": scene_output(1, 1),
        "summary": "Эмили открыла дверь",
        "scene_id": "scene_0001",
        "story_datetime": "2025-09-08T10:01:00",
        "events": [
            {
                "scene_id": "scene_0001",
                "story_datetime": "2025-09-08T10:01:00",
                "location_id": "loc_home",
                "participants_present": ["char_emily"],
                "event": "Эмили открыла дверь",
            }
        ],
    }
    committed = client.post(
        f"/api/v1/sessions/{session_id}/turns/commit", json=commit_body
    )
    repeated_commit = client.post(
        f"/api/v1/sessions/{session_id}/turns/commit", json=commit_body
    )
    assert committed.status_code == 200
    assert repeated_commit.status_code == 200
    assert repeated_commit.json() == committed.json()
    chronology = client.get(f"/api/v1/sessions/{session_id}/chronology").json()[
        "events"
    ]
    assert len(chronology) == 1


def test_wrong_scene_counter_and_missing_reminder_are_rejected(
    client, session_payload
) -> None:
    session_id = create_session(client, session_payload)
    packet = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": "Проверка footer"},
        ),
    )
    base = {
        "turn_id": packet["turn_id"],
        "expected_state_revision": packet["expected_state_revision"],
        "summary": "Проверка",
        "scene_id": "scene_0001",
        "story_datetime": "2025-09-08T10:01:00",
    }
    wrong = client.post(
        f"/api/v1/sessions/{session_id}/turns/commit",
        json={**base, "scene_output": scene_output(2, 1)},
    )
    assert wrong.status_code == 422
    assert wrong.json()["error"]["code"] == "SCENE_COUNTER_MISMATCH"

    missing_reminder = client.post(
        f"/api/v1/sessions/{session_id}/turns/commit",
        json={**base, "scene_output": "Сцена.\n\nХод 1 · цикл 1/15"},
    )
    assert missing_reminder.status_code == 422
    assert missing_reminder.json()["error"]["code"] == "SCENE_REMINDER_MISSING"


def test_chronology_waits_for_scene_boundary_before_sealing_part(
    client, service, session_payload
) -> None:
    session_id = create_session(client, session_payload)
    same_scene_events = [
        {
            "turn_number": turn,
            "turn_id": f"turn_{turn}",
            "scene_id": "scene_long",
            "story_datetime": f"2025-09-08T10:{turn:02d}:00",
            "location_id": "loc_home",
            "participants_present": ["char_emily"],
            "event": f"Факт {turn}",
            "consequences": [],
            "knowledge_update_refs": [],
            "minor_npcs": [],
            "supersedes_event_id": None,
        }
        for turn in range(1, 32)
    ]
    with service.storage.session_transaction(session_id):
        writes, _ids = service._append_chronology_locked(session_id, same_scene_events)
        service.storage._write_json_batch_locked(session_id, writes)
        manifest = service.storage.read_json(session_id, "chronology/manifest.json")
        assert len(manifest["parts"]) == 1
        assert manifest["parts"][0]["sealed"] is False

        boundary_event = {
            "turn_number": 32,
            "turn_id": "turn_32",
            "scene_id": "scene_new",
            "story_datetime": "2025-09-08T11:00:00",
            "location_id": "loc_home",
            "participants_present": ["char_emily"],
            "event": "Началась новая сцена",
            "consequences": [],
            "knowledge_update_refs": [],
            "minor_npcs": [],
            "supersedes_event_id": None,
        }
        writes, _ids = service._append_chronology_locked(session_id, [boundary_event])
        service.storage._write_json_batch_locked(session_id, writes)

    manifest = service.storage.read_json(session_id, "chronology/manifest.json")
    assert len(manifest["parts"]) == 2
    assert manifest["parts"][0]["sealed"] is True
    assert manifest["parts"][0]["turn_to"] == 31
    assert manifest["parts"][1]["turn_from"] == 32
