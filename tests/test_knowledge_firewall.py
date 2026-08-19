from copy import deepcopy

from fastapi.testclient import TestClient

from app.config import Settings
from app.knowledge_firewall import knowledge_provenance_issues
from app.main import app
from app.stable_runtime_service import StableRuntimeNovellaService
from tests.conftest import collect_packet, create_session


def _client(tmp_path) -> TestClient:
    app.state.service = StableRuntimeNovellaService(
        Settings(
            data_dir=tmp_path / "knowledge-firewall-data",
            public_base_url="https://example.test",
            packet_chunk_chars=4000,
        )
    )
    return TestClient(app)


def _valid_scene_output() -> str:
    return (
        "🕒 День 1 · Понедельник, 08.09.2025, 10:01 · 📍 Дом Эмили\n"
        "Эмили продолжила разговор.\n\n"
        "Ход 1 · цикл 1/15\n"
        "↻ Перед следующим ходом: прочитать актуальный state. На 15/15 — провести сверку."
    )


def _commit_body(packet, *, events, characters, present_character_ids):
    return {
        "turn_id": packet["turn_id"],
        "expected_state_revision": packet["expected_state_revision"],
        "scene_output": _valid_scene_output(),
        "summary": "Проверка границ знания",
        "scene_id": "scene_0001",
        "story_datetime": "2025-09-08T10:01:00",
        "events": events,
        "state_updates": {
            "scene_state": {
                "turn_number": 1,
                "scene_id": "scene_0001",
                "story_datetime": "2025-09-08T10:01:00",
                "location_id": "loc_home",
                "present_character_ids": present_character_ids,
                "entered_character_ids": [],
                "left_character_ids": [],
            },
            "characters": characters,
        },
    }


def test_turn_packet_separates_objective_truth_director_secrets_and_character_knowledge(
    tmp_path, session_payload
) -> None:
    client = _client(tmp_path)
    session_id = create_session(client, session_payload)

    packet = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": "Продолжить разговор"},
        ),
    )

    assert "story_memory" not in packet
    assert packet["director_only_context"]["hidden_lore"]["facts"][0]["fact_id"] == "secret_1"
    assert "objective_chronology_memory" in packet["director_only_context"]
    assert packet["memory_boundaries"]["character_knowledge"]["source"] == (
        "state.characters[*].knowledge"
    )
    permissions = {
        item["character_id"]: item for item in packet["character_knowledge_permissions"]
    }
    assert {"char_emily", "char_chloe"}.issubset(permissions)
    assert "If Emily told Ethan something while Ren was absent" in packet["instruction"]


def test_direct_knowledge_cannot_be_given_to_character_absent_from_source_event(
    tmp_path, session_payload
) -> None:
    client = _client(tmp_path)
    payload = deepcopy(session_payload)
    payload["scene_state"]["present_character_ids"] = ["char_emily"]
    session_id = create_session(client, payload)
    packet = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": "Сказать это вслух"},
        ),
    )

    response = client.post(
        f"/api/v1/sessions/{session_id}/turns/commit",
        json=_commit_body(
            packet,
            events=[
                {
                    "scene_id": "scene_0001",
                    "story_datetime": "2025-09-08T10:01:00",
                    "location_id": "loc_home",
                    "participants_present": ["char_emily"],
                    "event": "Эмили произнесла приватную фразу",
                    "knowledge_update_refs": ["know_leak"],
                }
            ],
            characters=[
                {
                    "character_id": "char_chloe",
                    "knowledge": {
                        "entries": [
                            {
                                "knowledge_id": "know_leak",
                                "fact": "Приватная фраза Эмили",
                                "acquisition_type": "heard",
                                "status": "active",
                            }
                        ]
                    },
                }
            ],
            present_character_ids=["char_emily"],
        ),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "KNOWLEDGE_WITNESS_REQUIRED"


def test_new_personal_knowledge_requires_chronology_ref(tmp_path, session_payload) -> None:
    client = _client(tmp_path)
    session_id = create_session(client, session_payload)
    packet = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": "Рассказать Хлое"},
        ),
    )

    response = client.post(
        f"/api/v1/sessions/{session_id}/turns/commit",
        json=_commit_body(
            packet,
            events=[
                {
                    "scene_id": "scene_0001",
                    "story_datetime": "2025-09-08T10:01:00",
                    "location_id": "loc_home",
                    "participants_present": ["char_emily", "char_chloe"],
                    "event": "Эмили рассказала Хлое факт",
                    "knowledge_update_refs": [],
                }
            ],
            characters=[
                {
                    "character_id": "char_chloe",
                    "knowledge": {
                        "entries": [
                            {
                                "knowledge_id": "know_fact",
                                "fact": "Факт от Эмили",
                                "acquisition_type": "told_directly",
                                "source_character_id": "char_emily",
                                "status": "active",
                            }
                        ]
                    },
                }
            ],
            present_character_ids=["char_emily", "char_chloe"],
        ),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "KNOWLEDGE_EVENT_REF_REQUIRED"


def test_valid_direct_knowledge_is_stamped_with_provenance(tmp_path, session_payload) -> None:
    client = _client(tmp_path)
    session_id = create_session(client, session_payload)
    packet = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": "Рассказать Хлое"},
        ),
    )

    response = client.post(
        f"/api/v1/sessions/{session_id}/turns/commit",
        json=_commit_body(
            packet,
            events=[
                {
                    "scene_id": "scene_0001",
                    "story_datetime": "2025-09-08T10:01:00",
                    "location_id": "loc_home",
                    "participants_present": ["char_emily", "char_chloe"],
                    "event": "Эмили рассказала Хлое факт",
                    "knowledge_update_refs": ["know_fact"],
                }
            ],
            characters=[
                {
                    "character_id": "char_chloe",
                    "knowledge": {
                        "entries": [
                            {
                                "knowledge_id": "know_fact",
                                "fact": "Факт от Эмили",
                                "acquisition_type": "told_directly",
                                "source_character_id": "char_emily",
                                "status": "active",
                            }
                        ]
                    },
                }
            ],
            present_character_ids=["char_emily", "char_chloe"],
        ),
    )
    assert response.status_code == 200, response.text
    knowledge = app.state.service.storage.read_json(
        session_id, "characters/char_chloe/knowledge.json"
    )
    entry = next(item for item in knowledge["entries"] if item["knowledge_id"] == "know_fact")
    assert entry["source_turn"] == 1
    assert entry["source_scene_id"] == "scene_0001"
    assert entry["learned_at"] == "2025-09-08T10:01:00"
    assert entry["provenance_status"] == "verified_current_turn"


def test_provenance_audit_flags_direct_knowledge_when_owner_was_not_present() -> None:
    state = {
        "characters": [
            {
                "character_id": "char_ren",
                "card": {"identity": {"name": "Рен"}},
                "knowledge": {
                    "entries": [
                        {
                            "knowledge_id": "know_phrase",
                            "fact": "Эмили сказала, что он слишком милый, чтобы быть страшным",
                            "acquisition_type": "heard",
                            "status": "active",
                        }
                    ]
                },
            }
        ]
    }
    chronology = [
        {
            "event_id": "event_000001",
            "participants_present": ["char_emily", "char_ethan"],
            "event": "Эмили сказала Итану приватную фразу",
            "knowledge_update_refs": ["know_phrase"],
        }
    ]

    issues = knowledge_provenance_issues(state, chronology)
    assert any(
        item["reason"] == "direct_knowledge_owner_absent_from_source_event"
        and item["character_id"] == "char_ren"
        for item in issues
    )
