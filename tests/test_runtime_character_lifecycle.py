from copy import deepcopy

from fastapi.testclient import TestClient

from app.character_profiles import enrich_character_card
from app.main import app
from app.session_manager import SessionManager
from tests.test_scene_state_invariants import _active_session, _pending_turn
from tests.test_smoke import _long_scene_response, _valid_bootstrap


def _full_new_npc() -> dict:
    raw = deepcopy(_valid_bootstrap()["characters"]["coworker_01"])
    raw.update({
        "id": "nora_west",
        "name": "Nora West",
        "display_name": "Нора Уэст",
        "role": "new significant coworker",
        "cast_status": "known_support",
        "goal": "добиться перевода на новую смену и понять, почему в кофейне скрывают ночные происшествия",
        "past_short": "Нора впервые вышла в эту кофейню после конфликта на прежнем месте работы.",
        "connections": [{"character_id": "pc_01", "relation": "new acquaintance"}],
    })
    return enrich_character_card(raw, "nora_west")


def test_incomplete_significant_new_npc_is_rejected_before_turn_write():
    client = TestClient(app)
    session_id = _active_session(client)
    player_input = "(посмотреть на новую сотрудницу)"
    turn_id = _pending_turn(client, session_id, player_input)
    response = _long_scene_response(player_input)
    response["proposed_updates"]["new_or_updated_characters"] = [
        {"id": "nora_west", "name": "Nora West", "role": "significant coworker"}
    ]

    applied = client.post(
        f"/api/v1/sessions/{session_id}/apply-turn-result",
        json={"turn_id": turn_id, "scene_response": response},
    )

    assert applied.status_code == 422
    assert any("new_or_updated_characters[0]" in error for error in applied.json()["detail"])
    assert "nora_west" not in SessionManager().storage.read_characters(session_id)


def test_full_new_npc_is_created_with_knowledge_runtime_and_relationship_pair():
    client = TestClient(app)
    session_id = _active_session(client)
    player_input = "(кивнуть новой сотруднице)"
    turn_id = _pending_turn(client, session_id, player_input)
    response = _long_scene_response(player_input)
    response["proposed_updates"]["new_or_updated_characters"] = [_full_new_npc()]
    response["proposed_updates"]["scene_state_patch"]["active_character_ids"] = ["pc_01", "nora_west"]
    response["witnesses"] = ["pc_01", "nora_west"]
    response["proposed_updates"]["knowledge_patches"] = [
        {
            "character_id": "nora_west",
            "reason": "Нора лично услышала ответ героини.",
            "source_in_scene": "Героиня кивнула и назвала своё имя.",
            "add_knows": ["Героиня представилась Норе"],
        }
    ]
    response["proposed_updates"]["npc_state_patches"] = [
        {
            "character_id": "nora_west",
            "reason": "Первый разговор изменил её ближайший план.",
            "source_in_scene": "Нора задержалась у стойки после представления.",
            "current_mood": "настороженный интерес",
        }
    ]

    applied = client.post(
        f"/api/v1/sessions/{session_id}/apply-turn-result",
        json={"turn_id": turn_id, "scene_response": response},
    )

    assert applied.status_code == 200, applied.text
    storage = SessionManager().storage
    card = storage.read_characters(session_id)["nora_west"]
    assert card["locked"] is True
    assert card["introduced"] is True
    assert card["available_to_scene"] is True
    assert card["behavior"]["stress_response"]
    assert storage.read_knowledge(session_id)["nora_west"]["known_facts"]
    assert storage.read_json(session_id, "npc_state.json")["nora_west"]["current_mood"] == "настороженный интерес"
    relationship = storage.read_relationships(session_id)["nora_west__pc_01"]
    assert relationship["a_to_b"]
    assert relationship["b_to_a"]


