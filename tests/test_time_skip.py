from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from app.director_bible import normalise_director_bible
from app.novella_openapi_actions import build_openapi_actions
from app.storage import JsonStorage
from app.time_skip import (
    assess_time_skip,
    build_time_skip_contract,
    prepare_time_skip_state,
    record_time_skip_result,
    validate_time_skip_scene_response,
)


def _bundle() -> dict:
    data = {
        "session": {"session_id": "session_time_skip", "status": "active"},
        "protagonist": {"id": "pc_01", "name": "Mira Vale", "role": "player_character"},
        "characters": {
            "pc_01": {
                "id": "pc_01",
                "name": "Mira Vale",
                "role": "player_character",
                "cast_status": "player",
                "introduced": True,
                "available_to_scene": True,
            },
            "friend_01": {
                "id": "friend_01",
                "name": "Chloe Arden",
                "role": "old friend",
                "cast_status": "known_core",
                "introduced": True,
                "available_to_scene": True,
            },
            "hidden_01": {
                "id": "hidden_01",
                "name": "Ren Kurose",
                "role": "future core",
                "cast_status": "hidden_core",
                "introduced": False,
                "available_to_scene": False,
            },
        },
        "relationships": {},
        "knowledge": {},
        "story_plan": {
            "genre": "romantic mysticism",
            "tone": "tense",
            "setting_summary": "night city",
            "main_premise": "visible distortions follow emotional pressure",
            "protagonist_start": "late shift",
            "player_goal": "keep control",
            "central_conflict": "care becomes pressure",
            "central_question": "who gets close",
            "opening_scene_intent": "show ordinary life before pressure",
            "current_story_position": "act_1",
            "act_structure": [{"act": 1}],
            "relationship_focus": [],
            "character_arcs": {},
            "open_threads": ["the lamp reacts"],
            "forbidden_drift": ["do not reveal the source early"],
            "status_slots": [
                {"id": "story_slot_1", "label": "Pressure", "description": "social pressure", "initial_value": "low"},
                {"id": "story_slot_2", "label": "Distortion", "description": "mystic trace", "initial_value": "low"},
            ],
        },
        "current_state": {
            "turn_number": 4,
            "date": "2026-07-14",
            "time": "10:00",
            "location": "apartment",
            "weather": "clear",
            "scene_state": "conversation ended and the apartment is quiet",
            "player_character_id": "pc_01",
            "active_character_ids": ["pc_01"],
            "nearby_character_ids": ["friend_01"],
            "scene_goal": "wait for the next pressure",
            "last_player_input": "(лечь спать)",
            "outfit": "home clothes",
            "inventory": ["phone"],
            "nearby_items": ["keys"],
            "environment": {},
            "time_skip_control": {
                "allowed": True,
                "reason": "the current scene reached a natural pause",
                "blockers": [],
                "suggested_mode": "nearest_event",
                "max_unit": "days",
                "max_amount": 3,
            },
            "status": {
                "hunger": "normal",
                "fatigue": "medium",
                "injuries": [],
                "emotional_state": "tired",
                "skills": [],
                "custom": [
                    {"id": "story_slot_1", "label": "Pressure", "value": "low"},
                    {"id": "story_slot_2", "label": "Distortion", "value": "low"},
                ],
            },
        },
        "npc_state": {},
        "future_locks": {"hidden_character_ids": ["hidden_01"], "hidden_character_seeds": [], "do_not_reveal_yet": ["Ren identity"]},
        "continuity": {},
        "scene_history": [],
        "turns": [],
        "director_bible": {
            "world_truth": {"core_truth": "distortions have one cause", "world_rules": ["effects need pressure"], "hidden_cause": "hidden cause"},
            "hidden_lore": [{"id": "lore_01", "truth": "hidden truth", "status": "locked", "reveal_policy": "evidence first", "known_by": [], "related_character_ids": ["hidden_01"], "evidence_chain": ["trace"]}],
            "character_functions": {},
            "story_hooks": [{"id": "hook_01", "hook": "lamp reacts", "status": "active", "pressure": "returns", "next_escalation": "stronger flicker", "earliest_turn": 1}],
            "planned_reveals": [{"id": "reveal_01", "reveal": "source identity", "status": "locked", "earliest_turn": 8, "prerequisites": ["three traces"], "forbidden_before": "evidence"}],
            "active_conflicts": [{"id": "conflict_01", "description": "friend intervenes", "status": "active", "pressure": "messages", "next_escalation": "arrives", "do_not_resolve_with": ["one apology"]}],
            "event_queue": [
                {
                    "id": "event_hours",
                    "title": "Call after the pause",
                    "status": "ready",
                    "priority": 60,
                    "earliest_turn": 5,
                    "latest_turn": 6,
                    "conditions": ["natural pause"],
                    "participants": ["friend_01"],
                    "purpose": "friend acts without waiting",
                    "scene_pressure": "unanswered call",
                    "next_if_ignored": "friend comes over",
                    "time_hint": "in a few hours",
                    "skip_unit": "hours",
                    "skip_amount": 3,
                },
                {
                    "id": "event_days",
                    "title": "Work consequence",
                    "status": "planned",
                    "priority": 95,
                    "earliest_turn": 5,
                    "latest_turn": 8,
                    "conditions": ["two days pass"],
                    "participants": [],
                    "purpose": "show consequence",
                    "scene_pressure": "missed deadline",
                    "next_if_ignored": "manager calls",
                    "time_hint": "in two days",
                    "skip_unit": "days",
                    "skip_amount": 2,
                },
                {
                    "id": "event_locked_by_turn",
                    "title": "Premature hidden arrival",
                    "status": "planned",
                    "priority": 100,
                    "earliest_turn": 10,
                    "latest_turn": 12,
                    "conditions": ["later act"],
                    "participants": ["hidden_01"],
                    "purpose": "future reveal pressure",
                    "scene_pressure": "unknown observer",
                    "next_if_ignored": "indirect trace",
                    "time_hint": "later",
                    "skip_unit": "hours",
                    "skip_amount": 1,
                },
            ],
            "time_anchors": [],
            "time_flow": {
                "current_period": "act_1",
                "default_mode": "nearest_event",
                "allow_nearest_event": True,
                "allowed_units": ["hours", "days", "weeks"],
                "max_amounts": {"hours": 24, "days": 7, "weeks": 2, "months": 1},
                "last_skip": None,
            },
            "do_not_resolve_early": [],
            "continuity_truths": [],
            "future_consequences": [],
            "pacing": {"current_phase": "act_1", "quiet_scene_budget": 1, "major_reveal_spacing": 2, "notes": []},
            "history": [],
        },
    }
    data["director_bible"] = normalise_director_bible(data["director_bible"], data)
    return data


