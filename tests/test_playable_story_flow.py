from __future__ import annotations

from copy import deepcopy

from fastapi.testclient import TestClient

from app.character_profiles import enrich_character_card
from app.id_utils import pair_id
from app.main import app
from app.session_manager import SessionManager
from app.validators import validate_scene_state_invariants
from tests.test_smoke import _long_scene_response, _valid_bootstrap
from tests.test_story_launch_flow import _collect_turn_prompt


RAW_EMILY_REQUEST = """Героиня — Эмили Харпер, 21 год. Невысокая, стройная, с длинными каштановыми волосами, зелёными глазами и веснушками. Она упрямая, наблюдательная, прячет тревогу за сухим юмором. Райан — её старший брат, Хлоя — лучшая подруга, Итан — коллега. Жанр: взрослая романтическая мистика, медленное сближение, современный дождливый город. Остальное придумай сам."""


def _known_card(template: dict, character_id: str, name: str, role: str, marker: str) -> dict:
    card = deepcopy(template)
    card.update(
        {
            "id": character_id,
            "name": name,
            "display_name": name,
            "role": role,
            "cast_status": "known_core" if role in {"older brother", "best friend"} else "known_support",
            "goal": f"вести собственную жизнь и добиться своей цели: {marker}",
            "past_short": f"У {name} есть отдельная история с Эмили и незавершённое дело: {marker}.",
            "habits": [f"замечает {marker}", "не отвечает сразу", "меняет тему при давлении"],
            "connections": [
                {
                    "character_id": "pc_01",
                    "relation": role,
                    "summary": f"Знаком с Эмили до начала истории; {marker}.",
                }
            ],
        }
    )
    card["personality"] = {
        "core": [f"самостоятельный и {marker}", "не сводит жизнь к героине"],
        "flaws": [f"слишком часто действует через {marker}"],
        "speech": f"узнаваемая манера речи: {marker}",
    }
    return card


def _emily_bootstrap() -> dict:
    bootstrap = _valid_bootstrap()
    player = bootstrap["characters"]["pc_01"]
    player.update(
        {
            "name": "Emily Harper",
            "display_name": "Эмили Харпер",
            "age": 21,
            "appearance": {
                "height": "невысокая",
                "build": "стройная",
                "hair": "длинные каштановые волосы",
                "eyes": "зелёные",
                "face": "веснушки и мягкие черты",
                "style": "удобная городская одежда",
            },
            "personality": {
                "core": ["упрямая", "наблюдательная", "прячет тревогу за сухим юмором"],
                "flaws": ["отталкивает помощь", "слишком долго терпит"],
                "speech": "коротко, точно, с сухой иронией",
            },
            "past_short": "Эмили недавно начала самостоятельную жизнь в дождливом городе и не любит просить о помощи.",
            "goal": "сохранить самостоятельность и понять странные события, не отдавая другим право решать за неё",
        }
    )
    bootstrap["protagonist"] = {"id": "pc_01", "name": "Emily Harper", "role": "player_character"}

    template = bootstrap["characters"].pop("coworker_01")
    bootstrap["characters"]["ryan_01"] = _known_card(
        template, "ryan_01", "Ryan Harper", "older brother", "защитная прямота"
    )
    bootstrap["characters"]["chloe_01"] = _known_card(
        template, "chloe_01", "Chloe Bennett", "best friend", "неудобная честность"
    )
    bootstrap["characters"]["ethan_01"] = _known_card(
        template, "ethan_01", "Ethan Cole", "coworker", "спокойное соперничество"
    )
    bootstrap["relationships"] = {}
    bootstrap["knowledge"] = {"pc_01": bootstrap["knowledge"]["pc_01"]}
    bootstrap["current_state"].update(
        {
            "nearby_character_ids": ["ethan_01"],
            "player_character_id": "pc_01",
            "outfit": "тёмные джинсы, мягкий свитер и непромокаемые ботинки",
        }
    )
    bootstrap["story_plan"].update(
        {
            "genre": "взрослая романтическая мистика",
            "tone": "медленное сближение, напряжение и сухой юмор",
            "setting_summary": "Современный дождливый город, где эмоции иногда оставляют физические следы.",
        }
    )
    bootstrap["future_locks"] = {
        "hidden_character_seeds": [
            {
                "id": "future_stranger_seed",
                "role": "возможный будущий романтический интерес",
                "story_function": "осложнить выбор Эмили собственной целью, не спасать её",
                "entry_condition": "после первой сцены, если последствия выводят историю за пределы офиса",
                "earliest_turn": 2,
                "priority": 100,
                "notes_for_engine": "создать только при личном причинном входе",
            },
            {
                "id": "later_rival_seed",
                "role": "поздний соперник",
                "story_function": "усилить внешний конфликт во втором акте",
                "entry_condition": "после укрепления центральной связи",
                "earliest_turn": 6,
                "priority": 70,
            },
        ],
        "do_not_reveal_yet": ["Не объяснять источник мистики в первых сценах."],
    }
    bootstrap["scene_history"] = []
    bootstrap["turns"] = []
    return bootstrap


