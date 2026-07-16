from __future__ import annotations

from typing import Any

from app.id_utils import now_iso
from app.storage import JsonStorage


MAX_RECOVERY_AUDITS = 6
MAX_COMPACTION_REPORTS = 6
FORBIDDEN_RUNTIME_KEYS = {
    "rendered_text",
    "visible_scene_text",
    "scene_response",
    "player_options",
    "safety_checks",
}


def _turn_value(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _forbidden_paths(value: Any, path: str) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}"
            if key in FORBIDDEN_RUNTIME_KEYS:
                found.append(child)
            found.extend(_forbidden_paths(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_forbidden_paths(item, f"{path}[{index}]"))
    return found


def _check_turn_sequence(entries: Any, label: str, current_turn: int, issues: list[str]) -> list[int]:
    if not isinstance(entries, list):
        issues.append(f"{label} is not a list")
        return []
    turns = [_turn_value(item.get("turn")) for item in entries if isinstance(item, dict)]
    valid = [turn for turn in turns if turn is not None]
    if len(valid) != len(turns):
        issues.append(f"{label} contains entries without numeric turn")
    if valid != sorted(valid):
        issues.append(f"{label} turn order is not monotonic")
    if len(valid) != len(set(valid)):
        issues.append(f"{label} contains duplicate turn entries")
    if valid and valid[-1] != current_turn:
        issues.append(f"{label} latest turn is {valid[-1]}, expected {current_turn}")
    return valid


def _check_provenance(items: Any, label: str, issues: list[str]) -> int:
    checked = 0
    if not isinstance(items, list):
        return checked
    for index, item in enumerate(items):
        if not isinstance(item, dict) or _turn_value(item.get("turn")) is None:
            continue
        checked += 1
        if not str(item.get("source_in_scene") or item.get("based_on") or "").strip():
            issues.append(f"{label}[{index}] has no source_in_scene/based_on")
    return checked


def _check_change_history(items: Any, label: str, issues: list[str]) -> int:
    checked = 0
    seen: set[tuple[Any, ...]] = set()
    if not isinstance(items, list):
        return checked
    for index, item in enumerate(items):
        if not isinstance(item, dict) or _turn_value(item.get("turn")) is None:
            continue
        checked += 1
        if not str(item.get("reason") or "").strip() or not str(item.get("source_in_scene") or "").strip():
            issues.append(f"{label}[{index}] lacks reason/source_in_scene")
        signature = (
            _turn_value(item.get("turn")),
            item.get("entry"),
            item.get("change_type"),
            item.get("source_in_scene"),
            item.get("from_character_id"),
            item.get("to_character_id"),
        )
        if signature in seen:
            issues.append(f"{label}[{index}] duplicates an already stored change")
        seen.add(signature)
    return checked


def _build_recovery_audit(storage: JsonStorage, session_id: str, turn_number: int) -> dict[str, Any]:
    current_state = storage.read_json(session_id, "current_state.json", default={})
    scene_history = storage.read_json(session_id, "scene_history.json", default=[])
    turns = storage.read_json(session_id, "turns.json", default=[])
    continuity = storage.read_json(session_id, "continuity.json", default={})
    characters = storage.read_characters(session_id)
    knowledge = storage.read_knowledge(session_id)
    relationships = storage.read_relationships(session_id)
    npc_state = storage.read_json(session_id, "npc_state.json", default={})
    director_bible = storage.read_json(session_id, "director_bible.json", default={})

    issues: list[str] = []
    warnings: list[str] = []
    counts = {
        "scene_history_entries": len(scene_history) if isinstance(scene_history, list) else 0,
        "turn_entries": len(turns) if isinstance(turns, list) else 0,
        "knowledge_entries": len(knowledge),
        "relationship_pairs": len(relationships),
        "npc_runtime_entries": len(npc_state) if isinstance(npc_state, dict) else 0,
        "memory_chunks": len((continuity or {}).get("memory_chunks", []) or []) if isinstance(continuity, dict) else 0,
        "provenance_records_checked": 0,
    }

    if _turn_value((current_state or {}).get("turn_number")) != turn_number:
        issues.append("current_state.turn_number does not match the audit turn")
    if isinstance(scene_history, list) and len(scene_history) > 6:
        issues.append("scene_history keeps more than 6 recent entries")
    if isinstance(turns, list) and len(turns) > 8:
        issues.append("turns keeps more than 8 recent entries")
    _check_turn_sequence(scene_history, "scene_history", turn_number, issues)
    _check_turn_sequence(turns, "turns", turn_number, issues)

    for root_label, value in (
        ("scene_history", scene_history),
        ("turns", turns),
        ("continuity.memory_chunks", (continuity or {}).get("memory_chunks", []) if isinstance(continuity, dict) else []),
    ):
        for path in _forbidden_paths(value, root_label):
            issues.append(f"forbidden full-scene payload retained at {path}")

    for character_id, entry in knowledge.items():
        if character_id not in characters and not str(character_id).startswith("_"):
            issues.append(f"knowledge.{character_id} belongs to an unknown character")
        if not isinstance(entry, dict):
            issues.append(f"knowledge.{character_id} is not an object")
            continue
        counts["provenance_records_checked"] += _check_change_history(entry.get("history"), f"knowledge.{character_id}.history", issues)
        for field in ("known_facts", "observations", "assumptions", "wrong_beliefs"):
            counts["provenance_records_checked"] += _check_provenance(entry.get(field), f"knowledge.{character_id}.{field}", issues)

    for pair_id, pair in relationships.items():
        if not isinstance(pair, dict):
            issues.append(f"relationships.{pair_id} is not an object")
            continue
        if str(pair.get("pair_id") or "") != str(pair_id):
            issues.append(f"relationships.{pair_id}.pair_id does not match its file key")
        for participant_key in ("character_a", "character_b"):
            participant = str(pair.get(participant_key) or "")
            if participant and participant not in characters:
                issues.append(f"relationships.{pair_id}.{participant_key} references unknown character {participant}")
        counts["provenance_records_checked"] += _check_change_history(pair.get("history"), f"relationships.{pair_id}.history", issues)
        shared = pair.get("shared") if isinstance(pair.get("shared"), dict) else {}
        counts["provenance_records_checked"] += _check_change_history(shared.get("recent_changes"), f"relationships.{pair_id}.shared.recent_changes", issues)

    if not isinstance(npc_state, dict):
        issues.append("npc_state is not an object")
    else:
        for character_id, entry in npc_state.items():
            if character_id not in characters:
                issues.append(f"npc_state.{character_id} belongs to an unknown character")
            if not isinstance(entry, dict):
                issues.append(f"npc_state.{character_id} is not an object")
                continue
            counts["provenance_records_checked"] += _check_change_history(entry.get("history"), f"npc_state.{character_id}.history", issues)
            last_updated = _turn_value(entry.get("last_updated_turn"))
            if last_updated is not None and last_updated > turn_number:
                issues.append(f"npc_state.{character_id}.last_updated_turn is in the future")

    if isinstance(director_bible, dict):
        counts["provenance_records_checked"] += _check_change_history(director_bible.get("history"), "director_bible.history", issues)

    hidden_ids = {
        str(character_id)
        for character_id, card in characters.items()
        if isinstance(card, dict)
        and (
            card.get("cast_status") == "hidden_core"
            or card.get("introduced") is False
            or card.get("available_to_scene") is False
        )
    }
    active_ids = {
        str(item)
        for item in [
            *((current_state or {}).get("active_character_ids", []) or []),
            *((current_state or {}).get("nearby_character_ids", []) or []),
        ]
    }
    leaked = sorted(hidden_ids & active_ids)
    if leaked:
        issues.append(f"hidden/unavailable characters leaked into active scene state: {leaked}")

    if not counts["provenance_records_checked"]:
        warnings.append("No sourced runtime changes were available to verify yet.")

    return {
        "turn": turn_number,
        "type": "state_recovery_audit",
        "status": "ok" if not issues else "needs_attention",
        "checked_at": now_iso(),
        "issue_count": len(issues),
        "warning_count": len(warnings),
        "issues": issues[:12],
        "warnings": warnings[:8],
        "counts": counts,
    }


def _build_compaction_report(storage: JsonStorage, session_id: str, turn_number: int) -> dict[str, Any]:
    current_state = storage.read_json(session_id, "current_state.json", default={})
    scene_history = storage.read_json(session_id, "scene_history.json", default=[])
    turns = storage.read_json(session_id, "turns.json", default=[])
    continuity = storage.read_json(session_id, "continuity.json", default={})
    memory_chunks = (continuity or {}).get("memory_chunks", []) if isinstance(continuity, dict) else []
    issues: list[str] = []

    if len(scene_history) > 6:
        issues.append("scene_history was not reduced to the recent window")
    if len(turns) > 8:
        issues.append("turns was not reduced to the recent window")
    if not memory_chunks:
        issues.append("no memory_chunks were created by turn 15")
    for path in _forbidden_paths(memory_chunks, "continuity.memory_chunks"):
        issues.append(f"compaction retained forbidden payload at {path}")
    maintenance = (current_state or {}).get("maintenance") if isinstance((current_state or {}).get("maintenance"), dict) else {}
    if _turn_value(maintenance.get("last_compact_turn")) != turn_number:
        issues.append("current_state.maintenance.last_compact_turn was not updated")

    return {
        "turn": turn_number,
        "type": "state_compaction_cleanup",
        "status": "ok" if not issues else "needs_attention",
        "checked_at": now_iso(),
        "issue_count": len(issues),
        "issues": issues[:12],
        "recent_scene_history_kept": len(scene_history),
        "recent_turns_kept": len(turns),
        "memory_chunk_count": len(memory_chunks),
    }


def _update_maintenance_event(continuity: dict[str, Any], report: dict[str, Any]) -> None:
    events = continuity.setdefault("maintenance_events", [])
    for event in reversed(events):
        if not isinstance(event, dict):
            continue
        if event.get("turn") == report.get("turn") and event.get("type") == report.get("type"):
            event.update({
                "status": report.get("status"),
                "checked_at": report.get("checked_at"),
                "issue_count": report.get("issue_count", 0),
            })
            return
    events.append({
        "turn": report.get("turn"),
        "type": report.get("type"),
        "status": report.get("status"),
        "checked_at": report.get("checked_at"),
        "issue_count": report.get("issue_count", 0),
    })


def finalize_due_turn_maintenance(
    storage: JsonStorage,
    session_id: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    current_state = storage.read_json(session_id, "current_state.json", default={})
    turn_number = _turn_value((current_state or {}).get("turn_number")) or 0
    audit_due = turn_number > 0 and turn_number % 10 == 0
    compaction_due = turn_number > 0 and turn_number % 15 == 0
    if not audit_due and not compaction_due:
        return result

    continuity = storage.read_json(session_id, "continuity.json", default={})
    if not isinstance(continuity, dict):
        continuity = {}
    maintenance = current_state.get("maintenance") if isinstance(current_state.get("maintenance"), dict) else {}
    maintenance = dict(maintenance)
    reports: list[dict[str, Any]] = []

    if audit_due:
        audit = _build_recovery_audit(storage, session_id, turn_number)
        audits = [item for item in (continuity.get("state_recovery_audits", []) or []) if isinstance(item, dict)]
        audits.append(audit)
        continuity["state_recovery_audits"] = audits[-MAX_RECOVERY_AUDITS:]
        continuity["last_state_recovery_audit"] = audit
        _update_maintenance_event(continuity, audit)
        maintenance.update({
            "state_recovery_audit_due": False,
            "continuity_check_required_next": False,
            "state_recovery_audit_completed_turn": turn_number,
            "state_recovery_audit_status": audit["status"],
            "state_recovery_audit_issue_count": audit["issue_count"],
            "state_recovery_audit_warning_count": audit["warning_count"],
        })
        if audit["issues"]:
            notes = [str(item) for item in (maintenance.get("notes", []) or [])]
            notes.extend(f"Audit turn {turn_number}: {item}" for item in audit["issues"][:5])
            maintenance["notes"] = list(dict.fromkeys(notes))[-8:]
        reports.append(audit)

    if compaction_due:
        compaction = _build_compaction_report(storage, session_id, turn_number)
        reports_list = [item for item in (continuity.get("state_compaction_reports", []) or []) if isinstance(item, dict)]
        reports_list.append(compaction)
        continuity["state_compaction_reports"] = reports_list[-MAX_COMPACTION_REPORTS:]
        continuity["last_state_compaction_report"] = compaction
        _update_maintenance_event(continuity, compaction)
        maintenance.update({
            "state_compaction_cleanup_due": False,
            "memory_review_required_next": False,
            "state_compaction_cleanup_completed_turn": turn_number,
            "state_compaction_cleanup_status": compaction["status"],
            "state_compaction_cleanup_issue_count": compaction["issue_count"],
        })
        reports.append(compaction)

    current_state["maintenance"] = maintenance
    storage.write_json(session_id, "current_state.json", current_state)
    storage.write_json(session_id, "continuity.json", continuity)

    result.setdefault("applied", {}).setdefault("maintenance", [])
    for report in reports:
        result["applied"]["maintenance"].append({
            "operation": report["type"],
            "turn": turn_number,
            "status": report["status"],
            "issue_count": report["issue_count"],
        })
    hints = result.setdefault("next_builder_hints", {})
    hints["maintenance"] = maintenance
    if any(report.get("issue_count") for report in reports):
        hints["repair_required"] = True
        hints["maintenance_reports"] = reports
    return result
