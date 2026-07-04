from typing import Any
from app.id_utils import now_iso
from app.storage import JsonStorage


def _append_unique(target: list[Any], items: list[Any]) -> list[Any]:
    result = list(target)
    for item in items:
        if item not in result:
            result.append(item)
    return result


class StateUpdater:
    def __init__(self, storage: JsonStorage):
        self.storage = storage

    def apply_scene_response(self, session_id: str, scene_response: dict[str, Any]) -> dict[str, Any]:
        applied = {
            "current_state": [],
            "relationships": [],
            "knowledge": [],
            "characters": [],
            "scene_history": [],
            "turns": [],
        }
        rejected: list[dict[str, Any]] = []

        current_state = self.storage.read_json(session_id, "current_state.json")
        relationships = self.storage.read_json(session_id, "relationships.json")
        knowledge = self.storage.read_json(session_id, "knowledge.json")
        characters = self.storage.read_json(session_id, "characters.json")
        scene_history = self.storage.read_json(session_id, "scene_history.json", default=[])
        turns = self.storage.read_json(session_id, "turns.json", default=[])

        updates = scene_response.get("proposed_updates", {})
        scene_state_patch = updates.get("scene_state_patch", {})

        # Current state patch.
        for key in ["date", "time", "location", "weather", "scene_state", "outfit", "inventory", "nearby_items", "scene_goal", "active_character_ids", "nearby_character_ids", "environment", "status"]:
            if key in scene_state_patch:
                current_state[key] = scene_state_patch[key]
                applied["current_state"].append({"field": key, "operation": "replace"})

        current_state["turn_number"] = int(current_state.get("turn_number", 0)) + 1
        current_state["last_player_input"] = scene_response.get("player_input", current_state.get("last_player_input", ""))

        # Relationship patches.
        for patch in updates.get("relationship_patches", []):
            pair_id = patch.get("pair_id")
            if not pair_id:
                rejected.append({"target": "relationships", "reason": "missing pair_id", "severity": "error"})
                continue
            if not patch.get("source_in_scene") or not patch.get("reason"):
                rejected.append({"target": f"relationships.{pair_id}", "reason": "relationship patch requires reason and source_in_scene", "severity": "error"})
                continue
            base = relationships.setdefault(pair_id, {})
            base.setdefault("history", [])
            base["history"].append({
                "turn": current_state["turn_number"],
                "entry": patch.get("entry"),
                "change_type": patch.get("change_type"),
                "reason": patch.get("reason"),
                "source_in_scene": patch.get("source_in_scene"),
            })
            for score_key in ["trust", "tension", "attachment", "respect", "fear"]:
                if score_key in patch:
                    base[score_key] = patch[score_key]
            applied["relationships"].append({"pair_id": pair_id, "operation": "append_history"})

        # Knowledge patches.
        for patch in updates.get("knowledge_patches", []):
            character_id = patch.get("character_id")
            if not character_id:
                rejected.append({"target": "knowledge", "reason": "missing character_id", "severity": "error"})
                continue
            if not patch.get("source_in_scene") or not patch.get("reason"):
                rejected.append({"target": f"knowledge.{character_id}", "reason": "knowledge patch requires reason and source_in_scene", "severity": "error"})
                continue
            base = knowledge.setdefault(character_id, {"knows": [], "does_not_know": [], "must_not_assume": [], "assumptions": []})
            if patch.get("add_knows"):
                base["knows"] = _append_unique(base.get("knows", []), patch["add_knows"])
            if patch.get("add_assumptions"):
                base["assumptions"] = _append_unique(base.get("assumptions", []), patch["add_assumptions"])
            if patch.get("remove_does_not_know"):
                base["does_not_know"] = [x for x in base.get("does_not_know", []) if x not in patch["remove_does_not_know"]]
            base.setdefault("history", []).append({
                "turn": current_state["turn_number"],
                "reason": patch.get("reason"),
                "source_in_scene": patch.get("source_in_scene"),
                "add_knows": patch.get("add_knows", []),
                "add_assumptions": patch.get("add_assumptions", []),
            })
            applied["knowledge"].append({"character_id": character_id, "operation": "patch"})

        # New or updated characters.
        immutable_locked_fields = {"name", "age", "appearance", "personality", "past_short", "role"}
        allowed_locked_runtime_fields = {"id", "introduced", "known_to_player", "last_seen", "current_mood", "temporary_state", "scene_notes", "connections", "locked"}
        for patch in updates.get("new_or_updated_characters", []):
            character_id = patch.get("id")
            if not character_id:
                rejected.append({"target": "characters", "reason": "missing id", "severity": "error"})
                continue
            existing = characters.get(character_id, {})
            if existing.get("locked"):
                changed_immutable = [field for field in immutable_locked_fields if field in patch and patch.get(field) != existing.get(field)]
                unknown_fields = [field for field in patch if field not in allowed_locked_runtime_fields and field not in immutable_locked_fields]
                if changed_immutable:
                    rejected.append({
                        "target": f"characters.{character_id}",
                        "reason": f"locked character card immutable fields cannot be changed: {changed_immutable}",
                        "severity": "error",
                    })
                    continue
                runtime_patch = {key: value for key, value in patch.items() if key in allowed_locked_runtime_fields}
                characters[character_id] = {**existing, **runtime_patch, "locked": True}
                applied["characters"].append({"character_id": character_id, "operation": "runtime_patch_locked"})
                continue
            characters[character_id] = {**existing, **patch, "locked": patch.get("locked", True)}
            applied["characters"].append({"character_id": character_id, "operation": "upsert"})

        # Scene history.
        scene = scene_response.get("scene", {})
        history_entry = {
            "turn": current_state["turn_number"],
            "summary": scene_response.get("summary", ""),
            "visible_scene_text": scene.get("rendered_text") or scene.get("body", ""),
            "important_facts": scene_response.get("important_facts", []),
            "witnesses": scene_response.get("witnesses", current_state.get("active_character_ids", [])),
            "created_at": now_iso(),
        }
        scene_history.append(history_entry)
        applied["scene_history"].append({"operation": "append", "turn": current_state["turn_number"]})

        turns.append({
            "turn": current_state["turn_number"],
            "player_input": scene_response.get("player_input", ""),
            "scene_response": scene_response,
            "created_at": now_iso(),
        })
        applied["turns"].append({"operation": "append", "turn": current_state["turn_number"]})

        self.storage.write_json(session_id, "current_state.json", current_state)
        self.storage.write_json(session_id, "relationships.json", relationships)
        self.storage.write_json(session_id, "knowledge.json", knowledge)
        self.storage.write_json(session_id, "characters.json", characters)
        self.storage.write_json(session_id, "scene_history.json", scene_history)
        self.storage.write_json(session_id, "turns.json", turns)

        session = self.storage.read_json(session_id, "session.json")
        session["updated_at"] = now_iso()
        self.storage.write_json(session_id, "session.json", session)

        return {
            "status": "applied" if not rejected else "partially_applied",
            "applied": applied,
            "rejected": rejected,
            "next_builder_hints": {
                "active_character_ids": current_state.get("active_character_ids", []),
                "location": current_state.get("location"),
                "repair_required": bool(rejected),
            },
        }
