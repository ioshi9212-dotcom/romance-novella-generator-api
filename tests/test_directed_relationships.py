from __future__ import annotations

from copy import deepcopy

from app.bootstrap_setup import build_setup_preview
from app.id_utils import pair_id
from app.npc_state_updates import apply_npc_state_patches, scene_response_for_base_updater
from app.relationship_bootstrap import prepare_directed_relationships
from app.relationship_state import build_starting_relationship, normalize_relationship_entry
from app.scene_contract_builder import build_scene_contract
from app.storage import JsonStorage


def _appearance() -> dict:
    return {
        "height": "средний рост",
        "build": "обычное телосложение",
        "hair": "тёмные волосы",
        "eyes": "карие глаза",
        "face": "живое лицо",
        "style": "повседневная одежда",
    }


def _character(character_id: str, role: str, display_name: str, cast_status: str) -> dict:
    player = cast_status == "player"
    return {
        "id": character_id,
        "name": {
            "pc_01": "Mara Ellison",
            "chloe_01": "Chloe Mercer",
            "ethan_01": "Ethan Ward",
            "hidden_01": "Adrian Vale",
        }[character_id],
        "display_name": display_name,
        "role": role,
        "age": 26,
        "cast_status": cast_status,
        "introduced": cast_status != "hidden_core",
        "known_to_player": cast_status in {"player", "known_core", "known_support"},
        "show_in_preview": cast_status in {"player", "known_core", "known_support"},
        "available_to_scene": cast_status != "hidden_core",
        "locked": True,
        "appearance": _appearance(),
        "personality": {
            "core": ["собранная" if player else "настойчивый"],
            "flaws": ["скрывает перегрузку" if player else "плохо принимает дистанцию"],
            "speech": "сухая речь" if player else "прямые вопросы",
        },
        "goal": "сохранить право решать самой" if player else "добиться ясности в отношениях",
        "past_short": "давно знакомы и накопили несовпадающие ожидания",
        "habits": ["проверяет телефон"],
        "inner_logic": {
            "core_need": "самостоятельность" if player else "быть важным для героини",
            "main_fear": "потерять контроль" if player else "снова остаться на расстоянии",
            "blind_spot": "считает молчание безопаснее разговора" if player else "считает настойчивость доказательством серьёзности",
            "contradiction": "хочет близости, но закрывается" if player else "хочет доверия, но давит",
        },
        "behavior": {
            "conflict_style": "замолкает и завершает разговор" if player else "возвращается к вопросу и требует ответа",
            "care_style": "решает проблемы делами" if player else "появляется рядом раньше, чем его позвали",
            "closeness_style": "сама выбирает дистанцию" if player else "считает давнюю связь правом быть ближе",
            "touch_style": "не инициирует касания без решения игрока" if player else "может взять за локоть по старой привычке",
            "stress_response": "становится резче" if player else "говорит громче и ревнует",
            "rejection_response": "уходит в молчание" if player else "останавливается, но холодеет и возвращается позже",
            "change_inertia": "медленно учится говорить прямо" if player else "понимает замечание, но под страхом повторяет давление",
            "inconvenient_pattern": "прячет проблему до последнего" if player else "удерживает контакт, когда героине нужна дистанция",
        },
        "speech_profile": {
            "baseline": "коротко и сухо" if player else "лично и настойчиво",
            "under_pressure": "обрывает фразы" if player else "говорит короче и громче",
            "verbal_habits": ["повторяет ключевое слово"],
            "avoids": ["называть собственный страх"],
        },
        "life_outside_player": {
            "current_obligation": "рабочая смена",
            "private_problem": "накопленная усталость",
            "person_or_place_that_matters": "собственная квартира",
        },
        "social_triggers": [
            {"behavior": "прямой ответ", "interpretation": "можно продолжать разговор", "usual_reaction": "становится открытее"},
            {"behavior": "уклонение", "interpretation": "от него скрывают правду", "usual_reaction": "давит сильнее"},
        ],
        "skills": [],
        "connections": [],
    }


def _characters() -> dict:
    return {
        "pc_01": _character("pc_01", "player_character", "Мара", "player"),
        "chloe_01": _character("chloe_01", "best friend", "Хлоя", "known_core"),
        "ethan_01": _character("ethan_01", "long-time romantic interest", "Итан", "known_core"),
        "hidden_01": _character("hidden_01", "future romantic lead", "Адриан", "hidden_core"),
    }


