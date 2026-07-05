from typing import Any
from app.id_utils import pair_id


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
    return {"character_id": character_id, "known": entry.get("knows", []), "known_facts": entry.get("known_facts", []), "observations": entry.get("observations", [])[-10:], "assumptions": entry.get("assumptions", [])[-10:], "wrong_beliefs": entry.get("wrong_beliefs", [])[-10:], "recent_memories": entry.get("recent_memories", [])[-10:], "open_questions": entry.get("open_questions", []), "unknown": entry.get("does_not_know", []), "must_not_assume": entry.get("must_not_assume", [])}


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
    return {"contract_version": "novella.scene_contract.v1", "session_id": bundle.get("session", {}).get("session_id"), "current_frame": {"player_character_id": player_id, "player_display_name": _display_name(characters, player_id), "date": current_state.get("date"), "time": current_state.get("time"), "location": current_state.get("location"), "weather": current_state.get("weather", ""), "scene_state": current_state.get("scene_state", ""), "outfit": current_state.get("outfit", ""), "inventory": current_state.get("inventory", []), "nearby_items": current_state.get("nearby_items", []), "scene_goal": current_state.get("scene_goal"), "last_player_input": player_input if player_input is not None else current_state.get("last_player_input", ""), "active_character_ids": active_ids, "active_character_display_names": [_display_name(characters, cid) for cid in active_ids], "nearby_character_ids": nearby_ids, "environment": current_state.get("environment", {}), "status": status}, "loaded_characters": loaded_characters, "loaded_relationships": loaded_relationships, "visible_relationship_pair_ids": visible_relationship_pair_ids, "knowledge_boundaries": [_knowledge_boundary(knowledge, cid) for cid in focus_ids if cid in knowledge], "story_compass": {"genre": story_plan.get("genre"), "tone": story_plan.get("tone"), "current_story_position": story_plan.get("current_story_position"), "active_act": story_plan.get("act_structure", [])[:1], "forbidden_drift": story_plan.get("forbidden_drift", [])}, "status_slots": status_slots[:2] if isinstance(status_slots, list) else [], "recent_scene_history": scene_history[-5:] if isinstance(scene_history, list) else [], "future_locks": {"do_not_reveal_yet": future_locks.get("do_not_reveal_yet", []), "hidden_character_seeds": future_locks.get("hidden_character_seeds", [])}, "continuity": continuity, "maintenance": {"continuity_check_required": turn_number > 0 and turn_number % 10 == 0, "memory_review_required": turn_number > 0 and turn_number % 15 == 0}, "player_input_rules": {"outside_parentheses": "spoken dialogue by the player character", "inside_parentheses": "action/thought/pause/remark, not spoken unless explicit quoted speech", "preserve_order": "dialogue/action/dialogue order from player input must be preserved", "important_answer_must_remain_player_choice": True}, "output_requirements": {"response_schema": "schemas/scene_response.schema.json", "state_update_mode": "propose_patch_only"}}