def test_bootstrap_time_skip_is_blocked_until_a_scene_saves_natural_pause():
    data = {"current_state": {"turn_number": 0}}
    control = prepare_time_skip_state(data)

    assert control["allowed"] is False
    assert control["blockers"] == ["opening_scene_not_played"]
    assert data["current_state"]["time_skip_control"] == control


def test_nearest_event_uses_time_distance_and_respects_earliest_turn():
    bundle = _bundle()
    assessment = assess_time_skip(bundle, mode="nearest_event")

    assert assessment["allowed"] is True
    assert assessment["target_event"]["id"] == "event_hours"
    assert assessment["unit"] == "hours"
    assert assessment["amount"] == 3
    assert assessment["target_frame_hint"] == {"date": "2026-07-14", "time": "13:00", "deterministic": True}
    assert assessment["target_event"]["id"] != "event_locked_by_turn"


def test_duration_skip_respects_scene_limit_and_selects_highest_priority_reachable_event():
    bundle = _bundle()
    assessment = assess_time_skip(bundle, mode="duration", unit="days", amount=2)

    assert assessment["allowed"] is True
    assert assessment["target_event"]["id"] == "event_days"

    blocked = assess_time_skip(bundle, mode="duration", unit="weeks", amount=1)
    assert blocked["allowed"] is False
    assert "duration_exceeds_scene_control" in blocked["blockers"]


def test_day_number_calendar_is_calculated_across_midnight():
    bundle = _bundle()
    bundle["current_state"].update({"date": "День 1", "time": "22:40"})

    assessment = assess_time_skip(bundle, mode="duration", unit="hours", amount=3)

    assert assessment["target_frame_hint"] == {
        "date": "День 2",
        "time": "01:40",
        "deterministic": True,
    }


def test_invalid_clock_does_not_produce_a_fake_deterministic_target():
    bundle = _bundle()
    bundle["current_state"].update({"date": "День 1", "time": "77:88"})

    assessment = assess_time_skip(bundle, mode="duration", unit="hours", amount=3)

    assert assessment["target_frame_hint"]["deterministic"] is False


def test_time_skip_contract_keeps_hidden_core_out_of_loaded_scene():
    bundle = _bundle()
    bundle["director_bible"]["event_queue"][0].update({
        "participants": ["hidden_01"],
        "skip_amount": 1,
    })
    contract, assessment = build_time_skip_contract(
        bundle,
        player_input="(пропустить время до ближайшего события)",
        mode="nearest_event",
    )

    loaded_ids = {item["character_id"] for item in contract["loaded_characters"]}
    assert "hidden_01" not in loaded_ids
    assert assessment["hidden_participant_ids"] == ["hidden_01"]
    assert contract["time_skip_request"]["rules"]["no_player_choice"]
    assert contract["time_skip_request"]["target_event"]["id"] == "event_hours"


