from typing import Any

from app.id_utils import pair_id
from app.npc_runtime import compact_npc_runtime_entry


TECH_LABEL_MAP = {
    "vision_intensity": "Видения",
    "vision": "Видения",
    "emotional_numbness": "Эмоциональная отстранённость",
    "mystic_pressure": "Мистическое давление",
    "relationship_tension": "Напряжение отношений",
    "story_slot_1": "Поле истории 1",
    "story_slot_2": "Поле истории 2",
}


def _clip_text(value: Any, limit: int = 500) -> str:
    text = "" if value is None else str(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


def _clip_list(items: Any, limit_items: int = 6, text_limit: int = 180) -> list[Any]:
    if not isinstance(items, list):
        return []
    result: list[Any] = []
    for item in items[:limit_items]:
        if isinstance(item, str):
            result.append(_clip_text(item, text_limit))
        elif isinstance(item, dict):
            result.append({str(key): _clip_text(value, text_limit) if isinstance(value, str) else value for key, value in item.items()})
        else:
            result.append(item)
    return result


def _compact_dict(value: Any, limit: int = 500) -> Any:
    if isinstance(value, dict):
        return {str(key): _compact_dict(item, max(160, limit // 2)) for key, item in value.items()}
    if isinstance(value, list):
        return _clip_list(value, 6, max(120, limit // 3))
    if isinstance(value, str):
        return _clip_text(value, limit)
    return value


def _compact_history_entry(entry: Any) -> dict[str, Any]:
    if not isinstance(entry, dict):
        return {}
    return {
        "turn": entry.get("turn"),
        "summary": _clip_text(entry.get("summary", ""), 360),
        "important_facts": _clip_list(entry.get("important_facts", []), 4, 160),
        "witnesses": _clip_list(entry.get("witnesses", []), 8, 80),
    }


def _compact_memory_chunk(chunk: Any) -> dict[str, Any]:
    if not isinstance(chunk, dict):
        return {}
    return {
        "type": chunk.get("type"),
        "turn_start": chunk.get("turn_start"),
        "turn_end": chunk.get("turn_end"),
        "scene_summaries": _clip_list(chunk.get("scene_summaries", []), 4, 180),
        "turn_summaries": _clip_list(chunk.get("turn_summaries", []), 4, 160),
    }


def _compact_continuity(continuity: Any) -> dict[str, Any]:
    if not isinstance(continuity, dict):
        return {}
    return {
        "current_arc": continuity.get("current_arc"),
        "current_act": continuity.get("current_act"),
        "open_threads": _clip_list(continuity.get("open_threads", []), 8, 200),
        "notes": _clip_list(continuity.get("notes", []), 6, 180),
        "warnings": _clip_list(continuity.get("warnings", []), 5, 180),
        "maintenance_events": _clip_list(continuity.get("maintenance_events", []), 4, 160),
    }


def _get_character(characters: dict[str, Any], character_id: str) -> dict[str, Any] | None:
    character = characters.get(character_id)
    return character if isinstance(character, dict) else None


def _display_name(characters: dict[str, Any], character_id: str) -> str:
    card = _get_character(characters, character_id)
    if not card:
        return character_id
    for key in ["display_name", "visible_name", "name_ru", "russian_name", "name"]:
        value = card.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return character_id


def _human_label(value: Any, fallback: str) -> str:
    text = _clip_text(value, 80).strip()
    if not text or text == "—":
        return fallback
    key = text.lower()
    if key in TECH_LABEL_MAP:
        return TECH_LABEL_MAP[key]
    if "_" in key and key.isascii():
        return TECH_LABEL_MAP.get(key, fallback)
    return text


def _knowledge_boundary(knowledge: dict[str, Any], character_id: str) -> dict[str, Any]:
    entry = knowledge.get(character_id, {})
    return {
        "character_id": character_id,
        "known": _clip_list(entry.get("knows", []), 8, 160),
        "known_facts": _clip_list(entry.get("known_facts", []), 8, 160),
        "observations": _clip_list(entry.get("observations", [])[-6:], 6, 160),
        "assumptions": _clip_list(entry.get("assumptions", [])[-6:], 6, 160),
        "wrong_beliefs": _clip_list(entry.get("wrong_beliefs", [])[-6:], 6, 160),
        "recent_memories": _clip_list(entry.get("recent_memories", [])[-6:], 6, 180),
        "open_questions": _clip_list(entry.get("open_questions", []), 6, 160),
        "unknown": _clip_list(entry.get("does_not_know", []), 6, 160),
        "must_not_assume": _clip_list(entry.get("must_not_assume", []), 6, 160),
    }


def _normalise_status(current_state: dict[str, Any], story_plan: dict[str, Any]) -> dict[str, Any]:
    status = current_state.get("status") or {}
    status_slots = story_plan.get("status_slots") or []
    custom_source = status.get("custom") or []
    normalised_custom: list[dict[str, str]] = []
    for index in range(2):
        slot = status_slots[index] if index < len(status_slots) and isinstance(status_slots[index], dict) else {}
        source = custom_source[index] if index < len(custom_source) else {}
        if not isinstance(source, dict):
            source = {"value": source}
        raw_id = source.get("id") or slot.get("id") or f"story_slot_{index + 1}"
        raw_label = source.get("label") or slot.get("label") or raw_id
        fallback_label = slot.get("label") or f"Поле истории {index + 1}"
        label = _human_label(raw_label, _human_label(raw_id, fallback_label))
        value = source.get("value") or slot.get("initial_value") or "не задано"
        normalised_custom.append({"id": str(raw_id), "label": str(label), "value": _clip_text(value, 160)})
    return {
        "hunger": status.get("hunger", "норма"),
        "fatigue": status.get("fatigue", "низкая"),
        "injuries": status.get("injuries", []),
        "emotional_state": status.get("emotional_state", "нейтрально"),
        "skills": status.get("skills", []),
        "custom": normalised_custom,
    }


def _baseline_relationship_content(characters: dict[str, Any], a: str, b: str) -> dict[str, Any]:
    a_name = _display_name(characters, a)
    b_name = _display_name(characters, b)
    return {
        "pair_id": pair_id(a, b),
        "character_a": a,
        "character_b": b,
        "type": "baseline",
        "status": "первое впечатление",
        "scores": {"trust": 50, "tension": 15, "attachment": 0, "respect": 30, "fear": 0, "curiosity": 25},
        "a_view_of_b": {"summary": f"{a_name} пока считывает {b_name} по видимому поведению.", "current_assumption": "может ошибаться"},
        "b_view_of_a": {"summary": f"{b_name} пока считывает {a_name} по видимому поведению.", "current_assumption": "может ошибаться"},
        "shared_history": [],
        "recent_changes": [],
        "open_threads": [],
        "is_runtime_baseline": True,
    }


def _focused_npc_runtime(
    characters: dict[str, Any],
    npc_state: dict[str, Any],
    focus_ids: list[str],
    player_id: str,
) -> dict[str, Any]:
    focused: dict[str, Any] = {}
    for character_id in focus_ids:
        if character_id == player_id:
            continue
        card = _get_character(characters, character_id)
        if not card or card.get("available_to_scene") is False or card.get("introduced") is False:
            continue
        runtime = compact_npc_runtime_entry(npc_state.get(character_id))
        if runtime:
            focused[character_id] = runtime
    return {
        "rules": {
            "state_is_persistent": "current mood, urge, pressure and unresolved emotion carry into later scenes until events change them",
            "awareness_is_not_change": "понимание ошибки или извинение не означает мгновенную смену привычного поведения",
            "relapse_under_stress": "под давлением персонаж возвращается к старому конфликтному и защитному паттерну",
            "voice_is_not_uniform": "тихо, спокойно, ровно и бережно не являются стандартной манерой всех NPC",
            "patch_when_changed": "если сцена реально изменила runtime NPC, верни npc_state_patches с причиной и источником",
        },
        "characters": focused,
    }


def build_scene_contract(bundle: dict[str, Any], player_input: str | None = None) -> dict[str, Any]:
    current_state = bundle.get("current_state", {})
    characters = bundle.get("characters", {})
    relationships = bundle.get("relationships", {})
    knowledge = bundle.get("knowledge", {})
    story_plan = bundle.get("story_plan", {})
    npc_state = bundle.get("npc_state", {})
    future_locks = bundle.get("future_locks", {})
    continuity = bundle.get("continuity", {})
    scene_history = bundle.get("scene_history", [])
    active_ids = current_state.get("active_character_ids", []) or []
    nearby_ids = current_state.get("nearby_character_ids", []) or []
    player_id = current_state.get("player_character_id") or current_state.get("player_character_character_id") or "protagonist"
    turn_number = int(current_state.get("turn_number", 0) or 0)

    focus_ids: list[str] = []
    for character_id in [player_id, *active_ids, *nearby_ids]:
        if character_id and character_id not in focus_ids:
            focus_ids.append(character_id)
    scene_ids: list[str] = []
    for character_id in [player_id, *active_ids]:
        if character_id and character_id not in scene_ids:
            scene_ids.append(character_id)

    loaded_characters = []
    for character_id in focus_ids:
        card = _get_character(characters, character_id)
        if card:
            load_reason = ["player_character"] if character_id == player_id else (["physically_present"] if character_id in scene_ids else ["nearby_context"])
            loaded_characters.append({"character_id": character_id, "display_name": _display_name(characters, character_id), "load_reason": load_reason, "card": card})

    loaded_relationships = []
    visible_relationship_pair_ids: list[str] = []
    for index, character_a in enumerate(focus_ids):
        for character_b in focus_ids[index + 1:]:
            relationship_id = pair_id(character_a, character_b)
            both_in_scene = character_a in scene_ids and character_b in scene_ids
            if relationship_id in relationships:
                content = relationships[relationship_id]
                load_reason = ["both_present"] if both_in_scene else ["nearby_context"]
                is_baseline = False
            elif both_in_scene and player_id in {character_a, character_b}:
                content = _baseline_relationship_content(characters, character_a, character_b)
                load_reason = ["runtime_baseline", "both_present"]
                is_baseline = True
            else:
                continue
            loaded_relationships.append({
                "pair_id": relationship_id,
                "display_label": f"{_display_name(characters, character_a)} ↔ {_display_name(characters, character_b)}",
                "load_reason": load_reason,
                "visible_in_footer": both_in_scene,
                "is_runtime_baseline": is_baseline,
                "content": content,
            })
            if both_in_scene:
                visible_relationship_pair_ids.append(relationship_id)

    status = _normalise_status(current_state, story_plan)
    status_slots = status.get("custom", [])
    memory_chunks = [
        _compact_memory_chunk(chunk)
        for chunk in (continuity.get("memory_chunks", []) or [])[-4:]
        if isinstance(chunk, dict)
    ]
    recent_scene_history = [
        _compact_history_entry(item)
        for item in (scene_history[-4:] if isinstance(scene_history, list) else [])
        if isinstance(item, dict)
    ]

    return {
        "contract_version": "novella.scene_contract.v1",
        "session_id": bundle.get("session", {}).get("session_id"),
        "current_frame": {
            "player_character_id": player_id,
            "player_display_name": _display_name(characters, player_id),
            "date": current_state.get("date"),
            "time": current_state.get("time"),
            "location": current_state.get("location"),
            "weather": current_state.get("weather", ""),
            "scene_state": current_state.get("scene_state", ""),
            "outfit": current_state.get("outfit", ""),
            "inventory": current_state.get("inventory", []),
            "nearby_items": current_state.get("nearby_items", []),
            "scene_goal": _clip_text(current_state.get("scene_goal"), 450),
            "last_player_input": player_input if player_input is not None else current_state.get("last_player_input", ""),
            "active_character_ids": active_ids,
            "active_character_display_names": [_display_name(characters, character_id) for character_id in active_ids],
            "nearby_character_ids": nearby_ids,
            "environment": current_state.get("environment", {}),
            "status": status,
        },
        "loaded_characters": loaded_characters,
        "loaded_relationships": loaded_relationships,
        "visible_relationship_pair_ids": visible_relationship_pair_ids,
        "knowledge_boundaries": [_knowledge_boundary(knowledge, character_id) for character_id in focus_ids if character_id in knowledge],
        "story_compass": {
            "genre": story_plan.get("genre"),
            "tone": story_plan.get("tone"),
            "setting_summary": _clip_text(story_plan.get("setting_summary"), 500),
            "main_premise": _clip_text(story_plan.get("main_premise"), 500),
            "protagonist_start": _clip_text(story_plan.get("protagonist_start"), 360),
            "player_goal": _clip_text(story_plan.get("player_goal"), 360),
            "central_conflict": _clip_text(story_plan.get("central_conflict"), 420),
            "central_question": _clip_text(story_plan.get("central_question"), 420),
            "opening_scene_intent": _clip_text(story_plan.get("opening_scene_intent"), 420),
            "current_story_position": _clip_text(story_plan.get("current_story_position"), 500),
            "active_act": _clip_list(story_plan.get("act_structure", [])[:1], 1, 360),
            "relationship_focus": _clip_list(story_plan.get("relationship_focus", []), 4, 220),
            "character_arcs": _compact_dict(story_plan.get("character_arcs", {}), 360),
            "open_threads": _clip_list(story_plan.get("open_threads", []), 6, 180),
            "forbidden_drift": _clip_list(story_plan.get("forbidden_drift", []), 8, 180),
        },
        "npc_runtime": _focused_npc_runtime(characters, npc_state if isinstance(npc_state, dict) else {}, focus_ids, player_id),
        "status_slots": status_slots[:2] if isinstance(status_slots, list) else [],
        "recent_scene_history": recent_scene_history,
        "memory_chunks": memory_chunks,
        "future_locks": {
            "do_not_reveal_yet": _clip_list(future_locks.get("do_not_reveal_yet", []), 4, 160),
            "hidden_character_seeds": _clip_list(future_locks.get("hidden_character_seeds", []), 4, 160),
        },
        "continuity": _compact_continuity(continuity),
        "maintenance": {
            "state_recovery_audit_due": turn_number > 0 and turn_number % 10 == 0,
            "state_compaction_cleanup_due": turn_number > 0 and turn_number % 15 == 0,
            "continuity_check_required": turn_number > 0 and turn_number % 10 == 0,
            "memory_review_required": turn_number > 0 and turn_number % 15 == 0,
            "memory_chunk_count": len(memory_chunks),
        },
        "player_input_rules": {
            "outside_parentheses": "spoken dialogue by the player character",
            "inside_parentheses": "action/thought/pause/remark, not spoken unless explicit quoted speech",
            "preserve_order": "dialogue/action/dialogue order from player input must be preserved",
            "important_answer_must_remain_player_choice": True,
            "player_agency_scope": "protect player character choices only; NPC goals and actions remain independent",
        },
        "output_requirements": {
            "response_schema": "schemas/scene_response.schema.json",
            "state_update_mode": "propose_patch_only",
            "if_prompt_chunked": "read all chunks in order before writing scene_response",
        },
    }
