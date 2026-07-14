from __future__ import annotations

import json
from pathlib import Path

from app.npc_runtime import prepare_npc_runtime_map
from app.npc_state_updates import apply_npc_state_patches
from app.scene_contract_builder import build_scene_contract
from app.state_updater import StateUpdater
from app.storage import JsonStorage


ROOT_DIR = Path(__file__).resolve().parents[1]


def _card(character_id: str, *, hidden: bool = False) -> dict:
    return {
        "id": character_id,
        "name": "Chloe Mercer" if character_id == "chloe_01" else "Adrian Vale",
        "display_name": "Хлоя" if character_id == "chloe_01" else "Адриан",
        "role": "best friend" if character_id == "chloe_01" else "future romantic lead",
        "cast_status": "hidden_core" if hidden else "known_core",
        "introduced": not hidden,
        "known_to_player": not hidden,
        "available_to_scene": not hidden,
        "show_in_preview": not hidden,
        "goal": "добиться честного ответа и успеть на собственную смену",
        "inner_logic": {
            "main_fear": "оказаться последней, кто узнает о проблеме",
        },
        "behavior": {
            "conflict_style": "задаёт вопрос повторно и не отпускает тему",
            "inconvenient_pattern": "приезжает без предупреждения, если её продолжают избегать",
        },
        "life_outside_player": {
            "current_obligation": "закрыть собственную рабочую смену",
            "private_problem": "рискует потерять важный проект из-за постоянной усталости",
        },
    }


def _bundle() -> dict:
    return {
        "session": {"session_id": "session_npc", "status": "active"},
        "protagonist": {"id": "pc_01"},
        "characters": {
            "pc_01": {
                "id": "pc_01",
                "name": "Mara Ellison",
                "display_name": "Мара",
                "role": "player_character",
                "cast_status": "player",
                "introduced": True,
                "available_to_scene": True,
            },
            "chloe_01": _card("chloe_01"),
            "hidden_01": _card("hidden_01", hidden=True),
        },
        "relationships": {},
        "knowledge": {},
        "story_plan": {"status_slots": []},
        "current_state": {
            "turn_number": 0,
            "player_character_id": "pc_01",
            "active_character_ids": ["pc_01", "chloe_01"],
            "nearby_character_ids": [],
            "status": {},
        },
        "npc_state": {
            "chloe_01": {
                "character_id": "chloe_01",
                "current_mood": "раздражена, но пока шутит",
                "current_urge": "добиться прямого ответа",
                "change_stage": "defensive",
            },
            "hidden_01": {
                "character_id": "hidden_01",
                "current_mood": "занят собственным конфликтом",
            },
        },
        "future_locks": {},
        "continuity": {},
        "scene_history": [],
    }


def _write_session(storage: JsonStorage, session_id: str) -> dict:
    bundle = _bundle()
    storage.ensure_session_dir(session_id)
    storage.write_json(session_id, "session.json", bundle["session"])
    storage.write_json(session_id, "user_request.json", {})
    storage.write_json(session_id, "protagonist.json", bundle["protagonist"])
    storage.write_json(session_id, "story_plan.json", bundle["story_plan"])
    storage.write_json(session_id, "current_state.json", bundle["current_state"])
    storage.write_json(session_id, "npc_state.json", bundle["npc_state"])
    storage.write_json(session_id, "future_locks.json", {})
    storage.write_json(session_id, "continuity.json", {})
    storage.write_json(session_id, "scene_history.json", [])
    storage.write_json(session_id, "turns.json", [])
    storage.write_json(session_id, "characters_index.json", {"ids": []})
    storage.write_json(session_id, "state/knowledge_index.json", {"ids": []})
    storage.write_json(session_id, "state/relationship_index.json", {"pair_ids": []})
    for character_id, card in bundle["characters"].items():
        storage.write_character(session_id, character_id, card)
    return storage.read_session_bundle(session_id)


def test_bootstrap_runtime_is_completed_and_preserves_written_state():
    data = _bundle()
    data["npc_state"] = {"chloe_01": {"current_mood": "злится после сорванной встречи"}}

    prepare_npc_runtime_map(data)
    state = data["npc_state"]["chloe_01"]

    assert state["current_mood"] == "злится после сорванной встречи"
    assert state["current_goal"]
    assert state["current_pressure"]
    assert state["current_urge"]
    assert state["behavior_mode"]
    assert state["unresolved_emotion"]
    assert state["next_self_action_if_ignored"]
    assert state["change_stage"] == "baseline"