def _active_session_with_hidden_character(client: TestClient) -> str:
    bootstrap = _valid_bootstrap()
    hidden_raw = deepcopy(bootstrap["characters"]["coworker_01"])
    hidden_raw.update({
        "id": "eiden_cross",
        "name": "Eiden Cross",
        "display_name": "Эйден Кросс",
        "role": "future major stranger",
        "cast_status": "hidden_core",
        "goal": "найти источник повторяющегося мистического следа раньше конкурентов",
        "past_short": "Эйден приехал в город по личной причине, которую пока никому не объясняет.",
        "connections": [],
    })
    bootstrap["characters"]["eiden_cross"] = enrich_character_card(hidden_raw, "eiden_cross")
    bootstrap["knowledge"]["eiden_cross"] = {
        "character_id": "eiden_cross",
        "known_facts": [],
        "observations": [],
        "assumptions": [],
        "wrong_beliefs": [],
        "does_not_know": [],
        "must_not_assume": [],
        "recent_memories": [],
        "open_questions": [],
        "knows": [],
    }
    bootstrap["future_locks"] = {
        "hidden_character_ids": ["eiden_cross"],
        "hidden_character_seeds": [],
        "do_not_reveal_yet": ["Эйден не появляется до первой причинной встречи"],
    }
    bootstrap["director_bible"] = {
        "planned_reveals": [
            {
                "id": "reveal_eiden",
                "reveal": "Эйден входит в историю как реальный участник",
                "status": "locked",
                "earliest_turn": 1,
                "related_character_ids": ["eiden_cross"],
                "prerequisites": ["личная встреча в видимой сцене"],
            }
        ]
    }

    created = client.post(
        "/api/v1/sessions",
        json={"raw_start_text": "Романтическая мистика с будущим незнакомцем.", "mode": "gpt_actions"},
    )
    session_id = created.json()["session_id"]
    preview = client.post(
        f"/api/v1/sessions/{session_id}/bootstrap-preview",
        json={"bootstrap_json": bootstrap},
    )
    assert preview.status_code == 200, preview.text
    confirmed = client.post(
        f"/api/v1/sessions/{session_id}/bootstrap-confirm",
        json={"confirmation_text": "подтверждаю"},
    )
    assert confirmed.status_code == 200, confirmed.text
    return session_id


def _reveal_response(player_input: str) -> dict:
    response = _long_scene_response(player_input)
    response["proposed_updates"]["new_or_updated_characters"] = [
        {
            "id": "eiden_cross",
            "name": "Eiden Cross",
            "role": "future major stranger",
            "reveal_id": "reveal_eiden",
            "reason": "Эйден лично вошёл в кофейню и заговорил с героиней.",
            "source_in_scene": "Эйден остановился у стойки и представился.",
        }
    ]
    response["proposed_updates"]["director_bible_patches"] = {
        "reveal_updates": [
            {
                "id": "reveal_eiden",
                "status": "revealed",
                "reason": "Причинная личная встреча состоялась.",
                "source_in_scene": "Эйден остановился у стойки и представился.",
            }
        ]
    }
    response["proposed_updates"]["scene_state_patch"]["active_character_ids"] = ["pc_01", "eiden_cross"]
    response["witnesses"] = ["pc_01", "eiden_cross"]
    return response


def test_hidden_character_reveal_atomically_unlocks_card_future_lock_and_relationship():
    client = TestClient(app)
    session_id = _active_session_with_hidden_character(client)
    player_input = "Добрый вечер."
    turn_id = _pending_turn(client, session_id, player_input)

    applied = client.post(
        f"/api/v1/sessions/{session_id}/apply-turn-result",
        json={"turn_id": turn_id, "scene_response": _reveal_response(player_input)},
    )

    assert applied.status_code == 200, applied.text
    storage = SessionManager().storage
    card = storage.read_characters(session_id)["eiden_cross"]
    assert card["cast_status"] == "known_core"
    assert card["introduced"] is True
    assert card["known_to_player"] is True
    assert card["available_to_scene"] is True
    assert card["show_in_preview"] is True
    locks = storage.read_json(session_id, "future_locks.json")
    assert "eiden_cross" not in locks["hidden_character_ids"]
    assert "eiden_cross" in locks["revealed_character_ids"]
    assert "eiden_cross__pc_01" in storage.read_relationships(session_id)
    bible = storage.read_json(session_id, "director_bible.json")
    reveal = next(item for item in bible["planned_reveals"] if item["id"] == "reveal_eiden")
    assert reveal["status"] == "revealed"


def test_hidden_character_cannot_unlock_without_matching_director_reveal():
    client = TestClient(app)
    session_id = _active_session_with_hidden_character(client)
    player_input = "Добрый вечер."
    turn_id = _pending_turn(client, session_id, player_input)
    response = _reveal_response(player_input)
    response["proposed_updates"]["director_bible_patches"] = {}

    applied = client.post(
        f"/api/v1/sessions/{session_id}/apply-turn-result",
        json={"turn_id": turn_id, "scene_response": response},
    )

    assert applied.status_code == 422
    card = SessionManager().storage.read_characters(session_id)["eiden_cross"]
    assert card["available_to_scene"] is False
