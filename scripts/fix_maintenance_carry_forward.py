from pathlib import Path

path = Path(__file__).resolve().parent.parent / "app" / "state_updater.py"
text = path.read_text(encoding="utf-8")
old = '''        scene_history, turns, continuity, compacted = _auto_compact_runtime_history(scene_history, turns, continuity, turn_number)
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
'''
new = '''        scene_history, turns, continuity, compacted = _auto_compact_runtime_history(scene_history, turns, continuity, turn_number)
        previous_maintenance = current_state.get("maintenance") if isinstance(current_state.get("maintenance"), dict) else {}
        maintenance = {
            **previous_maintenance,
            "last_saved_turn_number": turn_number,
            "state_recovery_audit_due": turn_number > 0 and turn_number % 10 == 0,
            "state_compaction_cleanup_due": turn_number > 0 and turn_number % 15 == 0,
            "continuity_check_required_next": turn_number > 0 and turn_number % 10 == 0,
            "memory_review_required_next": turn_number > 0 and turn_number % 15 == 0,
            "backend_compacted_after_turn": turn_number if compacted else previous_maintenance.get("backend_compacted_after_turn"),
            "last_compact_turn": turn_number if compacted else previous_maintenance.get("last_compact_turn"),
            "memory_chunk_count": len(continuity.get("memory_chunks", []) or []),
            "recent_scene_history_kept": len(scene_history),
            "recent_turns_kept": len(turns),
            "notes": [str(item) for item in (previous_maintenance.get("notes", []) or [])][-8:],
        }
'''
if new not in text:
    if old not in text:
        raise SystemExit("maintenance block anchor not found")
    text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8")
