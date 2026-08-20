from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from app.directional_relationships import (
    append_directional_preview,
    apply_directional_relationship_patches,
    prepare_directional_relationships,
    validate_directional_relationships,
)
from app.id_utils import pair_id
from app.relationship_state import apply_relationship_patch, normalize_relationship_pair
from app.scene_contract_builder import build_scene_contract
from app.storage import JsonStorage


def _card(character_id: str, name: str, role: str, cast_status: str) -> dict:
    return {
        "id": character_id,
        "name": name,
        "display_name": name.split()[0],
        "role": role,
        "cast_status": cast_status,
        "introduced": cast_status != "hidden_core",
        "known_to_player": cast_status in {"player", "known_core", "known_support"},
        "available_to_scene": cast_status != "hidden_core",
        "behavior": {
            "closeness_style": "считает давнюю близость правом задавать второй вопрос",
            "touch_style": "может коснуться плеча без отдельного разрешения, если раньше это было привычно",
            "inconvenient_pattern": "пытаясь помочь, начинает контролировать и проверять",
        },
        "inner_logic": {
            "core_need": "оставаться важной частью жизни близкого человека",
            "main_fear": "оказаться лишней",
            "blind_spot": "считает молчание доказательством, что нужно давить сильнее",
            "contradiction": "хочет поддержать, но превращает заботу в контроль",
        },
    }


def _bootstrap() -> dict:
    pc = _card("pc_01", "Mara Ellison", "player_character", "player")
    chloe = _card("chloe_01", "Chloe Mercer", "best friend", "known_core")
    hidden = _card("hidden_01", "Adrian Vale", "future romantic lead", "hidden_core")
    return {
        "protagonist": pc,
        "characters": {"pc_01": pc, "chloe_01": chloe, "hidden_01": hidden},
        "relationships": {
            pair_id("pc_01", "chloe_01"): {
                "pair_id": pair_id("pc_01", "chloe_01"),
                "character_a": "pc_01",
                "character_b": "chloe_01",
                "type": "friendship",
                "status": "давняя дружба с накопившимися ожиданиями",
                "scores": {"trust": 60, "attachment": 60, "tension": 30},
                "a_view_of_b": {"summary": "Мара считает Хлою навязчивой", "current_assumption": "Хлоя снова полезет спасать"},
                "b_view_of_a": {"summary": "Хлоя видит ложное спокойствие Мары", "current_assumption": "Мара скрывает проблему"},
                "shared_history": ["дружат со школы"],
                "recent_changes": [],
                "open_threads": ["Хлоя не верит последнему объяснению"],
            },
            pair_id("pc_01", "hidden_01"): {
                "pair_id": pair_id("pc_01", "hidden_01"),
                "character_a": "pc_01",
                "character_b": "hidden_01",
                "type": "future",
                "status": "ещё не знакомы",
            },
        },
        "current_state": {
            "player_character_id": "pc_01",
            "active_character_ids": ["pc_01", "chloe_01"],
            "nearby_character_ids": [],
            "turn_number": 0,
            "date": "День 1",
            "time": "19:00",
            "location": "кафе",
            "weather": "дождь",
            "scene_state": "Хлоя закрыла дверь после смены",
            "outfit": "рабочая одежда",
            "inventory": [],
            "nearby_items": [],
            "status": {"hunger": "50/100", "fatigue": "70/100", "injuries": [], "emotional_state": "напряжена", "skills": [], "custom": []},
        },
        "knowledge": {},
        "story_plan": {"status_slots": []},
        "npc_state": {},
        "future_locks": {"do_not_reveal_yet": [], "hidden_character_seeds": []},
        "continuity": {},
        "scene_history": [],
        "session": {"session_id": "session_test", "title": "Test"},
    }


def test_legacy_pair_becomes_asymmetric_directional_state():
    data = _bootstrap()
    prepare_directional_relationships(data)
    rel = data["relationships"][pair_id("pc_01", "chloe_01")]

    assert rel["shared"]["shared_history"] == ["дружат со школы"]
    assert rel["a_to_b"]["current_view"] == "Мара считает Хлою навязчивой"
    assert rel["b_to_a"]["current_view"] == "Хлоя видит ложное спокойствие Мары"
    assert rel["a_to_b"]["scores"] != rel["b_to_a"]["scores"]
    assert rel["a_to_b"]["unresolved_grievances"]
    assert rel["b_to_a"]["wrong_beliefs"]
    assert validate_directional_relationships(data) == []


def test_user_written_direction_values_are_preserved():
    data = _bootstrap()
    pid = pair_id("pc_01", "chloe_01")
    data["relationships"][pid]["b_to_a"] = {
        "scores": {"trust": 73, "attachment": 91, "jealousy": 22},
        "current_need": "добиться честного ответа сегодня",
        "access_boundary": "считает нормальным приехать без предупреждения",
        "unresolved_grievances": ["Мара снова исключила её из важного разговора"],
        "wrong_beliefs": ["проблема наверняка связана только с работой"],
    }
    prepare_directional_relationships(data)
    direction = data["relationships"][pid]["b_to_a"]

    assert direction["scores"]["attachment"] == 91
    assert direction["current_need"] == "добиться честного ответа сегодня"
    assert direction["access_boundary"] == "считает нормальным приехать без предупреждения"
    assert direction["wrong_beliefs"] == ["проблема наверняка связана только с работой"]