def _future_npc() -> dict:
    raw = deepcopy(_valid_bootstrap()["characters"]["coworker_01"])
    raw.update(
        {
            "id": "noah_reed",
            "name": "Noah Reed",
            "display_name": "Ноа Рид",
            "role": "future romantic interest with an independent investigation",
            "cast_status": "known_core",
            "goal": "найти источник городских сбоев раньше, чем он навредит его собственной семье",
            "past_short": "Ноа несколько месяцев отслеживал похожие сбои и пришёл сюда по собственной зацепке.",
            "connections": [{"character_id": "pc_01", "relation": "first causal encounter"}],
        }
    )
    card = enrich_character_card(raw, "noah_reed")
    card["source_seed_id"] = "future_stranger_seed"
    return card


def test_future_seed_cannot_be_consumed_before_the_character_appears():
    bootstrap = _valid_bootstrap()
    bootstrap["future_locks"]["hidden_character_seeds"] = [
        {"id": "future_stranger_seed", "role": "future significant stranger"}
    ]
    response = _long_scene_response("(не вводить нового персонажа)")
    response["proposed_updates"]["new_or_updated_characters"] = [_future_npc()]

    errors = validate_scene_state_invariants(response, bootstrap)

    assert any("actually appears" in error and "future_stranger_seed" in error for error in errors)


