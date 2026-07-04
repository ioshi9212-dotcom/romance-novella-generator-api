from typing import Any
from app.id_utils import pair_id


def _get_character(characters: dict[str, Any], character_id: str) -> dict[str, Any] | None:
    character = characters.get(character_id)
    if isinstance(character, dict):
        return character
    return None


def _knowledge_boundary(knowledge: dict[str, Any], character_id: str) -> dict[str, Any]:
    entry = knowledge.get(character_id, {})
    return {
        "character_id": character_id,
        "known": entry.get("knows", []),
        "unknown": entry.get("does_not_know", []),
        "must_not_assume": entry.get("must_not_assume", []),
    }


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
    pov_id = current_state.get("pov_character_id") or "protagonist"

    focus_ids = []
    for cid in [pov_id, *active_ids, *nearby_ids]:
        if cid and cid not in focus_ids:
            focus_ids.append(cid)

    loaded_characters = []
    for cid in focus_ids:
        card = _get_character(characters, cid)
        if not card:
            continue
        loaded_characters.append({
            "character_id": cid,
            "display_name": card.get("name", cid),
            "load_reason": ["pov"] if cid == pov_id else ["physically_present"],
            "card": card,
        })

    loaded_relationships = []
    for i, a in enumerate(focus_ids):
        for b in focus_ids[i + 1:]:
            pid = pair_id(a, b)
            if pid in relationships:
                loaded_relationships.append({
                    "pair_id": pid,
                    "load_reason": ["both_present"],
                    "content": relationships[pid],
                })

    boundaries = [_knowledge_boundary(knowledge, cid) for cid in focus_ids if cid in knowledge]

    return {
        "contract_version": "novella.scene_contract.v1",
        "session_id": bundle.get("session", {}).get("session_id"),
        "current_frame": {
            "pov_character_id": pov_id,
            "date": current_state.get("date"),
            "time": current_state.get("time"),
            "location": current_state.get("location"),
            "scene_goal": current_state.get("scene_goal"),
            "last_player_input": player_input if player_input is not None else current_state.get("last_player_input", ""),
            "active_character_ids": active_ids,
            "nearby_character_ids": nearby_ids,
            "environment": current_state.get("environment", {}),
        },
        "loaded_characters": loaded_characters,
        "loaded_relationships": loaded_relationships,
        "knowledge_boundaries": boundaries,
        "story_compass": {
            "genre": story_plan.get("genre"),
            "tone": story_plan.get("tone"),
            "current_story_position": story_plan.get("current_story_position"),
            "active_act": story_plan.get("act_structure", [])[:1],
            "forbidden_drift": story_plan.get("forbidden_drift", []),
        },
        "recent_scene_history": scene_history[-5:] if isinstance(scene_history, list) else [],
        "future_locks": {
            "do_not_reveal_yet": future_locks.get("do_not_reveal_yet", []),
            "hidden_character_seeds": future_locks.get("hidden_character_seeds", []),
        },
        "continuity": continuity,
        "output_requirements": {
            "response_schema": "schemas/scene_response.schema.json",
            "state_update_mode": "propose_patch_only",
            "rules": [
                "Не делать важный выбор за игрока.",
                "Не менять locked-анкету персонажа через сцену.",
                "NPC знает только то, что есть в knowledge/scene/relationship.",
                "Новые важные NPC сохраняются через proposed_updates.new_or_updated_characters.",
            ],
        },
    }