def _valid_time_skip_response() -> dict:
    return {
        "time_skip_result": {
            "elapsed": {"unit": "hours", "amount": 3, "label": "три часа"},
            "routine_summary": ["Мира выспалась", "Хлоя закончила смену и снова позвонила"],
            "target_event_id": "event_hours",
            "opened_at_meaningful_beat": True,
            "skipped_major_player_choice": False,
        },
        "proposed_updates": {
            "scene_state_patch": {
                "date": "2026-07-14",
                "time": "13:00",
                "time_skip_control": {
                    "allowed": False,
                    "reason": "новое событие уже началось",
                    "blockers": ["event_in_progress"],
                    "suggested_mode": "nearest_event",
                    "max_unit": "days",
                    "max_amount": 3,
                },
            },
            "director_bible_patches": {
                "event_updates": [
                    {
                        "id": "event_hours",
                        "status": "triggered",
                        "reason": "Хлоя позвонила после смены",
                        "source_in_scene": "телефон завибрировал на столе",
                    }
                ]
            },
        },
    }


def test_time_skip_result_requires_exact_elapsed_event_and_closes_skip_window():
    bundle = _bundle()
    pending = {
        "turn_kind": "time_skip",
        "time_skip_request": {"mode": "nearest_event", "unit": "hours", "amount": 3, "target_event": {"id": "event_hours"}},
    }
    response = _valid_time_skip_response()

    assert validate_time_skip_scene_response(pending, response, bundle) == []

    response["time_skip_result"]["elapsed"]["amount"] = 4
    response["proposed_updates"]["scene_state_patch"]["time_skip_control"]["allowed"] = True
    errors = validate_time_skip_scene_response(pending, response, bundle)
    assert "time_skip_result.elapsed must match the selected skip duration" in errors
    assert "time skip must close time_skip_control until the new scene reaches another natural pause" in errors


def test_time_skip_rejects_model_invented_date_instead_of_server_target():
    bundle = _bundle()
    pending = {
        "turn_kind": "time_skip",
        "time_skip_request": {
            "mode": "nearest_event",
            "unit": "hours",
            "amount": 3,
            "target_event": {"id": "event_hours"},
            "target_frame_hint": {"date": "2026-07-14", "time": "13:00", "deterministic": True},
        },
    }
    response = _valid_time_skip_response()
    response["proposed_updates"]["scene_state_patch"].update({"date": "2026-07-15", "time": "09:00"})

    errors = validate_time_skip_scene_response(pending, response, bundle)

    assert any("server-calculated target frame" in error for error in errors)


def test_record_time_skip_persists_last_skip_without_rewriting_world_truth(tmp_path: Path):
    bundle = _bundle()
    storage = JsonStorage(tmp_path)
    session_id = "session_time_skip"
    storage.ensure_session_dir(session_id)
    storage.write_json(session_id, "current_state.json", {**bundle["current_state"], "turn_number": 5, "time": "13:00"})
    storage.write_json(session_id, "director_bible.json", bundle["director_bible"])
    original_truth = deepcopy(bundle["director_bible"]["world_truth"])
    pending = {
        "turn_kind": "time_skip",
        "time_skip_request": {
            "mode": "nearest_event",
            "unit": "hours",
            "amount": 3,
            "target_event": {"id": "event_hours"},
            "from_frame": {"date": "2026-07-14", "time": "10:00", "location": "apartment"},
        },
    }
    result = {"status": "applied", "applied": {}, "rejected": [], "next_builder_hints": {}}

    updated = record_time_skip_result(storage, session_id, pending, _valid_time_skip_response(), bundle, result)
    stored = storage.read_json(session_id, "director_bible.json")

    assert stored["world_truth"] == original_truth
    assert stored["time_flow"]["last_skip"]["target_event_id"] == "event_hours"
    assert stored["time_flow"]["last_skip"]["elapsed"] == {"unit": "hours", "amount": 3, "label": "три часа"}
    assert updated["applied"]["time_skip"]["target_event_id"] == "event_hours"


def test_actions_and_schemas_expose_advance_time_contract():
    actions = build_openapi_actions("https://example.invalid")
    assert actions["paths"]["/api/v1/sessions/{session_id}/advance-time"]["post"]["operationId"] == "advanceTime"
    assert "AdvanceTimeRequest" in actions["components"]["schemas"]

    scene_schema = json.loads(Path("schemas/scene_response.schema.json").read_text(encoding="utf-8"))
    bootstrap_schema = json.loads(Path("schemas/bootstrap_output.schema.json").read_text(encoding="utf-8"))
    assert "time_skip_result" in scene_schema["properties"]
    assert "time_skip_control" in bootstrap_schema["properties"]["current_state"]["required"]
    assert "time_flow" in bootstrap_schema["properties"]["director_bible"]["required"]

    compiled_rules = Path("rules/time_skip_rules.md").read_text(encoding="utf-8")
    instruction = Path("gpt/custom_gpt_instructions.md").read_text(encoding="utf-8")
    assert all(token in compiled_rules for token in ("advanceTime", "time_skip_control", "time_skip_result"))
    assert "advanceTime" in instruction
