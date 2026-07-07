from typing import Any
from app.id_utils import pair_id



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
            result.append({str(k): _clip_text(v, text_limit) if isinstance(v, str) else v for k, v in item.items()})
        else:
            result.append(item)
    return result


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
    custom = status.get("custom") or []
    if len(custom) < 2:
        custom = []
        for index in range(2):
            slot = status_slots[index] if index < len(status_slots) else {}
            custom.append({"id": slot.get("id", f"story_slot_{index + 1}"), "label": slot.get("label", f"Поле истории {index + 1}"), "value": slot.get("initial_value", "не задано")})
    return {"hunger": status.get("hunger", "норма"), "fatigue": status.get("fatigue", "низкая"), "injuries": status.get("injuries", []), "emotional_state": status.get("emotional_state", "нейтрально"), "skills": status.get("skills", []), "custom": custom[:2]}


def build_scene_contract(bundle: dict[str, Any], player_input: str | None = None) -> dict[str, Any]:
    current_state = bundle.get("current_state", {})
    characters = bundle.get("characters", {})
    relationships = bundle.get("relationships", {})
    knowledge = bundle.get("knowledge", {})
    story_plan = bundle.get("story_plan", {})
    future_locks = bundle.get("future_locks", {})
    continuity = bundle.get("continuity", {})
    scene_history = bundle.get("scene_history", [])
    active_ids = current_state.get("active_character_ids", []) or []
    nearby_ids = current_state.get("nearby_character_ids", []) or []
    player_id = current_state.get("player_character_id") or current_state.get("player_character_character_id") or "protagonist"
    turn_number = int(current_state.get("turn_number", 0) or 0)
    focus_ids: list[str] = []
    for cid in [player_id, *active_ids, *nearby_ids]:
        if cid and cid not in focus_ids:
            focus_ids.append(cid)
    scene_ids: list[str] = []
    for cid in [player_id, *active_ids]:
        if cid and cid not in scene_ids:
            scene_ids.append(cid)
    loaded_characters = []
    for cid in focus_ids:
        card = _get_character(characters, cid)
        if card:
            load_reason = ["player_character"] if cid == player_id else (["physically_present"] if cid in scene_ids else ["nearby_context"])
            loaded_characters.append({"character_id": cid, "display_name": _display_name(characters, cid), "load_reason": load_reason, "card": card})
    loaded_relationships = []
    visible_relationship_pair_ids: list[str] = []
    for i, a in enumerate(focus_ids):
        for b in focus_ids[i + 1:]:
            pid = pair_id(a, b)
            if pid not in relationships:
                continue
            both_in_scene = a in scene_ids and b in scene_ids
            loaded_relationships.append({"pair_id": pid, "display_label": f"{_display_name(characters, a)} ↔ {_display_name(characters, b)}", "load_reason": ["both_present"] if both_in_scene else ["nearby_context"], "visible_in_footer": both_in_scene, "content": relationships[pid]})
            if both_in_scene:
                visible_relationship_pair_ids.append(pid)
    status = _normalise_status(current_state, story_plan)
    status_slots = story_plan.get("status_slots") or status.get("custom", [])
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
            "active_character_display_names": [_display_name(characters, cid) for cid in active_ids],
            "nearby_character_ids": nearby_ids,
            "environment": current_state.get("environment", {}),
            "status": status,
        },
        "loaded_characters": loaded_characters,
        "loaded_relationships": loaded_relationships,
        "visible_relationship_pair_ids": visible_relationship_pair_ids,
        "knowledge_boundaries": [_knowledge_boundary(knowledge, cid) for cid in focus_ids if cid in knowledge],
        "story_compass": {
            "genre": story_plan.get("genre"),
            "tone": story_plan.get("tone"),
            "current_story_position": _clip_text(story_plan.get("current_story_position"), 500),
            "active_act": _clip_list(story_plan.get("act_structure", [])[:1], 1, 300),
            "forbidden_drift": _clip_list(story_plan.get("forbidden_drift", []), 6, 140),
        },
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
        },
        "output_requirements": {
            "response_schema": "schemas/scene_response.schema.json",
            "state_update_mode": "propose_patch_only",
            "if_prompt_chunked": "read all chunks in order before writing scene_response",
        },
    }
