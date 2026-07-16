from typing import Any
from app.id_utils import now_iso
from app.storage import JsonStorage


MAX_RECENT_SCENE_HISTORY = 6
MAX_RECENT_TURNS = 8
MAX_MEMORY_CHUNKS = 12
MAX_ARCHIVED_SCENE_SUMMARIES = 120
MAX_ARCHIVED_TURN_SUMMARIES = 160


def _append_unique(target: list[Any], items: list[Any]) -> list[Any]:
    result = list(target or [])
    for item in items or []:
        if item not in result:
            result.append(item)
    return result


def _append_many(target: list[Any], items: list[Any]) -> list[Any]:
    result = list(target or [])
    result.extend(items or [])
    return result


def _clip_text(value: Any, limit: int = 500) -> str:
    text = "" if value is None else str(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


def _clip_list(items: Any, limit_items: int = 6, text_limit: int = 220) -> list[Any]:
    if not isinstance(items, list):
        return []
    out: list[Any] = []
    for item in items[:limit_items]:
        if isinstance(item, str):
            out.append(_clip_text(item, text_limit))
        elif isinstance(item, dict):
            out.append({str(k): _clip_text(v, text_limit) if isinstance(v, str) else v for k, v in item.items()})
        else:
            out.append(item)
    return out


def _scene_body_excerpt(scene_response: dict[str, Any], limit: int = 700) -> str:
    scene = scene_response.get("scene") if isinstance(scene_response, dict) else {}
    if not isinstance(scene, dict):
        scene = {}
    body = scene.get("body") or ""
    if not body and isinstance(scene.get("rendered_text"), str):
        body = scene.get("rendered_text", "")
    return _clip_text(body, limit)


def _compact_scene_history_entry(entry: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(entry, dict):
        return {}
    # Legacy entries may contain full visible_scene_text. Never keep it in runtime context.
    return {
        "turn": entry.get("turn"),
        "summary": _clip_text(entry.get("summary", ""), 500),
        "important_facts": _clip_list(entry.get("important_facts", []), 6, 220),
        "witnesses": _clip_list(entry.get("witnesses", []), 8, 80),
        "body_excerpt": _clip_text(entry.get("body_excerpt") or entry.get("visible_scene_excerpt") or entry.get("visible_scene_text") or "", 650),
        "created_at": entry.get("created_at"),
    }


def _compact_turn_entry(entry: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(entry, dict):
        return {}
    scene_response = entry.get("scene_response") if isinstance(entry.get("scene_response"), dict) else {}
    return {
        "turn": entry.get("turn"),
        "player_input": _clip_text(entry.get("player_input") or scene_response.get("player_input") or "", 350),
        "summary": _clip_text(entry.get("summary") or scene_response.get("summary") or "", 450),
        "important_facts": _clip_list(entry.get("important_facts") or scene_response.get("important_facts") or [], 5, 180),
        "witnesses": _clip_list(entry.get("witnesses") or scene_response.get("witnesses") or [], 8, 80),
        "created_at": entry.get("created_at"),
    }


def _make_memory_chunk(kind: str, scenes: list[dict[str, Any]], turns: list[dict[str, Any]], turn_number: int) -> dict[str, Any] | None:
    scene_items = [_compact_scene_history_entry(item) for item in scenes if isinstance(item, dict)]
    turn_items = [_compact_turn_entry(item) for item in turns if isinstance(item, dict)]
    if not scene_items and not turn_items:
        return None
    turn_values = [item.get("turn") for item in [*scene_items, *turn_items] if item.get("turn") is not None]
    start = min(turn_values) if turn_values else None
    end = max(turn_values) if turn_values else turn_number
    return {
        "chunk_id": f"{kind}_{start or 'x'}_{end or turn_number}",
        "type": kind,
        "turn_start": start,
        "turn_end": end,
        "created_at": now_iso(),
        "scene_summaries": [
            {
                "turn": item.get("turn"),
                "summary": item.get("summary", ""),
                "important_facts": item.get("important_facts", []),
                "witnesses": item.get("witnesses", []),
            }
            for item in scene_items
        ],
        "turn_summaries": [
            {
                "turn": item.get("turn"),
                "player_input": item.get("player_input", ""),
                "summary": item.get("summary", ""),
            }
            for item in turn_items
        ],
    }



def _dedupe_summary_items(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[Any, str]] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        key = (item.get("turn"), str(item.get("summary") or item.get("player_input") or ""))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result[-limit:]


def _merge_memory_chunks(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    scene_summaries = _dedupe_summary_items(
        [*(left.get("scene_summaries") or []), *(right.get("scene_summaries") or [])],
        MAX_ARCHIVED_SCENE_SUMMARIES,
    )
    turn_summaries = _dedupe_summary_items(
        [*(left.get("turn_summaries") or []), *(right.get("turn_summaries") or [])],
        MAX_ARCHIVED_TURN_SUMMARIES,
    )
    starts = [value for value in (left.get("turn_start"), right.get("turn_start")) if isinstance(value, int)]
    ends = [value for value in (left.get("turn_end"), right.get("turn_end")) if isinstance(value, int)]
    start = min(starts) if starts else None
    end = max(ends) if ends else None
    return {
        "chunk_id": f"long_term_archive_{start or 'x'}_{end or 'x'}",
        "type": "long_term_archive",
        "turn_start": start,
        "turn_end": end,
        "created_at": now_iso(),
        "scene_summaries": scene_summaries,
        "turn_summaries": turn_summaries,
        "merged_chunk_ids": [
            item for item in [left.get("chunk_id"), right.get("chunk_id")] if item
        ],
    }


def _append_memory_chunk(continuity: dict[str, Any], chunk: dict[str, Any] | None) -> bool:
    if not chunk:
        return False
    continuity.setdefault("memory_chunks", [])
    existing_ids = {item.get("chunk_id") for item in continuity["memory_chunks"] if isinstance(item, dict)}
    if chunk.get("chunk_id") not in existing_ids:
        continuity["memory_chunks"].append(chunk)
    chunks = [item for item in continuity.get("memory_chunks", []) if isinstance(item, dict)]
    while len(chunks) > MAX_MEMORY_CHUNKS:
        chunks = [_merge_memory_chunks(chunks[0], chunks[1]), *chunks[2:]]
    continuity["memory_chunks"] = chunks
    return True


def _trim_continuity(continuity: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(continuity, dict):
        continuity = {}
    for key in ("open_threads", "notes", "warnings"):
        if isinstance(continuity.get(key), list):
            continuity[key] = _clip_list(continuity[key], 16, 260)
    continuity["memory_chunks"] = [
        chunk for chunk in (continuity.get("memory_chunks", []) or []) if isinstance(chunk, dict)
    ][-MAX_MEMORY_CHUNKS:]
    continuity["memory_compacts"] = [
        item for item in (continuity.get("memory_compacts", []) or []) if isinstance(item, dict)
    ][-6:]
    continuity["turn_archives"] = [
        item for item in (continuity.get("turn_archives", []) or []) if isinstance(item, dict)
    ][-6:]
    continuity["maintenance_events"] = [
        item for item in (continuity.get("maintenance_events", []) or []) if isinstance(item, dict)
    ][-12:]
    continuity["persistence_audits"] = [
        item for item in (continuity.get("persistence_audits", []) or []) if isinstance(item, dict)
    ][-12:]
    return continuity



def _merge_status_patch(current_status: dict[str, Any], patch_status: Any) -> dict[str, Any]:
    """Merge status instead of replacing it; status is persistent gameplay state."""
    if not isinstance(current_status, dict):
        current_status = {}
    if not isinstance(patch_status, dict):
        return current_status
    merged = dict(current_status)
    for key, value in patch_status.items():
        if key == "custom" and isinstance(value, list):
            existing_custom = merged.get("custom") if isinstance(merged.get("custom"), list) else []
            new_custom = list(existing_custom)
            for index, item in enumerate(value[:2]):
                if not isinstance(item, dict):
                    continue
                while len(new_custom) <= index:
                    new_custom.append({})
                base = new_custom[index] if isinstance(new_custom[index], dict) else {}
                new_custom[index] = {**base, **item}
            merged["custom"] = new_custom
        else:
            merged[key] = value
    return merged


def _bounded_score_update(old_value: Any, new_value: Any, *, major_shift: bool = False) -> int | None:
    try:
        new_int = max(0, min(100, int(float(new_value))))
    except Exception:
        return None
    try:
        old_int = max(0, min(100, int(float(old_value))))
    except Exception:
        return new_int
    max_delta = 15 if major_shift else 8
    if new_int > old_int + max_delta:
        return old_int + max_delta
    if new_int < old_int - max_delta:
        return old_int - max_delta
    return new_int

def _merge_continuity_patch(continuity: dict[str, Any], patch: dict[str, Any], turn_number: int) -> dict[str, Any]:
    if not isinstance(patch, dict):
        return continuity

    continuity.setdefault("open_threads", [])
    continuity.setdefault("notes", [])
    continuity.setdefault("warnings", [])

    for key in ["open_threads", "notes", "warnings"]:
        if isinstance(patch.get(key), list):
            continuity[key] = _append_unique(continuity.get(key, []), patch[key])

    if isinstance(patch.get("memory_compact"), dict):
        continuity.setdefault("gpt_memory_compacts", [])
        continuity["gpt_memory_compacts"].append({**patch["memory_compact"], "turn": turn_number, "created_at": now_iso()})
        continuity["gpt_memory_compacts"] = continuity["gpt_memory_compacts"][-8:]

    for key in ["current_arc", "current_act", "last_continuity_check"]:
        if key in patch:
            continuity[key] = patch[key]

    return _trim_continuity(continuity)


def _auto_compact_runtime_history(
    scene_history: list[dict[str, Any]],
    turns: list[dict[str, Any]],
    continuity: dict[str, Any],
    turn_number: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], bool]:
    """Keep Action payload small.

    Every apply sanitizes legacy full-scene entries. At 10 turns we mark a recovery
    audit window; at 15 turns we compact stale history into memory_chunks. Old
    verbatim scenes and full scene_response payloads must not remain in runtime
    context, because processTurn can otherwise exceed Custom GPT Action limits.
    """
    compacted = False
    continuity = _trim_continuity(continuity)

    scene_history = [_compact_scene_history_entry(item) for item in (scene_history or []) if isinstance(item, dict)]
    turns = [_compact_turn_entry(item) for item in (turns or []) if isinstance(item, dict)]

    old_scenes = scene_history[:-MAX_RECENT_SCENE_HISTORY]
    old_turns = turns[:-MAX_RECENT_TURNS]
    if old_scenes or old_turns:
        kind = "state_compaction_cleanup" if turn_number > 0 and turn_number % 15 == 0 else "rolling_runtime_compaction"
        compacted = _append_memory_chunk(continuity, _make_memory_chunk(kind, old_scenes, old_turns, turn_number)) or compacted
        scene_history = scene_history[-MAX_RECENT_SCENE_HISTORY:]
        turns = turns[-MAX_RECENT_TURNS:]

    continuity.setdefault("maintenance_events", [])
    if turn_number > 0 and turn_number % 10 == 0:
        continuity["maintenance_events"].append({
            "turn": turn_number,
            "type": "state_recovery_audit",
            "created_at": now_iso(),
            "note": "Review recent scene summaries/knowledge patches for missed durable facts.",
        })
    if turn_number > 0 and turn_number % 15 == 0:
        continuity["maintenance_events"].append({
            "turn": turn_number,
            "type": "state_compaction_cleanup",
            "created_at": now_iso(),
            "note": "Compact stale scene/turn details into memory_chunks; keep hooks, sources, relationship changes.",
        })
        compacted = True

    continuity = _trim_continuity(continuity)
    return scene_history, turns, continuity, compacted


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
            "maintenance": [],
        }
        rejected: list[dict[str, Any]] = []

        bundle = self.storage.read_session_bundle(session_id)
        current_state = self.storage.read_json(session_id, "current_state.json", default=bundle.get("current_state", {}))
        relationships = bundle.get("relationships", {})
        knowledge = bundle.get("knowledge", {})
        characters = bundle.get("characters", {})
        scene_history = self.storage.read_json(session_id, "scene_history.json", default=[]) or []
        turns = self.storage.read_json(session_id, "turns.json", default=[]) or []
        continuity = self.storage.read_json(session_id, "continuity.json", default={}) or {}

        updates = scene_response.get("proposed_updates", {})
        scene_state_patch = updates.get("scene_state_patch", {})

        for key in ["date", "time", "location", "weather", "scene_state", "outfit", "inventory", "nearby_items", "scene_goal", "active_character_ids", "nearby_character_ids", "environment", "time_skip_control"]:
            if key in scene_state_patch:
                current_state[key] = scene_state_patch[key]
                applied["current_state"].append({"field": key, "operation": "replace"})

        if "status" in scene_state_patch:
            current_state["status"] = _merge_status_patch(current_state.get("status", {}), scene_state_patch.get("status"))
            applied["current_state"].append({"field": "status", "operation": "merge"})

        current_state["turn_number"] = int(current_state.get("turn_number", 0) or 0) + 1
        current_state["last_player_input"] = scene_response.get("player_input", current_state.get("last_player_input", ""))
        turn_number = current_state["turn_number"]

        if isinstance(updates.get("continuity_patch"), dict):
            continuity = _merge_continuity_patch(continuity, updates["continuity_patch"], turn_number)
            applied["maintenance"].append({"operation": "merge_continuity_patch", "turn": turn_number})

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

            major_shift = bool(patch.get("major_shift"))
            for score_key in ["overall", "trust", "tension", "attachment", "respect", "fear", "curiosity", "romantic_interest", "presence_pull"]:
                if score_key in patch:
                    bounded = _bounded_score_update(base["scores"].get(score_key, base.get(score_key)), patch[score_key], major_shift=major_shift)
                    if bounded is not None:
                        base[score_key] = bounded
                        base["scores"][score_key] = bounded
            if isinstance(patch.get("scores"), dict):
                for score_key, score_value in patch["scores"].items():
                    bounded = _bounded_score_update(base["scores"].get(score_key, base.get(score_key)), score_value, major_shift=major_shift)
                    if bounded is not None:
                        base["scores"][score_key] = bounded
            for view_key in ["a_view_of_b", "b_view_of_a"]:
                if isinstance(patch.get(view_key), dict):
                    base.setdefault(view_key, {})
                    base[view_key].update(patch[view_key])
            if patch.get("open_threads"):
                base["open_threads"] = _append_unique(base.get("open_threads", []), patch["open_threads"])

            relationships[pid] = base
            self.storage.write_relationship_pair(session_id, pid, base)
            applied["relationships"].append({"pair_id": pid, "operation": "patch_pair_file"})

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
                "knows": [],
                "history": [],
            })
            for key in ["known_facts", "observations", "assumptions", "wrong_beliefs", "does_not_know", "must_not_assume", "recent_memories", "open_questions", "knows", "history"]:
                base.setdefault(key, [])
            base.setdefault("character_id", character_id)

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
                    rejected.append({"target": f"characters.{character_id}", "reason": f"locked character card immutable fields cannot be changed: {changed_immutable}", "severity": "error"})
                    continue
                runtime_patch = {key: value for key, value in patch.items() if key in allowed_locked_runtime_fields}
                characters[character_id] = {**existing, **runtime_patch, "locked": True}
                self.storage.write_character(session_id, character_id, characters[character_id])
                applied["characters"].append({"character_id": character_id, "operation": "runtime_patch_locked_card_file"})
                continue
            characters[character_id] = {**existing, **patch, "locked": patch.get("locked", True)}
            self.storage.write_character(session_id, character_id, characters[character_id])
            if character_id not in knowledge:
                self.storage.write_character_knowledge(session_id, character_id, {"character_id": character_id, "known_facts": [], "observations": [], "assumptions": [], "wrong_beliefs": [], "does_not_know": [], "must_not_assume": [], "recent_memories": [], "open_questions": [], "knows": [], "history": []})
            applied["characters"].append({"character_id": character_id, "operation": "upsert_card_file"})

        history_entry = _compact_scene_history_entry({
            "turn": turn_number,
            "summary": scene_response.get("summary", ""),
            "body_excerpt": _scene_body_excerpt(scene_response, 700),
            "important_facts": scene_response.get("important_facts", []),
            "witnesses": scene_response.get("witnesses", current_state.get("active_character_ids", [])),
            "created_at": now_iso(),
        })
        scene_history.append(history_entry)
        applied["scene_history"].append({"operation": "append_compact", "turn": turn_number})

        turns.append(_compact_turn_entry({
            "turn": turn_number,
            "player_input": scene_response.get("player_input", ""),
            "summary": scene_response.get("summary", ""),
            "important_facts": scene_response.get("important_facts", []),
            "witnesses": scene_response.get("witnesses", []),
            "created_at": now_iso(),
        }))
        applied["turns"].append({"operation": "append_compact", "turn": turn_number})

        scene_history, turns, continuity, compacted = _auto_compact_runtime_history(scene_history, turns, continuity, turn_number)
        maintenance = {
            "last_saved_turn_number": turn_number,
            "state_recovery_audit_due": turn_number > 0 and turn_number % 10 == 0,
            "state_compaction_cleanup_due": turn_number > 0 and turn_number % 15 == 0,
            "continuity_check_required_next": turn_number > 0 and turn_number % 10 == 0,
            "memory_review_required_next": turn_number > 0 and turn_number % 15 == 0,
            "backend_compacted_after_turn": turn_number if compacted else (current_state.get("maintenance") or {}).get("backend_compacted_after_turn"),
            "last_compact_turn": turn_number if compacted else (current_state.get("maintenance") or {}).get("last_compact_turn"),
            "memory_chunk_count": len(continuity.get("memory_chunks", []) or []),
            "recent_scene_history_kept": len(scene_history),
            "recent_turns_kept": len(turns),
            "notes": [],
        }
        current_state["maintenance"] = maintenance
        applied["maintenance"].append({"operation": "update_flags", "turn": turn_number, "compacted": compacted})

        self.storage.write_json(session_id, "current_state.json", current_state)
        self.storage.write_json(session_id, "scene_history.json", scene_history)
        self.storage.write_json(session_id, "turns.json", turns)
        self.storage.write_json(session_id, "continuity.json", continuity)

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
                "maintenance": maintenance,
            },
        }
