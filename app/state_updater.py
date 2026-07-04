from typing import Any
from app.id_utils import now_iso
from app.storage import JsonStorage


def _append_unique(target: list[Any], items: list[Any]) -> list[Any]:
    result = list(target)
    for item in items or []:
        if item not in result:
            result.append(item)
    return result


def _append_many(target: list[Any], items: list[Any]) -> list[Any]:
    result = list(target or [])
    result.extend(items or [])
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

        bundle = self.storage.read_session_bundle(session_id)
        current_state = bundle.get("current_state", {})
        relationships = bundle.get("relationships", {})
        knowledge = bundle.get("knowledge", {})
        characters = bundle.get("characters", {})
        scene_history = bundle.get("scene_history", []) or []
        turns = bundle.get("turns", []) or []

        updates = scene_response.get("proposed_updates", {})
        scene_state_patch = updates.get("scene_state_patch", {})

        # Current state patch.
        for key in ["date", "time", "location", "weather", "scene_state", "outfit", "inventory", "nearby_items", "scene_goal", "active_character_ids", "nearby_character_ids", "environment", "status"]:
            if key in scene_state_patch:
                current_state[key] = scene_state_patch[key]
                applied["current_state"].append({"field": key, "operation": "replace"})

        current_state["turn_number"] = int(current_state.get("turn_number", 0)) + 1
        current_state["last_player_input"] = scene_response.get("player_input", current_state.get("last_player_input", ""))
        turn_number = current_state["turn_number"]

        # Relationship patches: one runtime file per pair_id.
        for patch in updates.get("relationship_patches", []) or []:
            pid = patch.get("pair_id")
            if not pid:
                rejected.append({"target": "relationships", "reason": "missing pair_id", "severity": "error"})
                continue
            if not patch.get("source_in_scene") or not patch.get("reason"):
                rejected.append({"target": f"relationships.{pid}", "reason": "relationship patch requires reason and source_in_scene", "severity": "error"})
                continue

            base = relationships.setdefault(pid, {"pair_id": pid, "scores": {}, "history": [], "recent_changes": [], "open_threads": []})
            base.setdefault("pair_id", pid)
            base.setdefault("scores", {})
            base.setdefault("history", [])
            base.setdefault("recent_changes", [])
            base.setdefault("open_threads", [])

            change_entry = {
                "turn": turn_number,
                "entry": patch.get("entry"),
                "change_type": patch.get("change_type"),
                "reason": patch.get("reason"),
                "source_in_scene": patch.get("source_in_scene"),
                "trigger_source": patch.get("trigger_source"),
            }
            base["history"].append(change_entry)
            base["recent_changes"].append(change_entry)
            base["recent_changes"] = base["recent_changes"][-10:]

            for score_key in ["trust", "tension", "attachment", "respect", "fear", "curiosity"]:
                if score_key in patch:
                    # Preserve legacy top-level scores and also maintain v8 scores object.
                    base[score_key] = patch[score_key]
                    base["scores"][score_key] = patch[score_key]

            if isinstance(patch.get("scores"), dict):
                base["scores"].update(patch["scores"])

            for view_key in ["a_view_of_b", "b_view_of_a"]:
                if isinstance(patch.get(view_key), dict):
                    base.setdefault(view_key, {})
                    base[view_key].update(patch[view_key])

            if patch.get("open_threads"):
                base["open_threads"] = _append_unique(base.get("open_threads", []), patch["open_threads"])

            relationships[pid] = base
            self.storage.write_relationship_pair(session_id, pid, base)
            applied["relationships"].append({"pair_id": pid, "operation": "patch_pair_file"})

        # Knowledge patches: one runtime file per character_id.
        for patch in updates.get("knowledge_patches", []) or []:
            character_id = patch.get("character_id")
            if not character_id:
                rejected.append({"target": "knowledge", "reason": "missing character_id", "severity": "error"})
                continue
            if not patch.get("source_in_scene") or not patch.get("reason"):
                rejected.append({"target": f"knowledge.{character_id}", "reason": "knowledge patch requires reason and source_in_scene", "severity": "error"})
                continue

            base = knowledge.setdefault(character_id, {
                "character_id": character_id,
                "known_facts": [],
                "observations": [],
                "assumptions": [],
                "wrong_beliefs": [],
                "does_not_know": [],
                "must_not_assume": [],
                "recent_memories": [],
                "open_questions": [],
                # legacy compatibility
                "knows": [],
                "history": [],
            })
            base.setdefault("character_id", character_id)
            base.setdefault("known_facts", [])
            base.setdefault("observations", [])
            base.setdefault("assumptions", [])
            base.setdefault("wrong_beliefs", [])
            base.setdefault("does_not_know", [])
            base.setdefault("must_not_assume", [])
            base.setdefault("recent_memories", [])
            base.setdefault("open_questions", [])
            base.setdefault("knows", [])
            base.setdefault("history", [])

            if patch.get("add_knows"):
                base["knows"] = _append_unique(base.get("knows", []), patch["add_knows"])
                for fact in patch["add_knows"]:
                    base["known_facts"].append({
                        "text": fact,
                        "source_type": patch.get("source_type", "scene"),
                        "source_in_scene": patch.get("source_in_scene"),
                        "turn": turn_number,
                        "certainty": patch.get("certainty", "medium"),
                    })

            if patch.get("add_known_facts"):
                base["known_facts"] = _append_many(base.get("known_facts", []), patch["add_known_facts"])

            if patch.get("add_observations"):
                observations = []
                for item in patch["add_observations"]:
                    if isinstance(item, dict):
                        observations.append({**item, "turn": item.get("turn", turn_number), "source_in_scene": item.get("source_in_scene") or patch.get("source_in_scene")})
                    else:
                        observations.append({"turn": turn_number, "saw": str(item), "source_in_scene": patch.get("source_in_scene")})
                base["observations"] = _append_many(base.get("observations", []), observations)

            if patch.get("add_assumptions"):
                assumptions = []
                for item in patch["add_assumptions"]:
                    if isinstance(item, dict):
                        assumptions.append({**item, "turn": item.get("turn", turn_number), "may_be_wrong": item.get("may_be_wrong", True)})
                    else:
                        assumptions.append({"text": str(item), "based_on": patch.get("source_in_scene"), "turn": turn_number, "may_be_wrong": True})
                base["assumptions"] = _append_many(base.get("assumptions", []), assumptions)

            if patch.get("add_wrong_beliefs"):
                base["wrong_beliefs"] = _append_many(base.get("wrong_beliefs", []), patch["add_wrong_beliefs"])
            if patch.get("add_recent_memories"):
                base["recent_memories"] = _append_unique(base.get("recent_memories", []), patch["add_recent_memories"])[-10:]
            if patch.get("add_open_questions"):
                base["open_questions"] = _append_unique(base.get("open_questions", []), patch["add_open_questions"])
            if patch.get("remove_does_not_know"):
                base["does_not_know"] = [x for x in base.get("does_not_know", []) if x not in patch["remove_does_not_know"]]

            base["history"].append({
                "turn": turn_number,
                "reason": patch.get("reason"),
                "source_in_scene": patch.get("source_in_scene"),
                "add_knows": patch.get("add_knows", []),
                "add_observations": patch.get("add_observations", []),
                "add_assumptions": patch.get("add_assumptions", []),
            })
            base["history"] = base["history"][-20:]

            knowledge[character_id] = base
            self.storage.write_character_knowledge(session_id, character_id, base)
            applied["knowledge"].append({"character_id": character_id, "operation": "patch_character_knowledge_file"})

        # New or updated characters: one runtime card per generated character id.
        immutable_locked_fields = {"name", "age", "appearance", "personality", "past_short", "role", "goal", "habits", "likes_in_people", "dislikes_in_people", "relationship_triggers"}
        allowed_locked_runtime_fields = {"id", "introduced", "known_to_player", "last_seen", "current_mood", "temporary_state", "scene_notes", "connections", "locked"}
        for patch in updates.get("new_or_updated_characters", []) or []:
            character_id = patch.get("id")
            if not character_id:
                rejected.append({"target": "characters", "reason": "missing id", "severity": "error"})
                continue
            existing = characters.get(character_id, {})
            if existing.get("locked"):
                changed_immutable = [field for field in immutable_locked_fields if field in patch and patch.get(field) != existing.get(field)]
                if changed_immutable:
                    rejected.append({
                        "target": f"characters.{character_id}",
                        "reason": f"locked character card immutable fields cannot be changed: {changed_immutable}",
                        "severity": "error",
                    })
                    continue
                runtime_patch = {key: value for key, value in patch.items() if key in allowed_locked_runtime_fields}
                characters[character_id] = {**existing, **runtime_patch, "locked": True}
                self.storage.write_character(session_id, character_id, characters[character_id])
                applied["characters"].append({"character_id": character_id, "operation": "runtime_patch_locked_card_file"})
                continue
            characters[character_id] = {**existing, **patch, "locked": patch.get("locked", True)}
            self.storage.write_character(session_id, character_id, characters[character_id])
            # Ensure every significant new character starts with a knowledge file.
            if character_id not in knowledge:
                self.storage.write_character_knowledge(session_id, character_id, {"character_id": character_id, "known_facts": [], "observations": [], "assumptions": [], "wrong_beliefs": [], "does_not_know": [], "must_not_assume": [], "recent_memories": [], "open_questions": [], "knows": [], "history": []})
            applied["characters"].append({"character_id": character_id, "operation": "upsert_card_file"})

        # Scene history.
        scene = scene_response.get("scene", {})
        history_entry = {
            "turn": turn_number,
            "summary": scene_response.get("summary", ""),
            "visible_scene_text": scene.get("rendered_text") or scene.get("body", ""),
            "important_facts": scene_response.get("important_facts", []),
            "witnesses": scene_response.get("witnesses", current_state.get("active_character_ids", [])),
            "created_at": now_iso(),
        }
        scene_history.append(history_entry)
        applied["scene_history"].append({"operation": "append", "turn": turn_number})

        turns.append({
            "turn": turn_number,
            "player_input": scene_response.get("player_input", ""),
            "scene_response": scene_response,
            "created_at": now_iso(),
        })
        applied["turns"].append({"operation": "append", "turn": turn_number})

        self.storage.write_json(session_id, "current_state.json", current_state)
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
