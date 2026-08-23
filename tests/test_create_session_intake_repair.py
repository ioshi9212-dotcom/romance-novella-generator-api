import json
import re
from copy import deepcopy

from fastapi.testclient import TestClient

from app.config import Settings
from app.enhanced_writer_service import EnhancedWriterNovellaService
from app.main import app
from tests.conftest import scene_output

SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def _partial_character(raw_id, name, role, *, target=None):
    relations = []
    if target:
        relations.append(
            {
                "target_character_id": target,
                "relationship_type": "подтверждённая связь",
                "current_dynamic": "отношения уже существуют до первой сцены",
                "dimensions": {"доверие": 62, "tension": "18"},
            }
        )
    return {
        "character_id": raw_id,
        "card": {
            "character_id": raw_id,
            "card_level": "player_defined",
            "origin": "player",
            "card_hint": f"{name}: {role}.",
            "identity": {"name": name, "role": role},
            "appearance": {"hair": "тёмные", "eyes": "серые"},
            "personality": {"inner_character": "действует из собственных целей"},
            "goals": {"personal": f"реализовать собственную линию: {role}"},
        },
        "current_state": {"current_location_id": "Восточный сектор"},
        "relationships": {"relations": relations},
        "knowledge": {"entries": []},
    }


def test_large_confirmed_setup_is_repaired_then_uses_chunked_turn_protocol(
    tmp_path, session_payload
) -> None:
    service = EnhancedWriterNovellaService(
        Settings(
            data_dir=tmp_path / "data",
            public_base_url="https://example.test",
            packet_chunk_chars=4_000,
        )
    )
    app.state.service = service
    client = TestClient(app)
    names = [
        ("Елена", "Елена Высоцкая", "POV и новая жительница сектора"),
        ("близнец", "Эйден Вернер", "один из близнецов Вернеров"),
        ("близнец", "Лиам Вернер", "второй из близнецов Вернеров"),
        (None, "Рэя", "жительница Восточного сектора"),
        ("Райан Нокс", "Райан Нокс", "значимый знакомый"),
        ("Адриан Браун", "Адриан Браун", "значимый знакомый"),
        ("Джейден Морита", "Джейден Морита", "значимый житель сектора"),
        ("Вероника Морита", "Вероника Морита", "значимая жительница сектора"),
        ("Таяна", "Таяна", "жительница сектора"),
        ("Юна", "Юна", "жительница сектора"),
    ]
    payload = deepcopy(session_payload)
    payload["runtime_contract_version"] = "2.0"
    payload["novel"] = {
        "title": "По ту сторону Аверна",
        "genre": ["романтика", "мистика"],
        "pov_character_id": "Елена",
    }
    payload["plot_state"] = {
        "active_lines": ["Прибытие Елены меняет привычный порядок Восточного сектора"]
    }
    payload["director_plan"] = {
        "active_threads": [],
        "character_agendas": [],
    }
    payload["world_state"] = {"story_datetime": "2026-08-18T09:00:00"}
    payload["scene_state"] = {
        "turn_number": 0,
        "scene_id": "стартовая сцена",
        "story_datetime": "2026-08-18T09:00:00",
        "location_id": "Восточный сектор",
        "present_character_ids": ["Елена", "Эйден Вернер", "Лиам Вернер"],
    }
    payload["characters"] = [
        _partial_character(raw_id, name, role, target="Елена" if index else None)
        for index, (raw_id, name, role) in enumerate(names)
    ]
    payload["locations"] = [
        {
            "location_id": "Восточный сектор",
            "state": {
                "canon": {
                    "name": "Восточный сектор",
                    "purpose": "жилой сектор Аверна",
                }
            },
        }
    ]

    created = client.post("/api/v1/sessions", json=payload)

    assert created.status_code == 200, created.text
    assert len(created.content) < 8_000
    result = created.json()
    assert result["creation_verified"] is True
    assert result["normalization_applied"] is True
    assert "Immediately call getTurnPacket" in result["next_required_action"]
    session_id = result["session_id"]

    manifest = service.storage.read_json(session_id, "manifest.json")
    assert len(manifest["character_ids"]) == 10
    assert len(set(manifest["character_ids"])) == 10
    assert all(SAFE_ID_RE.fullmatch(item) for item in manifest["character_ids"])
    stored_names = {
        service.storage.read_json(session_id, f"characters/{character_id}/card.json")[
            "identity"
        ]["name"]
        for character_id in manifest["character_ids"]
    }
    assert stored_names == {name for _, name, _ in names}
    report = service.storage.read_json(session_id, "intake/normalization_report.json")
    assert report["creation_verified"] is True
    assert report["notes"]

    first = client.post(
        f"/api/v1/sessions/{session_id}/turn-packet",
        json={
            "player_input": "Начать стартовую сцену по подтверждённым данным",
            "mode": "new",
            "client_request_id": "opening-turn-1",
        },
    )
    assert first.status_code == 200, first.text
    first_chunk = first.json()
    assert first_chunk["chunk_count"] > 1
    assert first_chunk["all_chunks_delivered"] is False
    assert first_chunk["next_chunk_index"] == 1

    chunks = [first_chunk["content"]]
    final_chunk = first_chunk
    for index in range(1, first_chunk["chunk_count"]):
        chunk = client.get(
            f"/api/v1/sessions/{session_id}/turn-packets/"
            f"{first_chunk['packet_id']}/chunks/{index}"
        )
        assert chunk.status_code == 200, chunk.text
        final_chunk = chunk.json()
        chunks.append(final_chunk["content"])
    assert final_chunk["all_chunks_delivered"] is True
    packet = json.loads("".join(chunks))

    pov_id = packet["scene_focus"]["pov_character_id"]
    present_ids = packet["state"]["scene_state"]["present_character_ids"]
    location_id = packet["state"]["scene_state"]["location_id"]
    story_datetime = "2026-08-18T09:05:00"
    committed = client.post(
        f"/api/v1/sessions/{session_id}/turns/commit",
        json={
            "turn_id": packet["turn_id"],
            "expected_state_revision": packet["expected_state_revision"],
            "scene_output": scene_output(
                1, 1, "День 1\nЕлена вошла в Восточный сектор."
            ),
            "summary": "Елена прибыла в Восточный сектор.",
            "scene_id": "scene_0001",
            "story_datetime": story_datetime,
            "events": [
                {
                    "scene_id": "scene_0001",
                    "story_datetime": story_datetime,
                    "location_id": location_id,
                    "participants_present": present_ids,
                    "event": "Елена прибыла в Восточный сектор.",
                }
            ],
            "state_updates": {
                "scene_state": {
                    "turn_number": 1,
                    "scene_id": "scene_0001",
                    "story_datetime": story_datetime,
                    "location_id": location_id,
                    "present_character_ids": present_ids,
                    "entered_character_ids": [],
                    "left_character_ids": [],
                }
            },
        },
    )
    assert pov_id in present_ids
    assert committed.status_code == 200, committed.text
    assert committed.json()["last_completed_turn"] == 1