def _bundle() -> dict:
    characters = _characters()
    relationship_id = pair_id("pc_01", "ethan_01")
    return {
        "session": {"session_id": "directed_session", "status": "active", "title": "Тест"},
        "protagonist": {"id": "pc_01"},
        "characters": characters,
        "relationships": {
            relationship_id: build_starting_relationship(characters, "pc_01", "ethan_01"),
        },
        "knowledge": {character_id: {"character_id": character_id} for character_id in characters},
        "story_plan": {
            "genre": "romantic drama",
            "tone": "напряжённый",
            "setting_summary": "современный город",
            "main_premise": "старые отношения снова требуют ответа",
            "protagonist_start": "героиня избегает разговора",
            "player_goal": "самой определить границы",
            "central_conflict": "чужая настойчивость против её дистанции",
            "central_question": "что она выберет",
            "opening_scene_intent": "показать несовпадающие ожидания",
            "act_structure": [],
            "relationship_focus": [],
            "character_arcs": {},
            "open_threads": [],
            "forbidden_drift": [],
            "status_slots": [],
        },
        "current_state": {
            "turn_number": 0,
            "player_character_id": "pc_01",
            "active_character_ids": ["pc_01", "ethan_01"],
            "nearby_character_ids": [],
            "date": "День 1",
            "time": "20:00",
            "location": "кафе",
            "weather": "дождь",
            "scene_state": "разговор начался",
            "outfit": "рабочая одежда",
            "inventory": [],
            "nearby_items": [],
            "environment": {},
            "status": {},
        },
        "npc_state": {},
        "future_locks": {},
        "continuity": {},
        "scene_history": [],
        "turns": [],
    }


def _write_bundle(storage: JsonStorage, session_id: str, bundle: dict) -> dict:
    storage.ensure_session_dir(session_id)
    storage.write_json(session_id, "session.json", bundle["session"])
    storage.write_json(session_id, "user_request.json", {})
    storage.write_json(session_id, "protagonist.json", bundle["protagonist"])
    storage.write_json(session_id, "story_plan.json", bundle["story_plan"])
    storage.write_json(session_id, "current_state.json", bundle["current_state"])
    storage.write_json(session_id, "npc_state.json", bundle.get("npc_state", {}))
    storage.write_json(session_id, "future_locks.json", {})
    storage.write_json(session_id, "continuity.json", {})
    storage.write_json(session_id, "scene_history.json", [])
    storage.write_json(session_id, "turns.json", [])
    storage.write_json(session_id, "characters_index.json", {"ids": []})
    storage.write_json(session_id, "state/knowledge_index.json", {"ids": []})
    storage.write_json(session_id, "state/relationship_index.json", {"pair_ids": []})
    for character_id, card in bundle["characters"].items():
        storage.write_character(session_id, character_id, card)
    for relationship_id, relation in bundle["relationships"].items():
        storage.write_relationship_pair(session_id, relationship_id, relation)
    return storage.read_session_bundle(session_id)


def _base_result() -> dict:
    return {
        "status": "applied",
        "applied": {"relationships": []},
        "rejected": [],
        "next_builder_hints": {},
    }


def test_legacy_romantic_score_migrates_to_npc_side_without_forcing_player_feelings():
    characters = _characters()
    legacy = {
        "pair_id": pair_id("pc_01", "ethan_01"),
        "character_a": "pc_01",
        "character_b": "ethan_01",
        "type": "old_pair",
        "status": "он любит её несколько лет",
        "scores": {
            "trust": 45,
            "attachment": 70,
            "romantic_interest": 82,
            "tension": 40,
        },
        "a_view_of_b": {"summary": "она считает его давним знакомым"},
        "b_view_of_a": {"summary": "он давно влюблён"},
        "shared_history": ["знакомы несколько лет"],
        "recent_changes": [],
        "open_threads": ["он ждёт ответа"],
    }

    migrated = normalize_relationship_entry(legacy, characters, "pc_01")

    assert migrated["relationship_version"] == "directed.v1"
    assert migrated["b_to_a"]["scores"]["attraction"] == 82
    assert migrated["a_to_b"]["scores"]["attraction"] != 82
    assert migrated["a_to_b"]["scores"]["attraction"] <= 35
    assert migrated["scores"]["romantic_interest"] == 82
    assert migrated["shared"]["open_threads"] == ["он ждёт ответа"]


