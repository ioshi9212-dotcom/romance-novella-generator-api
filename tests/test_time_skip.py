from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from app.bootstrap_normalizer import normalize_bootstrap_json
from app.character_profiles import prepare_bootstrap_cast
from app.directional_relationships import prepare_directional_relationships
from app.director_bible import prepare_director_bible
from app.main import _process_turn_locked
from app.models import TurnRequest
from app.npc_runtime import prepare_npc_runtime_map
from app.scene_rules_compiler import compile_scene_rules
from app.session_manager import SessionManager
from app.state_updater import StateUpdater
from app.storage import JsonStorage
from app.time_skip import (
    TIME_SKIP_ACTION,
    build_time_skip_contract,
    ensure_time_skip_state_patch,
    is_time_skip_command,
    select_time_skip_event,
    time_skip_availability,
    validate_time_skip_scene_response,
)
from app.turn_processor import process_time_skip_gpt_actions


def _raw_bundle(*, allowed: bool = True) -> dict:
    return {
        "session": {"session_id": "session_time_skip", "status": "active", "title": "Time Skip Test"},
        "protagonist": {"id": "pc_01", "name": "Mira Vale", "role": "player_character"},
        "characters": {
            "pc_01": {
                "id": "pc_01",
                "name": "Mira Vale",
                "role": "player_character",
                "goal": "не позволять другим принимать за неё важные решения",
                "past_short": "она привыкла сама определять дистанцию",
                "introduced": True,
                "known_to_player": True,
            },
            "friend_01": {
                "id": "friend_01",
                "name": "Chloe Arden",
                "role": "old friend",
                "goal": "добиться прямого разговора вместо очередного исчезновения",
                "past_short": "они давно спорят о праве вмешиваться",
                "introduced": True,
                "known_to_player": True,
            },
            "hidden_01": {
                "id": "hidden_01",
                "name": "Ren Kurose",
                "role": "future core character",
                "goal": "добраться до источника искажений",
                "past_short": "его участие пока скрыто",
                "introduced": False,
                "known_to_player": False,
                "cast_status": "hidden_core",
            },
        },
        "relationships": {},
        "knowledge": {
            "friend_01": {
                "character_id": "friend_01",
                "known_facts": ["Мира часто задерживается после смены"],
                "observations": ["она отвечает короче, когда устала"],
                "assumptions": ["молчание означает, что снова случилась проблема"],
                "wrong_beliefs": ["без вмешательства Мира обязательно исчезнет"],
                "does_not_know": ["истинную причину сбоев"],
                "must_not_assume": ["мысли Миры"],
                "recent_memories": ["последний спор закончился без ответа"],
                "open_questions": [],
                "knows": [],
            }
        },
        "story_plan": {
            "genre": "romantic mysticism",
            "language": "ru",
            "tone": "adult, tense",
            "setting_summary": "ночной город и работа после закрытия",
            "main_premise": "эмоциональное давление связано с физическими искажениями",
            "protagonist_start": "смена закончилась",
            "player_goal": "сохранить контроль",
            "central_conflict": "чужие цели давят на границы героини",
            "central_question": "кого она допустит ближе",
            "opening_scene_intent": "показать обычную жизнь и первый слабый сбой",
            "act_structure": [{"act": 1, "goal": "первое давление", "must_happen": ["сбой"], "must_not_resolve_yet": ["источник"]}],
            "character_arcs": {},
            "relationship_focus": [],
            "open_threads": ["почему свет реагирует на Миру"],
            "forbidden_drift": ["не раскрывать источник сразу"],
            "current_story_position": "act_1_start",
            "status_slots": [
                {"id": "story_slot_1", "label": "Давление", "description": "социальное давление", "initial_value": "низкое"},
                {"id": "story_slot_2", "label": "Искажение", "description": "видимость мистики", "initial_value": "слабое"},
            ],
        },
        "current_state": {
            "turn_number": 4,
            "date": "День 1",
            "time": "23:20",
            "location": "квартира Миры",
            "weather": "дождь",
            "scene_state": "разговор завершён и квартира снова пуста",
            "player_character_id": "pc_01",
            "active_character_ids": ["pc_01"],
            "nearby_character_ids": [],
            "scene_goal": "естественная пауза",
            "last_player_input": "(закрыть дверь)",
            "outfit": "домашняя футболка",
            "inventory": ["телефон"],
            "nearby_items": ["ключи"],
            "environment": {"light": "тусклый", "sound": "дождь", "air": "прохладный", "details": []},
            "time_skip_state": {
                "allowed": allowed,
                "reason": "смысловой бит завершён, немедленных последствий нет",
                "suggested_horizon": "до следующего вечера",
                "blocked_by": [],
            },
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
        "npc_state": {
            "friend_01": {
                "character_id": "friend_01",
                "current_goal": "приехать и поговорить лично",
                "current_route": "заканчивает смену",
                "current_pressure": "боится очередного исчезновения",
                "current_mood": "обижена",
                "current_urge": "проверить всё самой",
                "behavior_mode": "pursuit",
                "last_trigger": "уклончивый ответ",
                "unresolved_emotion": "обида",
                "next_self_action_if_ignored": "приехать без предупреждения",
                "change_stage": "defensive",
            }
        },
        "director_bible": {
            "world_truth": {
                "core_truth": "искажения имеют одну устойчивую причинную основу",
                "world_rules": ["они усиливаются рядом с подавленными эмоциями"],
                "hidden_cause": "источник пока не раскрыт",
            },
            "hidden_lore": [
                {
                    "id": "lore_01",
                    "truth": "скрытая причина связана с прошлым героини",
                    "status": "locked",
                    "reveal_policy": "только через свидетельства",
                    "known_by": [],
                    "related_character_ids": [],
                    "evidence_chain": [],
                }
            ],
            "story_hooks": [
                {
                    "id": "hook_01",
                    "hook": "свет реагирует на присутствие Миры",
                    "status": "active",
                    "related_character_ids": [],
                    "pressure": "сбой возвращается",
                    "next_escalation": "новый видимый след",
                    "earliest_turn": 1,
                }
            ],
            "planned_reveals": [
                {
                    "id": "reveal_01",
                    "reveal": "причина искажений",
                    "status": "locked",
                    "earliest_turn": 8,
                    "latest_turn": 0,
                    "prerequisites": ["два свидетельства"],
                    "forbidden_before": "не объяснять напрямую",
                    "related_character_ids": [],
                }
            ],
            "active_conflicts": [
                {
                    "id": "conflict_01",
                    "description": "забота Хлои превращается в давление",
                    "status": "active",
                    "sides": ["pc_01", "friend_01"],
                    "pressure": "границы становятся жёстче",
                    "next_escalation": "Хлоя действует без разрешения",
                    "do_not_resolve_with": ["один спокойный разговор"],
                }
            ],
            "event_queue": [
                {
                    "id": "event_hidden",
                    "title": "Скрытый визит",
                    "status": "ready",
                    "priority": 100,
                    "earliest_turn": 5,
                    "latest_turn": 7,
                    "conditions": ["персонаж раскрыт"],
                    "participants": ["hidden_01"],
                    "purpose": "ввести скрытого персонажа",
                    "scene_pressure": "тайный контакт",
                    "next_if_ignored": "след останется",
                    "time_hint": "на следующую ночь",
                },
                {
                    "id": "event_public",
                    "title": "Хлоя приезжает сама",
                    "status": "ready",
                    "priority": 80,
                    "earliest_turn": 5,
                    "latest_turn": 6,
                    "conditions": ["Мира осталась дома"],
                    "participants": ["friend_01"],
                    "purpose": "дать самостоятельный шаг Хлои",
                    "scene_pressure": "разговор начнётся без приглашения",
                    "next_if_ignored": "Хлоя постучит настойчивее",
                    "time_hint": "следующим вечером",
                },
                {
                    "id": "event_later",
                    "title": "Возвращение сбоя",
                    "status": "planned",
                    "priority": 40,
                    "earliest_turn": 7,
                    "latest_turn": 10,
                    "conditions": [],
                    "participants": [],
                    "purpose": "вернуть мистический крючок",
                    "scene_pressure": "новый след",
                    "next_if_ignored": "сбой станет заметнее",
                    "time_hint": "через несколько дней",
                },
            ],
            "pacing": {"current_phase": "act_1_start", "quiet_scene_budget": 1, "major_reveal_spacing": 2, "notes": []},
        },
        "future_locks": {
            "hidden_character_seeds": [],
            "hidden_character_ids": ["hidden_01"],
            "do_not_reveal_yet": ["скрытого персонажа нельзя показывать до раскрытия"],
        },
        "continuity": {},
        "scene_history": [],
        "turns": [],
    }


def _prepared_bundle(*, allowed: bool = True) -> dict:
    data = normalize_bootstrap_json(_raw_bundle(allowed=allowed))
    data["session"] = _raw_bundle(allowed=allowed)["session"]
    prepare_bootstrap_cast(data)
    prepare_directional_relationships(data)
    prepare_npc_runtime_map(data)
    prepare_director_bible(data)
    # Keep the explicit test queue after all compatibility normalisers ran.
    data["director_bible"]["event_queue"] = _raw_bundle(allowed=allowed)["director_bible"]["event_queue"]
    return data


def _valid_time_skip_response() -> dict:
    return {
        "player_input": TIME_SKIP_ACTION,
        "scene": {
            "header": {
                "date": "День 2",
                "time": "19:10",
                "location": "квартира Миры",
                "scene_state": "Хлоя только что постучала",
            }
        },
        "proposed_updates": {
            "scene_state_patch": {
                "date": "День 2",
                "time": "19:10",
                "location": "квартира Миры",
                "scene_state": "Хлоя только что постучала",
                "active_character_ids": ["pc_01", "friend_01"],
                "time_skip_state": {
                    "allowed": False,
                    "reason": "переход завершён, началось новое событие",
                    "suggested_horizon": "до следующей естественной паузы",
                },
            },
            "director_bible_patches": {
                "event_updates": [
                    {
                        "id": "event_public",
                        "status": "triggered",
                        "reason": "переход открыл сцену у выбранного события",
                        "source_in_scene": "Хлоя постучала в дверь",
                    }
                ]
            },
        },
        "metadata": {
            "time_skip": {
                "applied": True,
                "target_event_id": "event_public",
                "elapsed_summary": "прошёл следующий день; Хлоя закончила смену и приехала сама",
            }
        },
    }


def test_command_detection_and_default_denial():
    assert is_time_skip_command(TIME_SKIP_ACTION)
    assert is_time_skip_command("пропустить время!")
    assert not is_time_skip_command("подождать пять минут")

    denied = time_skip_availability(_prepared_bundle(allowed=False))
    assert denied["allowed"] is False
    assert "естествен" in denied["reason"] or "смысловой" in denied["reason"]


def test_hidden_event_is_skipped_and_public_event_is_selected():
    bundle = _prepared_bundle()
    event = select_time_skip_event(bundle)

    assert event is not None
    assert event["id"] == "event_public"
    assert time_skip_availability(bundle)["allowed"] is True


def test_time_skip_contract_locks_one_public_target_and_loads_its_context():
    bundle = _prepared_bundle()
    contract = build_time_skip_contract(bundle, TIME_SKIP_ACTION)
    encoded = json.dumps(contract, ensure_ascii=False)

    assert contract["contract_version"] == "novella.time_skip_contract.v1"
    assert contract["time_skip"]["target_event"]["id"] == "event_public"
    assert [item["id"] for item in contract["director_guidance"]["due_or_next_events"]] == ["event_public"]
    assert "friend_01" in contract["time_skip"]["target_character_context"]
    assert contract["time_skip"]["target_character_context"]["friend_01"]["npc_runtime"]["current_goal"]
    assert contract["time_skip"]["target_relationships"]
    assert "Ren Kurose" not in encoded
    assert "event_hidden" not in encoded


def test_time_skip_prompt_and_pending_mode_are_distinct(tmp_path):
    bundle = _prepared_bundle()
    result = process_time_skip_gpt_actions(bundle, TIME_SKIP_ACTION)

    assert result["status"] == "gpt_actions_time_skip_prompt_ready"
    assert result["diagnostics"]["target_event_id"] == "event_public"
    assert "TIME_SKIP_CONTRACT_JSON:" in result["scene_prompt"]
    assert TIME_SKIP_ACTION in result["scene_prompt"]
    assert "Ren Kurose" not in result["scene_prompt"]

    storage = JsonStorage(tmp_path)
    manager = SessionManager(storage)
    response = _process_turn_locked(
        manager,
        "session_time_skip",
        TurnRequest(player_input=TIME_SKIP_ACTION),
        TIME_SKIP_ACTION,
        bundle,
    )
    pending = storage.read_json("session_time_skip", "pending_turn.json")
    assert response["turn_id"] == pending["turn_id"]
    assert pending["turn_mode"] == "time_skip"
    assert pending["target_event_id"] == "event_public"


def test_process_turn_rejects_time_skip_without_saved_pause(tmp_path):
    bundle = _prepared_bundle(allowed=False)
    manager = SessionManager(JsonStorage(tmp_path))

    with pytest.raises(HTTPException) as exc_info:
        _process_turn_locked(
            manager,
            "session_time_skip_denied",
            TurnRequest(player_input=TIME_SKIP_ACTION),
            TIME_SKIP_ACTION,
            bundle,
        )
    assert exc_info.value.status_code == 409


def test_time_skip_response_validation_requires_advance_metadata_and_trigger():
    bundle = _prepared_bundle()
    pending = {"turn_mode": "time_skip", "target_event_id": "event_public"}
    valid = _valid_time_skip_response()
    assert validate_time_skip_scene_response(valid, pending, bundle) == []

    broken = _valid_time_skip_response()
    broken["metadata"]["time_skip"]["elapsed_summary"] = ""
    broken["proposed_updates"]["director_bible_patches"]["event_updates"][0]["status"] = "completed"
    errors = validate_time_skip_scene_response(broken, pending, bundle)
    assert any("elapsed_summary" in error for error in errors)
    assert any("status=triggered" in error for error in errors)


def test_normal_scene_clears_stale_permission_but_preserves_explicit_new_pause():
    ordinary = ensure_time_skip_state_patch({"proposed_updates": {"scene_state_patch": {}}}, {"turn_mode": "scene"})
    assert ordinary["proposed_updates"]["scene_state_patch"]["time_skip_state"]["allowed"] is False

    explicit = ensure_time_skip_state_patch(
        {
            "proposed_updates": {
                "scene_state_patch": {
                    "time_skip_state": {
                        "allowed": True,
                        "reason": "разговор закончен",
                        "suggested_horizon": "до утра",
                    }
                }
            }
        },
        {"turn_mode": "scene"},
    )
    assert explicit["proposed_updates"]["scene_state_patch"]["time_skip_state"]["allowed"] is True


def test_state_updater_persists_time_skip_state(tmp_path):
    storage = JsonStorage(tmp_path)
    session_id = "session_state_time_skip"
    bundle = _prepared_bundle(allowed=False)

    scalar = {
        "session.json": bundle["session"],
        "user_request.json": {},
        "protagonist.json": bundle["protagonist"],
        "story_plan.json": bundle["story_plan"],
        "current_state.json": bundle["current_state"],
        "npc_state.json": bundle["npc_state"],
        "future_locks.json": bundle["future_locks"],
        "director_bible.json": bundle["director_bible"],
        "continuity.json": {},
        "scene_history.json": [],
        "turns.json": [],
        "characters.json": bundle["characters"],
        "knowledge.json": bundle["knowledge"],
        "relationships.json": bundle["relationships"],
    }
    for filename, value in scalar.items():
        storage.write_json(session_id, filename, value)

    scene_response = {
        "player_input": "(лечь спать)",
        "scene": {"body": "Сцена завершилась.", "rendered_text": "Сцена завершилась."},
        "summary": "Героиня осталась одна, немедленных последствий нет.",
        "important_facts": [],
        "witnesses": ["pc_01"],
        "proposed_updates": {
            "scene_state_patch": {
                "time_skip_state": {
                    "allowed": True,
                    "reason": "смысловой бит завершён",
                    "suggested_horizon": "до следующего вечера",
                    "blocked_by": [],
                }
            }
        },
    }
    StateUpdater(storage).apply_scene_response(session_id, scene_response)
    saved = storage.read_json(session_id, "current_state.json")
    assert saved["time_skip_state"]["allowed"] is True
    assert saved["time_skip_state"]["suggested_horizon"] == "до следующего вечера"


def test_compiled_rules_include_exact_visible_action_and_safety_boundary():
    compiled = compile_scene_rules()
    assert TIME_SKIP_ACTION in compiled
    assert "естественной паузе" in compiled
    assert "немедленной опасности" in compiled
    assert "time_skip_state" in compiled
