from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.id_utils import now_iso


FORBIDDEN_RUNTIME_KEYS = {
    "rendered_text",
    "scene_response",
    "player_options",
    "status_panel",
    "relationships_panel",
    "scene_prompt",
    "scene_prompt_chunk",
}


def _contains_forbidden_keys(value: Any, path: str = "root") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{path}.{key}"
            if key in FORBIDDEN_RUNTIME_KEYS:
                found.append(child_path)
            found.extend(_contains_forbidden_keys(item, child_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_contains_forbidden_keys(item, f"{path}[{index}]"))
    return found


def _turns_from_scene_history(scene_history: Any) -> set[int]:
    return {
        int(item.get("turn"))
        for item in (scene_history or [])
        if isinstance(item, dict) and item.get("turn") is not None
    }


def _turns_from_turn_history(turns: Any) -> set[int]:
    return {
        int(item.get("turn"))
        for item in (turns or [])
        if isinstance(item, dict) and item.get("turn") is not None
    }


def _turns_from_memory_chunks(chunks: Any, key: str) -> set[int]:
    result: set[int] = set()
    for chunk in chunks or []:
        if not isinstance(chunk, dict):
            continue
        for item in chunk.get(key, []) or []:
            if isinstance(item, dict) and item.get("turn") is not None:
                result.add(int(item.get("turn")))
    return result


def _history_has_turn(items: Any, turn_number: int) -> bool:
    return any(
        isinstance(item, dict) and int(item.get("turn") or 0) == turn_number
        for item in (items or [])
    )


def _expected_applied_ids(result: dict[str, Any], key: str, id_key: str) -> set[str]:
    applied = result.get("applied") if isinstance(result.get("applied"), dict) else {}
    rows = applied.get(key) if isinstance(applied.get(key), list) else []
    return {
        str(item.get(id_key))
        for item in rows
        if isinstance(item, dict) and item.get(id_key)
    }


def _persisted_relationships(bundle: dict[str, Any], ids: set[str], turn_number: int) -> bool:
    relationships = bundle.get("relationships") if isinstance(bundle.get("relationships"), dict) else {}
    return all(
        isinstance(relationships.get(pair_id), dict)
        and _history_has_turn(relationships[pair_id].get("history"), turn_number)
        for pair_id in ids
    )


def _persisted_knowledge(bundle: dict[str, Any], ids: set[str], turn_number: int) -> bool:
    knowledge = bundle.get("knowledge") if isinstance(bundle.get("knowledge"), dict) else {}
    return all(
        isinstance(knowledge.get(character_id), dict)
        and _history_has_turn(knowledge[character_id].get("history"), turn_number)
        for character_id in ids
    )


def _persisted_npc_state(bundle: dict[str, Any], ids: set[str], turn_number: int) -> bool:
    npc_state = bundle.get("npc_state") if isinstance(bundle.get("npc_state"), dict) else {}
    return all(
        isinstance(npc_state.get(character_id), dict)
        and int(npc_state[character_id].get("last_updated_turn") or 0) == turn_number
        and _history_has_turn(npc_state[character_id].get("history"), turn_number)
        for character_id in ids
    )


def run_persistence_audit(
    storage: Any,
    session_id: str,
    scene_response: dict[str, Any],
    apply_result: dict[str, Any],
) -> dict[str, Any]:
    """Audit real saved files on every 10th/15th turn without blocking the scene.

    The audit checks state, compact history, relationship/knowledge/NPC patches and
    verifies that visible scene payloads were not copied into runtime memory.
    """
    result = deepcopy(apply_result) if isinstance(apply_result, dict) else {}
    current_state = storage.read_json(session_id, "current_state.json", default={})
    turn_number = int((current_state or {}).get("turn_number", 0) or 0)

    triggers: list[str] = []
    if turn_number > 0 and turn_number % 10 == 0:
        triggers.append("state_recovery_audit")
    if turn_number > 0 and turn_number % 15 == 0:
        triggers.append("state_compaction_cleanup")
    if not triggers:
        return result

    bundle = storage.read_session_bundle(session_id)
    current_state = bundle.get("current_state") if isinstance(bundle.get("current_state"), dict) else {}
    scene_history = bundle.get("scene_history") if isinstance(bundle.get("scene_history"), list) else []
    turns = bundle.get("turns") if isinstance(bundle.get("turns"), list) else []
    continuity = bundle.get("continuity") if isinstance(bundle.get("continuity"), dict) else {}
    memory_chunks = continuity.get("memory_chunks") if isinstance(continuity.get("memory_chunks"), list) else []

    current_scene = next(
        (item for item in reversed(scene_history) if isinstance(item, dict) and int(item.get("turn") or 0) == turn_number),
        None,
    )
    expected_facts = [str(item) for item in (scene_response.get("important_facts") or [])]
    stored_facts = [str(item) for item in ((current_scene or {}).get("important_facts") or [])]

    relationship_ids = _expected_applied_ids(result, "relationships", "pair_id")
    knowledge_ids = _expected_applied_ids(result, "knowledge", "character_id")
    npc_ids = _expected_applied_ids(result, "npc_state", "character_id")

    scene_turns = _turns_from_scene_history(scene_history) | _turns_from_memory_chunks(memory_chunks, "scene_summaries")
    turn_turns = _turns_from_turn_history(turns) | _turns_from_memory_chunks(memory_chunks, "turn_summaries")
    expected_turns = set(range(1, turn_number + 1))

    forbidden_paths = _contains_forbidden_keys(
        {
            "scene_history": scene_history,
            "turns": turns,
            "memory_chunks": memory_chunks,
        }
    )

    checks = {
        "turn_number_matches": int(current_state.get("turn_number") or 0) == turn_number,
        "last_player_input_matches": str(current_state.get("last_player_input") or "") == str(scene_response.get("player_input") or ""),
        "current_scene_summary_present": bool(current_scene and current_scene.get("summary")),
        "current_scene_facts_present": all(fact in stored_facts for fact in expected_facts),
        "relationship_patches_persisted": _persisted_relationships(bundle, relationship_ids, turn_number),
        "knowledge_patches_persisted": _persisted_knowledge(bundle, knowledge_ids, turn_number),
        "npc_state_patches_persisted": _persisted_npc_state(bundle, npc_ids, turn_number),
        "scene_turn_coverage_complete": expected_turns.issubset(scene_turns),
        "turn_input_coverage_complete": expected_turns.issubset(turn_turns),
        "no_full_visible_payload_in_runtime_memory": not forbidden_paths,
    }
    warnings = [name for name, passed in checks.items() if not passed]
    report = {
        "turn": turn_number,
        "triggers": triggers,
        "status": "passed" if not warnings else "warning",
        "created_at": now_iso(),
        "checks": checks,
        "counts": {
            "recent_scene_history": len(scene_history),
            "recent_turns": len(turns),
            "memory_chunks": len(memory_chunks),
            "relationship_targets": len(relationship_ids),
            "knowledge_targets": len(knowledge_ids),
            "npc_state_targets": len(npc_ids),
        },
        "warnings": warnings,
        "forbidden_paths": forbidden_paths[:12],
    }

    continuity = dict(continuity)
    audits = [item for item in (continuity.get("persistence_audits") or []) if isinstance(item, dict)]
    audits.append(report)
    continuity["persistence_audits"] = audits[-12:]
    storage.write_json(session_id, "continuity.json", continuity)

    current_state = dict(current_state)
    maintenance = current_state.get("maintenance") if isinstance(current_state.get("maintenance"), dict) else {}
    maintenance = {
        **maintenance,
        "last_persistence_audit": {
            "turn": turn_number,
            "triggers": triggers,
            "status": report["status"],
            "warnings": warnings,
        },
    }
    current_state["maintenance"] = maintenance
    storage.write_json(session_id, "current_state.json", current_state)

    result.setdefault("applied", {}).setdefault("maintenance", []).append(
        {"operation": "persistence_audit", "turn": turn_number, "status": report["status"], "triggers": triggers}
    )
    result.setdefault("next_builder_hints", {})["maintenance"] = maintenance
    return result