def test_starting_relationship_has_two_independent_directions():
    characters = _characters()
    relation = build_starting_relationship(characters, "pc_01", "ethan_01")

    assert relation["a_to_b"]["source_character_id"] == "pc_01"
    assert relation["b_to_a"]["source_character_id"] == "ethan_01"
    assert relation["a_to_b"]["scores"] != relation["b_to_a"]["scores"]
    assert relation["b_to_a"]["scores"]["attraction"] > relation["a_to_b"]["scores"]["attraction"]
    assert relation["shared"]["scores"]["tension"] >= 0


def test_prepare_and_preview_show_both_visible_sides_without_hidden_leak():
    characters = _characters()
    data = {
        "protagonist": characters["pc_01"],
        "characters": characters,
        "relationships": {},
        "knowledge": {},
        "story_plan": _bundle()["story_plan"],
        "current_state": _bundle()["current_state"],
        "npc_state": {},
        "future_locks": {},
        "continuity": {},
        "scene_history": [],
        "turns": [],
    }
    prepare_directed_relationships(data)
    preview = build_setup_preview(data)

    assert pair_id("pc_01", "chloe_01") in data["relationships"]
    assert "Мара → Хлоя" in preview
    assert "Хлоя → Мара" in preview
    assert "Мара → Итан" in preview
    assert "Итан → Мара" in preview
    assert "Адриан" not in preview
    assert "hidden_01" not in preview


def test_scene_contract_loads_directed_relationship_and_update_rules():
    contract = build_scene_contract(_bundle(), player_input="Я не обещала тебе взаимности.")
    loaded = contract["loaded_relationships"][0]["content"]

    assert loaded["relationship_version"] == "directed.v1"
    assert "shared" in loaded and "a_to_b" in loaded and "b_to_a" in loaded
    assert "independent_directions" in loaded["_scene_rules"]
    assert "player_side_agency" in loaded["_scene_rules"]


def test_legacy_patch_for_player_pair_changes_npc_side_only(tmp_path):
    storage = JsonStorage(tmp_path)
    session_id = "directed_session"
    source_bundle = _write_bundle(storage, session_id, _bundle())
    relationship_id = pair_id("pc_01", "ethan_01")
    before = deepcopy(source_bundle["relationships"][relationship_id])
    scene_response = {
        "player_input": "Я не хочу сейчас об этом говорить.",
        "witnesses": ["pc_01", "ethan_01"],
        "proposed_updates": {
            "relationship_patches": [{
                "pair_id": relationship_id,
                "change_type": "rejection",
                "entry": "Итан воспринял отказ как новую дистанцию",
                "reason": "его ожидание ясности снова не совпало с решением Мары",
                "source_in_scene": "Мара отказалась продолжать разговор",
                "resentment": 32,
                "jealousy": 40,
            }]
        },
    }

    result = apply_npc_state_patches(storage, session_id, scene_response, source_bundle, _base_result())
    saved = storage.read_relationships(session_id)[relationship_id]

    assert result["status"] == "applied"
    assert saved["a_to_b"]["scores"] == before["a_to_b"]["scores"]
    assert saved["b_to_a"]["scores"]["resentment"] > before["b_to_a"]["scores"]["resentment"]
    assert saved["b_to_a"]["scores"]["jealousy"] > before["b_to_a"]["scores"]["jealousy"]


def test_player_side_patch_without_exact_input_evidence_is_rejected(tmp_path):
    storage = JsonStorage(tmp_path)
    session_id = "directed_session"
    source_bundle = _write_bundle(storage, session_id, _bundle())
    relationship_id = pair_id("pc_01", "ethan_01")
    before = deepcopy(source_bundle["relationships"][relationship_id])
    scene_response = {
        "player_input": "Я просто устала.",
        "witnesses": ["pc_01", "ethan_01"],
        "proposed_updates": {
            "relationship_patches": [{
                "pair_id": relationship_id,
                "scope": "directed",
                "source_character_id": "pc_01",
                "target_character_id": "ethan_01",
                "change_type": "romance",
                "entry": "Мара якобы стала сильнее влюблена",
                "reason": "движок сделал вывод без выбора игрока",
                "source_in_scene": "Итан был рядом",
                "attraction": 70,
            }]
        },
    }

    result = apply_npc_state_patches(storage, session_id, scene_response, source_bundle, _base_result())
    saved = storage.read_relationships(session_id)[relationship_id]

    assert result["status"] == "partially_applied"
    assert any("player_input_evidence" in item["reason"] for item in result["rejected"])
    assert saved["a_to_b"]["scores"] == before["a_to_b"]["scores"]


