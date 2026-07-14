from __future__ import annotations

import json
from pathlib import Path

from app.bootstrap_normalizer import normalize_bootstrap_json
from app.bootstrap_setup import build_setup_preview
from app.character_profiles import prepare_bootstrap_cast
from app.director_bible import (
    apply_director_bible_patches,
    build_director_guidance,
    prepare_director_bible,
    validate_director_bible,
)
from app.models import CreateSessionRequest
from app.scene_contract_builder import build_scene_contract
from app.session_manager import SessionManager
from app.storage import JsonStorage


def _raw_bootstrap() -> dict:
    return {
        "protagonist": {"id": "pc_01", "name": "Mira Vale", "role": "player_character"},
        "characters": {
            "pc_01": {
                "id": "pc_01",
                "name": "Mira Vale",
                "role": "player_character",
                "goal": "пережить смену и не позволить другим решить за неё",
                "past_short": "она давно привыкла прятать усталость за сухими ответами",
                "introduced": True,
                "known_to_player": True,
            },
            "friend_01": {
                "id": "friend_01",
                "name": "Chloe Arden",
                "role": "old friend",
                "goal": "понять, почему Мира снова исчезает после работы",
                "past_short": "они знакомы со школы и давно спорят о праве вмешиваться",
                "introduced": True,
                "known_to_player": True,
            },
            "hidden_01": {
                "id": "hidden_01",
                "name": "Ren Kurose",
                "role": "future core character",
                "goal": "найти источник искажений раньше, чем это сделает его семья",
                "past_short": "он связан с причиной сбоев, но Мира ещё не знает о его существовании",
                "introduced": False,
                "known_to_player": False,
                "cast_status": "hidden_core",
            },
        },
        "relationships": {},
        "knowledge": {},
        "story_plan": {
            "genre": "romantic mysticism",
            "language": "ru",
            "tone": "adult, tense",
            "setting_summary": "ночной город и офис после закрытия",
            "main_premise": "эмоциональное напряжение вызывает физические искажения",
            "protagonist_start": "Мира задерживается после смены",
            "player_goal": "сохранить контроль и понять происходящее",
            "central_conflict": "чужая забота становится давлением, пока скрытая причина приближается",
            "central_question": "кому Мира позволит приблизиться",
            "opening_scene_intent": "показать усталость, знакомую подругу и первый слабый сбой",
            "act_structure": [{"act": 1, "goal": "первое давление", "must_happen": ["сбой"], "must_not_resolve_yet": ["источник"]}],
            "character_arcs": {},
            "relationship_focus": [],
            "open_threads": ["почему свет реагирует на Миру", "почему Хлоя приезжает без предупреждения"],
            "forbidden_drift": ["не раскрывать источник в начале"],
            "current_story_position": "act_1_start",
            "status_slots": [
                {"id": "story_slot_1", "label": "Давление", "description": "социальное давление", "initial_value": "низкое"},
                {"id": "story_slot_2", "label": "Искажение", "description": "видимость мистики", "initial_value": "слабое"},
            ],
        },
        "current_state": {
            "turn_number": 0,
            "date": "День 1",
            "time": "22:40",
            "location": "закрытый офис",
            "weather": "дождь",
            "scene_state": "смена закончилась",
            "player_character_id": "pc_01",
            "active_character_ids": ["pc_01"],
            "nearby_character_ids": ["friend_01"],
            "scene_goal": "дать первый meaningful beat",
            "last_player_input": "",
            "outfit": "джинсы и свитер",
            "inventory": ["телефон", "ключи"],
            "nearby_items": ["лампа"],
            "environment": {"light": "тусклый", "sound": "дождь", "air": "прохладный", "details": []},
            "status": {
                "hunger": "средний",
                "fatigue": "высокая",
                "injuries": [],
                "emotional_state": "раздражена",
                "skills": ["наблюдательность"],
                "custom": [
                    {"id": "story_slot_1", "label": "Давление", "value": "низкое"},
                    {"id": "story_slot_2", "label": "Искажение", "value": "слабое"},
                ],
            },
        },
        "npc_state": {},
        "future_locks": {
            "hidden_character_seeds": [],
            "hidden_character_ids": ["hidden_01"],
            "do_not_reveal_yet": ["Ren связан с источником искажений"],
        },
        "continuity": {},
        "scene_history": [],
        "turns": [],
    }


def _prepared_bootstrap() -> dict:
    data = normalize_bootstrap_json(_raw_bootstrap())
    prepare_bootstrap_cast(data)
    prepare_director_bible(data)
    return data


def test_director_bible_is_autofilled_and_hidden_from_preview():
    data = _prepared_bootstrap()
    bible = data["director_bible"]

    assert bible["world_truth"]["core_truth"]
    assert len(bible["hidden_lore"]) >= 1
    assert len(bible["story_hooks"]) >= 1
    assert len(bible["event_queue"]) >= 3
    assert "friend_01" in bible["character_functions"]
    assert "hidden_01" in bible["character_functions"]
    assert validate_director_bible(data) == []

    preview = build_setup_preview(data)
    assert "Ren Kurose" not in preview
    assert "источником искажений" not in preview
    assert "director_bible" not in preview
    assert "event_01" not in preview