def test_questionnaire_preview_two_turns_and_seed_character_are_persisted_atomically():
    client = TestClient(app)
    created = client.post(
        "/api/v1/sessions",
        json={"raw_start_text": RAW_EMILY_REQUEST, "mode": "gpt_actions"},
    )
    assert created.status_code == 200, created.text
    session_id = created.json()["session_id"]
    storage = SessionManager().storage
    assert storage.read_json(session_id, "user_request.json")["raw_start_text"] == RAW_EMILY_REQUEST

    preview_response = client.post(
        f"/api/v1/sessions/{session_id}/bootstrap-preview",
        json={"bootstrap_json": _emily_bootstrap()},
    )
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()["message_to_user"]
    for visible_name in ("Эмили Харпер", "Ryan Harper", "Chloe Bennett", "Ethan Cole"):
        assert visible_name in preview
    for hidden_or_internal in (
        "future_stranger_seed",
        "later_rival_seed",
        "inner_logic",
        '"trust"',
        '"attachment"',
    ):
        assert hidden_or_internal not in preview
    assert len(preview) < 6000

    confirmed = client.post(
        f"/api/v1/sessions/{session_id}/bootstrap-confirm",
        json={"confirmation_text": "подтверждаю"},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert "future_stranger_seed" not in storage.read_characters(session_id)

    first_input = "(начать первую сцену)"
    first_turn = client.post(
        f"/api/v1/sessions/{session_id}/turn",
        json={"player_input": first_input, "mode": "gpt_actions"},
    )
    assert first_turn.status_code == 200, first_turn.text
    first_prompt = _collect_turn_prompt(client, session_id, first_turn.json())
    assert '"character_creation_request":null' in first_prompt
    assert "future_stranger_seed" not in first_prompt

    first_scene = _long_scene_response(first_input)
    first_scene["witnesses"] = ["pc_01", "ethan_01"]
    first_scene["proposed_updates"]["scene_state_patch"]["active_character_ids"] = ["pc_01", "ethan_01"]
    first_scene["proposed_updates"]["relationship_patches"] = []
    first_scene["proposed_updates"]["knowledge_patches"] = []
    first_applied = client.post(
        f"/api/v1/sessions/{session_id}/apply-turn-result",
        json={"turn_id": first_turn.json()["turn_id"], "scene_response": first_scene},
    )
    assert first_applied.status_code == 200, first_applied.text
    assert first_applied.json()["saved_turn_number"] == 1

    second_input = "(выйти в коридор и проверить источник помех)"
    second_turn = client.post(
        f"/api/v1/sessions/{session_id}/turn",
        json={"player_input": second_input, "mode": "gpt_actions"},
    )
    assert second_turn.status_code == 200, second_turn.text
    second_prompt = _collect_turn_prompt(client, session_id, second_turn.json())
    assert "future_stranger_seed" in second_prompt
    assert "source_seed_id" in second_prompt
    assert "later_rival_seed" not in second_prompt

    second_scene = _long_scene_response(second_input)
    second_scene["witnesses"] = ["pc_01", "ethan_01", "noah_reed"]
    updates = second_scene["proposed_updates"]
    updates["scene_state_patch"]["active_character_ids"] = ["pc_01", "ethan_01", "noah_reed"]
    updates["relationship_patches"] = []
    updates["knowledge_patches"] = [
        {
            "character_id": "noah_reed",
            "reason": "Ноа лично увидел помеху и услышал вопрос Эмили.",
            "source_in_scene": "Ноа вошёл в коридор во время сбоя и представился.",
            "add_knows": ["Эмили тоже видит физические следы сбоя"],
        }
    ]
    updates["new_or_updated_characters"] = [_future_npc()]

    second_applied = client.post(
        f"/api/v1/sessions/{session_id}/apply-turn-result",
        json={"turn_id": second_turn.json()["turn_id"], "scene_response": second_scene},
    )
    assert second_applied.status_code == 200, second_applied.text
    second_body = second_applied.json()
    assert second_body["saved_turn_number"] == 2

    characters = storage.read_characters(session_id)
    assert characters["noah_reed"]["locked"] is True
    assert storage.read_knowledge(session_id)["noah_reed"]["known_facts"]
    assert storage.read_json(session_id, "npc_state.json")["noah_reed"]
    assert pair_id("pc_01", "noah_reed") in storage.read_relationships(session_id)
    locks = storage.read_json(session_id, "future_locks.json")
    assert [seed["id"] for seed in locks["hidden_character_seeds"]] == ["later_rival_seed"]
    assert locks["used_character_seeds"][-1] == {
        "seed_id": "future_stranger_seed",
        "character_id": "noah_reed",
        "introduced_turn": 2,
    }
    assert storage.read_json(session_id, "current_state.json")["turn_number"] == 2

    recovered = client.get(f"/api/v1/sessions/{session_id}/last-scene")
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["message_to_user"] == second_body["message_to_user"]

    replayed = client.post(
        f"/api/v1/sessions/{session_id}/apply-turn-result",
        json={"turn_id": second_turn.json()["turn_id"], "scene_response": second_scene},
    )
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["replayed"] is True
    assert replayed.json()["message_to_user"] == second_body["message_to_user"]
    assert storage.read_json(session_id, "current_state.json")["turn_number"] == 2