def test_player_side_patch_with_exact_input_evidence_is_applied(tmp_path):
    storage = JsonStorage(tmp_path)
    session_id = "directed_session"
    source_bundle = _write_bundle(storage, session_id, _bundle())
    relationship_id = pair_id("pc_01", "ethan_01")
    before = deepcopy(source_bundle["relationships"][relationship_id])
    exact_input = "Я тебе доверяю, но не обещаю большего."
    scene_response = {
        "player_input": exact_input,
        "witnesses": ["pc_01", "ethan_01"],
        "proposed_updates": {
            "relationship_patches": [{
                "pair_id": relationship_id,
                "scope": "directed",
                "source_character_id": "pc_01",
                "target_character_id": "ethan_01",
                "player_input_evidence": exact_input,
                "change_type": "trust",
                "entry": "Мара прямо обозначила ограниченное доверие",
                "reason": "это точная реплика игрока, а не вывод движка",
                "source_in_scene": exact_input,
                "trust": before["a_to_b"]["scores"]["trust"] + 6,
            }]
        },
    }

    result = apply_npc_state_patches(storage, session_id, scene_response, source_bundle, _base_result())
    saved = storage.read_relationships(session_id)[relationship_id]

    assert result["status"] == "applied"
    assert saved["a_to_b"]["scores"]["trust"] == before["a_to_b"]["scores"]["trust"] + 6
    assert saved["b_to_a"]["scores"] == before["b_to_a"]["scores"]


def test_multiple_patches_for_same_direction_accumulate_in_one_turn(tmp_path):
    storage = JsonStorage(tmp_path)
    session_id = "directed_session"
    source_bundle = _write_bundle(storage, session_id, _bundle())
    relationship_id = pair_id("pc_01", "ethan_01")
    before = source_bundle["relationships"][relationship_id]["b_to_a"]["scores"]
    scene_response = {
        "player_input": "Оставь эту тему.",
        "witnesses": ["pc_01", "ethan_01"],
        "proposed_updates": {
            "relationship_patches": [
                {
                    "pair_id": relationship_id,
                    "scope": "directed",
                    "source_character_id": "ethan_01",
                    "target_character_id": "pc_01",
                    "change_type": "hurt",
                    "entry": "Итан обиделся",
                    "reason": "он услышал жёсткую границу",
                    "source_in_scene": "Мара велела оставить тему",
                    "resentment": before["resentment"] + 5,
                },
                {
                    "pair_id": relationship_id,
                    "scope": "directed",
                    "source_character_id": "ethan_01",
                    "target_character_id": "pc_01",
                    "change_type": "assumption",
                    "entry": "Итан решил, что она снова отдаляется",
                    "reason": "его старый страх усилил интерпретацию",
                    "source_in_scene": "Мара завершила разговор",
                    "current_assumption": "она снова собирается исчезнуть из его жизни",
                },
            ]
        },
    }

    result = apply_npc_state_patches(storage, session_id, scene_response, source_bundle, _base_result())
    saved = storage.read_relationships(session_id)[relationship_id]

    assert result["status"] == "applied"
    assert saved["b_to_a"]["scores"]["resentment"] == before["resentment"] + 5
    assert saved["b_to_a"]["current_assumption"] == "она снова собирается исчезнуть из его жизни"
    assert len(saved["b_to_a"]["history"]) >= 2


def test_base_updater_copy_removes_only_relationship_patches():
    scene_response = {
        "proposed_updates": {
            "relationship_patches": [{"pair_id": "a__b"}],
            "knowledge_patches": [{"character_id": "a"}],
            "npc_state_patches": [{"character_id": "b"}],
            "scene_state_patch": {"time": "21:00"},
        }
    }

    filtered = scene_response_for_base_updater(scene_response)

    assert filtered["proposed_updates"]["relationship_patches"] == []
    assert filtered["proposed_updates"]["knowledge_patches"] == [{"character_id": "a"}]
    assert filtered["proposed_updates"]["npc_state_patches"] == [{"character_id": "b"}]
    assert scene_response["proposed_updates"]["relationship_patches"] == [{"pair_id": "a__b"}]
