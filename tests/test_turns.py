from __future__ import annotations

import json

from app.config import MAX_CONTEXT_CHUNK_CHARS, MAX_CONTEXT_CHUNKS, SESSIONS_DIR
from tests.conftest import activate_session


def _prepare(client, headers, session_id, mode="play", user_input="Доброе утро."):
    response = client.post(
        f"/v1/sessions/{session_id}/turns",
        headers=headers,
        json={"mode": mode, "user_input": user_input},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _play_commit():
    return {
        "scene_text": "Утро в кафе началось с тихого звона чашки.",
        "scene_summary": "Посетитель заговорил с героиней у стойки.",
        "current_patch": {"last_pose": "у стойки"},
        "time_advance_minutes": 5,
        "character_patches": [],
        "new_characters": [],
        "knowledge_events": [
            {
                "character_id": "npc",
                "fact": "Героиня работает утром",
                "status": "fact",
                "source": "личное наблюдение в кафе",
            }
        ],
        "relationship_events": [
            {
                "from_character_id": "npc",
                "to_character_id": "pov",
                "metric": "interest",
                "delta": 2,
                "reason": "Ему понравилась её спокойная реакция",
            }
        ],
        "plotline_patches": [
            {"plotline_id": "main", "changes": {"current_stage": "first_contact"}}
        ],
        "chronology_event": {
            "start": "2026-09-02T08:00:00+10:00",
            "end": "2026-09-02T08:05:00+10:00",
            "location_id": "cafe",
            "events": ["Посетитель заговорил с героиней"],
        },
        "audit_updates": {},
    }


def test_prepare_is_frozen_and_repeatable(client, auth_headers):
    session_id = activate_session(client, auth_headers, "P")
    first = _prepare(client, auth_headers, session_id)
    second = _prepare(client, auth_headers, session_id)
    assert first["turn_id"] == second["turn_id"]
    assert first["input_hash"] == second["input_hash"]
    assert len(json.dumps(first, ensure_ascii=False)) < 30000

    if first["has_more"]:
        chunk = client.get(
            f"/v1/sessions/{session_id}/turns/{first['turn_id']}/chunks/{first['next_chunk_index']}",
            headers=auth_headers,
        )
        assert chunk.status_code == 200
        assert chunk.json()["turn_id"] == first["turn_id"]


def test_commit_is_idempotent_and_persists_scene(client, auth_headers):
    session_id = activate_session(client, auth_headers, "I")
    prepared = _prepare(client, auth_headers, session_id)
    url = f"/v1/sessions/{session_id}/turns/{prepared['turn_id']}/commit"
    first = client.post(url, headers=auth_headers, json=_play_commit())
    assert first.status_code == 200, first.text
    second = client.post(url, headers=auth_headers, json=_play_commit())
    assert second.status_code == 200, second.text
    assert second.json() == first.json()

    root = SESSIONS_DIR / session_id
    session = json.loads((root / "session.json").read_text())
    assert session["turn_number"] == 1
    assert session["state_version"] == 2
    assert (root / "scenes" / "000001.md").is_file()
    relationships = json.loads((root / "state" / "relationships.json").read_text())
    metric = relationships["pairs"]["npc__pov"]["directions"]["npc->pov"]["metrics"]["interest"]
    assert metric == 2
    status = client.get(f"/v1/sessions/{session_id}", headers=auth_headers).json()
    assert status["pending_turn_id"] is None


def test_technical_commit_does_not_advance_turn(client, auth_headers):
    session_id = activate_session(client, auth_headers, "T")
    prepared = _prepare(
        client,
        auth_headers,
        session_id,
        mode="technical",
        user_input="Исправь цвет волос.",
    )
    response = client.post(
        f"/v1/sessions/{session_id}/turns/{prepared['turn_id']}/commit",
        headers=auth_headers,
        json={
            "scene_text": "",
            "scene_summary": "",
            "current_patch": {},
            "character_patches": [
                {"character_id": "npc", "changes": {"appearance": {"hair": "рыжие"}}}
            ],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["turn_number"] == 0
    assert response.json()["new_state_version"] == 2
    card = json.loads(
        (SESSIONS_DIR / session_id / "state" / "characters" / "npc.json").read_text()
    )
    assert card["appearance"]["hair"] == "рыжие"


def test_stale_commit_is_rejected(client, auth_headers):
    session_id = activate_session(client, auth_headers, "S")
    prepared = _prepare(client, auth_headers, session_id)
    root = SESSIONS_DIR / session_id
    session_path = root / "session.json"
    session = json.loads(session_path.read_text())
    session["state_version"] += 1
    session_path.write_text(json.dumps(session), encoding="utf-8")
    response = client.post(
        f"/v1/sessions/{session_id}/turns/{prepared['turn_id']}/commit",
        headers=auth_headers,
        json=_play_commit(),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "state_version_conflict"


def test_new_character_can_be_patched_and_learn_in_same_commit(client, auth_headers):
    session_id = activate_session(client, auth_headers, "N")
    prepared = _prepare(
        client,
        auth_headers,
        session_id,
        mode="technical",
        user_input="Добавь нового персонажа.",
    )
    response = client.post(
        f"/v1/sessions/{session_id}/turns/{prepared['turn_id']}/commit",
        headers=auth_headers,
        json={
            "new_characters": [
                {
                    "character_id": "barista",
                    "card": {"name": "Бариста", "appearance": {"hair": "чёрные"}},
                    "starting_knowledge": [
                        {
                            "entry_id": "bootstrap:1",
                            "fact": "Кафе открывается в восемь",
                            "status": "fact",
                            "source": "рабочий график",
                        }
                    ],
                }
            ],
            "character_patches": [
                {
                    "character_id": "barista",
                    "changes": {"personality": {"core": "внимательный"}},
                }
            ],
            "knowledge_events": [
                {
                    "character_id": "barista",
                    "fact": "Героиня ждёт важного посетителя",
                    "status": "heard_fragment",
                    "source": "обрывок разговора у стойки",
                }
            ],
        },
    )
    assert response.status_code == 200, response.text

    root = SESSIONS_DIR / session_id
    card = json.loads((root / "state" / "characters" / "barista.json").read_text())
    knowledge = json.loads((root / "state" / "knowledge" / "barista.json").read_text())
    assert card["name"] == "Бариста"
    assert card["appearance"]["hair"] == "чёрные"
    assert card["personality"]["core"] == "внимательный"
    assert [entry["fact"] for entry in knowledge["entries"]] == [
        "Кафе открывается в восемь",
        "Героиня ждёт важного посетителя",
    ]


def test_large_context_is_split_into_bounded_frozen_chunks(client, auth_headers):
    session_id = activate_session(client, auth_headers, "L")
    root = SESSIONS_DIR / session_id
    lore_path = root / "state" / "lore.json"
    lore = json.loads(lore_path.read_text())
    lore["summary"] = "Длинный фрагмент мира. " * 1800
    lore_path.write_text(json.dumps(lore, ensure_ascii=False), encoding="utf-8")

    prepared = _prepare(client, auth_headers, session_id, user_input="Осмотрись вокруг.")
    assert 1 < prepared["total_chunks"] <= MAX_CONTEXT_CHUNKS

    responses = [prepared]
    for chunk_index in range(1, prepared["total_chunks"]):
        response = client.get(
            f"/v1/sessions/{session_id}/turns/{prepared['turn_id']}/chunks/{chunk_index}",
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        responses.append(response.json())

    for response in responses:
        sections = response["chunk"]["sections"]
        assert len(json.dumps(sections, ensure_ascii=False, separators=(",", ":"))) <= (
            MAX_CONTEXT_CHUNK_CHARS
        )
        assert len(json.dumps(response, ensure_ascii=False)) < 30000