def test_scene_contract_loads_only_focused_available_npc_runtime():
    contract = build_scene_contract(_bundle(), player_input="Я в порядке.")
    runtime = contract["npc_runtime"]

    assert set(runtime["characters"]) == {"chloe_01"}
    assert runtime["characters"]["chloe_01"]["current_mood"] == "раздражена, но пока шутит"
    assert "hidden_01" not in runtime["characters"]
    assert "awareness_is_not_change" in runtime["rules"]
    assert "relapse_under_stress" in runtime["rules"]


def test_npc_runtime_patch_survives_into_next_scene_contract(tmp_path):
    storage = JsonStorage(tmp_path)
    session_id = "session_npc"
    source_bundle = _write_session(storage, session_id)
    scene_response = {
        "player_input": "Я в порядке.",
        "summary": "Хлоя заметила уклончивый ответ и не поверила ему.",
        "important_facts": ["Хлоя решила вернуться к разговору позже"],
        "witnesses": ["pc_01", "chloe_01"],
        "scene": {"body": "Хлоя не приняла ответ и закончила разговор раздражённой."},
        "proposed_updates": {
            "scene_state_patch": {"active_character_ids": ["pc_01"]},
            "continuity_patch": {},
            "relationship_patches": [],
            "knowledge_patches": [],
            "new_or_updated_characters": [],
            "npc_state_patches": [
                {
                    "character_id": "chloe_01",
                    "current_mood": "обижена и заметно злее",
                    "current_urge": "проверить слова Мары действиями",
                    "behavior_mode": "pursuit",
                    "last_trigger": "Мара снова улыбнулась вместо прямого ответа",
                    "unresolved_emotion": "обида, что ей не доверяют",
                    "next_self_action_if_ignored": "приехать к Маре после смены без предупреждения",
                    "change_stage": "relapsed",
                    "reason": "уклончивый ответ усилил старый контролирующий паттерн",
                    "source_in_scene": "Мара сказала, что всё в порядке, не глядя Хлое в глаза",
                }
            ],
        },
    }

    base_result = StateUpdater(storage).apply_scene_response(session_id, scene_response)
    result = apply_npc_state_patches(storage, session_id, scene_response, source_bundle, base_result)

    assert result["status"] == "applied"
    assert result["applied"]["npc_state"][0]["character_id"] == "chloe_01"
    saved = storage.read_json(session_id, "npc_state.json")
    assert saved["chloe_01"]["current_mood"] == "обижена и заметно злее"
    assert saved["chloe_01"]["change_stage"] == "relapsed"
    assert saved["chloe_01"]["last_updated_turn"] == 1
    assert saved["chloe_01"]["history"][-1]["reason"]

    next_bundle = storage.read_session_bundle(session_id)
    next_bundle["current_state"]["active_character_ids"] = ["pc_01", "chloe_01"]
    next_contract = build_scene_contract(next_bundle)
    assert next_contract["npc_runtime"]["characters"]["chloe_01"]["current_urge"] == "проверить слова Мары действиями"
    assert next_contract["npc_runtime"]["characters"]["chloe_01"]["unresolved_emotion"] == "обида, что ей не доверяют"


def test_npc_patch_cannot_update_hidden_or_absent_character(tmp_path):
    storage = JsonStorage(tmp_path)
    session_id = "session_npc"
    source_bundle = _write_session(storage, session_id)
    scene_response = {
        "proposed_updates": {
            "npc_state_patches": [
                {
                    "character_id": "hidden_01",
                    "current_mood": "теперь знает о сцене",
                    "reason": "недопустимое скрытое обновление",
                    "source_in_scene": "персонаж отсутствовал",
                }
            ]
        }
    }
    base_result = {"status": "applied", "applied": {}, "rejected": [], "next_builder_hints": {}}

    result = apply_npc_state_patches(storage, session_id, scene_response, source_bundle, base_result)

    assert result["status"] == "partially_applied"
    assert result["next_builder_hints"]["repair_required"] is True
    assert any("hidden or unavailable" in item["reason"] for item in result["rejected"])


def test_scene_response_schema_exposes_strict_npc_state_patches():
    schema = json.loads((ROOT_DIR / "schemas" / "scene_response.schema.json").read_text(encoding="utf-8"))
    patch_schema = schema["properties"]["proposed_updates"]["properties"]["npc_state_patches"]["items"]

    assert patch_schema["additionalProperties"] is False
    assert set(patch_schema["required"]) == {"character_id", "reason", "source_in_scene"}
    assert "relapsed" in patch_schema["properties"]["change_stage"]["enum"]
    assert "admitted_not_changed" in patch_schema["properties"]["change_stage"]["enum"]