def test_scene_contract_gets_author_only_guidance_but_not_hidden_character_card():
    data = _prepared_bootstrap()
    contract = build_scene_contract(data, player_input="(посмотреть на лампу)")
    guidance = contract["director_guidance"]

    assert guidance["visibility"] == "author_only_never_render_or_quote"
    assert guidance["due_or_next_events"]
    assert guidance["hidden_lore"]
    assert all(item["character_id"] != "hidden_01" for item in contract["loaded_characters"])
    assert guidance["rules"]["queue_is_not_railroad"]


def test_director_event_patch_persists_without_rewriting_world_truth(tmp_path: Path):
    storage = JsonStorage(tmp_path)
    session_id = "session_director"
    data = _prepared_bootstrap()
    storage.ensure_session_dir(session_id)
    storage.write_json(session_id, "director_bible.json", data["director_bible"])
    storage.write_json(session_id, "current_state.json", {**data["current_state"], "turn_number": 2})

    original_truth = data["director_bible"]["world_truth"]
    scene_response = {
        "proposed_updates": {
            "director_bible_patches": {
                "event_updates": [
                    {
                        "id": "event_01",
                        "status": "triggered",
                        "reason": "Хлоя приехала и начала действовать сама",
                        "source_in_scene": "она появилась у служебного входа без предупреждения",
                    }
                ],
                "add_future_consequences": ["Хлоя теперь видела след искажений лично"],
            }
        }
    }
    result = {"status": "applied", "applied": {}, "rejected": [], "next_builder_hints": {}}
    updated_result = apply_director_bible_patches(storage, session_id, scene_response, data, result)
    stored = storage.read_json(session_id, "director_bible.json")

    event = next(item for item in stored["event_queue"] if item["id"] == "event_01")
    assert event["status"] == "triggered"
    assert stored["world_truth"] == original_truth
    assert "Хлоя теперь видела след искажений лично" in stored["future_consequences"]
    assert updated_result["applied"]["director_bible_patches"] == 2
    assert updated_result["rejected"] == []


def test_reveal_cannot_be_marked_revealed_before_earliest_turn(tmp_path: Path):
    storage = JsonStorage(tmp_path)
    session_id = "session_reveal"
    data = _prepared_bootstrap()
    storage.ensure_session_dir(session_id)
    storage.write_json(session_id, "director_bible.json", data["director_bible"])
    storage.write_json(session_id, "current_state.json", {**data["current_state"], "turn_number": 1})

    reveal_id = data["director_bible"]["planned_reveals"][0]["id"]
    scene_response = {
        "proposed_updates": {
            "director_bible_patches": {
                "reveal_updates": [
                    {
                        "id": reveal_id,
                        "status": "revealed",
                        "reason": "модель решила раскрыть тайну слишком рано",
                        "source_in_scene": "одна случайная реплика",
                    }
                ]
            }
        }
    }
    result = {"status": "applied", "applied": {}, "rejected": [], "next_builder_hints": {}}
    updated_result = apply_director_bible_patches(storage, session_id, scene_response, data, result)
    stored = storage.read_json(session_id, "director_bible.json")
    reveal = next(item for item in stored["planned_reveals"] if item["id"] == reveal_id)

    assert reveal["status"] == "locked"
    assert any(item["reason"] == "reveal attempted before earliest_turn" for item in updated_result["rejected"])


def test_debug_session_writes_and_reads_director_bible(tmp_path: Path):
    storage = JsonStorage(tmp_path)
    manager = SessionManager(storage)
    response = manager.create_session(
        CreateSessionRequest(
            genre="debug",
            setting_request="technical room",
            protagonist_request="technical heroine",
            mode="debug_stub",
        )
    )
    session_id = response["session_id"]

    assert "director_bible.json" in response["files_created"]
    stored = storage.read_json(session_id, "director_bible.json")
    bundle = storage.read_session_bundle(session_id)
    assert len(stored["event_queue"]) >= 3
    assert bundle["director_bible"]["world_truth"]


def test_action_schemas_include_director_bible_and_status_patches():
    bootstrap_schema = json.loads(Path("schemas/bootstrap_output.schema.json").read_text(encoding="utf-8"))
    scene_schema = json.loads(Path("schemas/scene_response.schema.json").read_text(encoding="utf-8"))
    contract_schema = json.loads(Path("schemas/scene_contract.schema.json").read_text(encoding="utf-8"))

    assert "director_bible" in bootstrap_schema["required"]
    assert bootstrap_schema["properties"]["director_bible"]["properties"]["event_queue"]["minItems"] == 3
    proposed = scene_schema["properties"]["proposed_updates"]["properties"]
    assert "director_bible_patches" in proposed
    assert "director_guidance" in contract_schema["required"]


def test_director_rule_is_compiled_into_runtime_prompt():
    from app.scene_rules_compiler import RULE_SOURCES, compile_scene_rules

    compiled = compile_scene_rules()
    assert any(source.relative_path == "rules/director_bible_rules.md" for source in RULE_SOURCES)
    assert "author_only_never_render_or_quote" in compiled
    assert "director_bible_patches" in compiled
    assert "event_queue" in compiled