def test_patch_changes_only_named_direction_and_bounds_score():
    data = _bootstrap()
    prepare_directional_relationships(data)
    pid = pair_id("pc_01", "chloe_01")
    rel = data["relationships"][pid]
    pc_before = deepcopy(rel["a_to_b"])
    chloe_trust_before = rel["b_to_a"]["scores"]["trust"]

    updated, error = apply_relationship_patch(
        rel,
        {
            "pair_id": pid,
            "from_character_id": "chloe_01",
            "to_character_id": "pc_01",
            "direction_patch": {
                "trust": 100,
                "current_need": "не отпускать тему до прямого ответа",
                "add_unresolved_grievances": ["Мара снова улыбнулась вместо ответа"],
                "add_wrong_beliefs": ["молчание означает немедленную опасность"],
            },
            "shared_patch": {"add_unresolved_threads": ["Хлоя собирается приехать без предупреждения"]},
            "change_type": "pressure_increased",
            "entry": "Хлоя не приняла уклончивый ответ",
            "reason": "старый контролирующий паттерн усилился",
            "source_in_scene": "Мара не ответила на повторный вопрос",
        },
        turn_number=3,
    )

    assert error is None
    assert updated["a_to_b"] == pc_before
    assert updated["b_to_a"]["scores"]["trust"] == min(100, chloe_trust_before + 8)
    assert updated["b_to_a"]["current_need"] == "не отпускать тему до прямого ответа"
    assert "Хлоя собирается приехать без предупреждения" in updated["shared"]["unresolved_threads"]


def test_direction_patch_rejects_participants_outside_pair():
    data = _bootstrap()
    prepare_directional_relationships(data)
    rel = data["relationships"][pair_id("pc_01", "chloe_01")]
    unchanged, error = apply_relationship_patch(
        rel,
        {
            "from_character_id": "hidden_01",
            "to_character_id": "pc_01",
            "direction_patch": {"current_need": "вмешаться"},
        },
        turn_number=1,
    )
    assert error
    assert unchanged == rel


def test_scene_contract_loads_directions_without_hidden_pair():
    data = _bootstrap()
    prepare_directional_relationships(data)
    contract = build_scene_contract(data, player_input="(молча посмотреть на Хлою)")

    loaded = {item["pair_id"]: item for item in contract["loaded_relationships"]}
    visible_pid = pair_id("pc_01", "chloe_01")
    hidden_pid = pair_id("pc_01", "hidden_01")
    assert visible_pid in loaded
    assert hidden_pid not in loaded
    assert loaded[visible_pid]["content"]["a_to_b"]
    assert loaded[visible_pid]["content"]["b_to_a"]
    assert "never mirror" in contract["output_requirements"]["directional_relationship_rule"]


def test_preview_shows_known_directions_and_hides_future_character():
    data = _bootstrap()
    preview = append_directional_preview("## Черновик", data)
    assert "Chloe" in preview
    assert "Adrian" not in preview
    assert "ошибочное убеждение" in preview
    assert "как может сделать хуже" in preview


def test_directional_patch_is_persisted_in_pair_file(tmp_path):
    storage = JsonStorage(tmp_path)
    session_id = "session_directional"
    storage.ensure_session_dir(session_id)
    storage.write_json(session_id, "current_state.json", {"turn_number": 4})

    data = _bootstrap()
    prepare_directional_relationships(data)
    pid = pair_id("pc_01", "chloe_01")
    storage.write_relationship_pair(session_id, pid, data["relationships"][pid])

    result = {
        "status": "applied",
        "applied": {"relationships": []},
        "rejected": [],
        "next_builder_hints": {"repair_required": False},
    }
    scene_response = {
        "proposed_updates": {
            "relationship_patches": [
                {
                    "pair_id": pid,
                    "from_character_id": "chloe_01",
                    "to_character_id": "pc_01",
                    "direction_patch": {
                        "current_view": "Мара снова закрылась именно после прямого вопроса",
                        "unresolved_emotion": "обида и тревога",
                    },
                    "change_type": "view_changed",
                    "entry": "Хлоя сделала новый вывод",
                    "reason": "увидела несовпадение улыбки и взгляда",
                    "source_in_scene": "Мара улыбнулась, но глаза остались пустыми",
                }
            ]
        }
    }

    applied = apply_directional_relationship_patches(storage, session_id, scene_response, data, result)
    saved = storage.read_relationships(session_id)[pid]
    assert applied["status"] == "applied"
    assert saved["b_to_a"]["current_view"] == "Мара снова закрылась именно после прямого вопроса"
    assert saved["a_to_b"]["current_view"] != saved["b_to_a"]["current_view"]
    assert any(item.get("operation") == "patch_directional_pair" for item in applied["applied"]["relationships"])


def test_action_schemas_expose_directional_relationship_fields():
    root = Path(__file__).resolve().parent.parent
    bootstrap = json.loads((root / "schemas" / "bootstrap_output.schema.json").read_text(encoding="utf-8"))
    relationship_props = bootstrap["properties"]["relationships"]["additionalProperties"]["properties"]
    assert {"shared", "a_to_b", "b_to_a"} <= set(relationship_props)

    scene = json.loads((root / "schemas" / "scene_response.schema.json").read_text(encoding="utf-8"))
    patch_props = scene["properties"]["proposed_updates"]["properties"]["relationship_patches"]["items"]["properties"]
    assert {"from_character_id", "to_character_id", "direction_patch", "shared_patch"} <= set(patch_props)
