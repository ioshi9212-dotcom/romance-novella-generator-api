from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"missing patch anchor for {label}: {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


main = ROOT / "app" / "main.py"
replace_once(
    main,
    "from app.turn_processor import process_time_skip_gpt_actions, process_turn_debug_stub, process_turn_gpt_actions\n",
    "from app.turn_maintenance import finalize_due_turn_maintenance\nfrom app.turn_processor import process_time_skip_gpt_actions, process_turn_debug_stub, process_turn_gpt_actions\n",
    "main maintenance import",
)
replace_once(
    main,
    '''            result = record_time_skip_result(
                manager.storage,
                session_id,
                pending,
                normalized_scene_response,
                bundle,
                result,
            )
            _mark_pending_turn_applied(manager, session_id, pending)
''',
    '''            result = record_time_skip_result(
                manager.storage,
                session_id,
                pending,
                normalized_scene_response,
                bundle,
                result,
            )
            result = finalize_due_turn_maintenance(manager.storage, session_id, result)
            _mark_pending_turn_applied(manager, session_id, pending)
''',
    "main maintenance finalizer",
)

state_updater = ROOT / "app" / "state_updater.py"
replace_once(
    state_updater,
    '''    continuity["maintenance_events"] = [
        item for item in (continuity.get("maintenance_events", []) or []) if isinstance(item, dict)
    ][-12:]
    return continuity
''',
    '''    continuity["maintenance_events"] = [
        item for item in (continuity.get("maintenance_events", []) or []) if isinstance(item, dict)
    ][-12:]
    continuity["state_recovery_audits"] = [
        item for item in (continuity.get("state_recovery_audits", []) or []) if isinstance(item, dict)
    ][-6:]
    continuity["state_compaction_reports"] = [
        item for item in (continuity.get("state_compaction_reports", []) or []) if isinstance(item, dict)
    ][-6:]
    return continuity
''',
    "bounded maintenance reports",
)
replace_once(
    state_updater,
    '''        for patch in updates.get("relationship_patches", []) or []:
            pid = patch.get("pair_id")
''',
    '''        for patch in updates.get("relationship_patches", []) or []:
            uses_directional_fields = any(
                key in patch
                for key in ("direction_patch", "a_to_b", "b_to_a", "shared_patch", "from_character_id", "to_character_id")
            )
            if uses_directional_fields:
                # The directional layer runs after the base updater. Applying the same
                # patch here too would duplicate relationship history and recent_changes.
                continue
            pid = patch.get("pair_id")
''',
    "skip duplicate directional relationship application",
)
replace_once(
    state_updater,
    '''            if not character_id:
                rejected.append({"target": "knowledge", "reason": "missing character_id", "severity": "error"})
                continue
            if not patch.get("source_in_scene") or not patch.get("reason"):
''',
    '''            if not character_id:
                rejected.append({"target": "knowledge", "reason": "missing character_id", "severity": "error"})
                continue
            card = characters.get(character_id)
            if not isinstance(card, dict):
                rejected.append({"target": f"knowledge.{character_id}", "reason": "unknown character_id", "severity": "error"})
                continue
            if card.get("available_to_scene") is False or card.get("introduced") is False:
                rejected.append({"target": f"knowledge.{character_id}", "reason": "hidden or unavailable character cannot receive scene knowledge before reveal", "severity": "error"})
                continue
            if not patch.get("source_in_scene") or not patch.get("reason"):
''',
    "knowledge character boundary",
)
replace_once(
    state_updater,
    '''            if patch.get("add_known_facts"):
                base["known_facts"] = _append_many(base.get("known_facts", []), patch["add_known_facts"])
''',
    '''            if patch.get("add_known_facts"):
                known_facts = []
                for item in patch["add_known_facts"]:
                    if isinstance(item, dict):
                        known_facts.append({
                            **item,
                            "turn": item.get("turn", turn_number),
                            "source_type": item.get("source_type") or patch.get("source_type", "scene"),
                            "source_in_scene": item.get("source_in_scene") or patch.get("source_in_scene"),
                        })
                    else:
                        known_facts.append({
                            "text": str(item),
                            "turn": turn_number,
                            "source_type": patch.get("source_type", "scene"),
                            "source_in_scene": patch.get("source_in_scene"),
                            "certainty": patch.get("certainty", "medium"),
                        })
                base["known_facts"] = _append_many(base.get("known_facts", []), known_facts)
''',
    "known fact provenance",
)
replace_once(
    state_updater,
    '''            if patch.get("add_wrong_beliefs"):
                base["wrong_beliefs"] = _append_many(base.get("wrong_beliefs", []), patch["add_wrong_beliefs"])
''',
    '''            if patch.get("add_wrong_beliefs"):
                wrong_beliefs = []
                for item in patch["add_wrong_beliefs"]:
                    if isinstance(item, dict):
                        wrong_beliefs.append({
                            **item,
                            "turn": item.get("turn", turn_number),
                            "source_in_scene": item.get("source_in_scene") or patch.get("source_in_scene"),
                            "may_be_wrong": True,
                        })
                    else:
                        wrong_beliefs.append({
                            "text": str(item),
                            "turn": turn_number,
                            "source_in_scene": patch.get("source_in_scene"),
                            "may_be_wrong": True,
                        })
                base["wrong_beliefs"] = _append_many(base.get("wrong_beliefs", []), wrong_beliefs)
''',
    "wrong belief provenance",
)

directional = ROOT / "app" / "directional_relationships.py"
replace_once(
    directional,
    '''        pid = str(patch.get("pair_id") or "")
        base = relationships.get(pid)
''',
    '''        pid = str(patch.get("pair_id") or "")
        if not pid:
            result["rejected"].append({"target": "relationships", "reason": "missing pair_id", "severity": "error"})
            continue
        if not str(patch.get("reason") or "").strip() or not str(patch.get("source_in_scene") or "").strip():
            result["rejected"].append({
                "target": f"relationships.{pid}",
                "reason": "directional relationship patch requires reason and source_in_scene",
                "severity": "error",
            })
            continue
        base = relationships.get(pid)
''',
    "directional relationship provenance validation",
)

scene_contract = ROOT / "app" / "scene_contract_builder.py"
replace_once(
    scene_contract,
    '''    turn_number = int(current_state.get("turn_number", 0) or 0)

    focus_ids: list[str] = []
''',
    '''    turn_number = int(current_state.get("turn_number", 0) or 0)
    maintenance_state = current_state.get("maintenance") if isinstance(current_state.get("maintenance"), dict) else {}
    audit_due = (
        turn_number > 0
        and turn_number % 10 == 0
        and int(maintenance_state.get("state_recovery_audit_completed_turn") or 0) != turn_number
    )
    compaction_due = (
        turn_number > 0
        and turn_number % 15 == 0
        and int(maintenance_state.get("state_compaction_cleanup_completed_turn") or 0) != turn_number
    )

    focus_ids: list[str] = []
''',
    "maintenance completion-aware due flags",
)
replace_once(
    scene_contract,
    '''        "maintenance": {
            "state_recovery_audit_due": turn_number > 0 and turn_number % 10 == 0,
            "state_compaction_cleanup_due": turn_number > 0 and turn_number % 15 == 0,
            "continuity_check_required": turn_number > 0 and turn_number % 10 == 0,
            "memory_review_required": turn_number > 0 and turn_number % 15 == 0,
            "memory_chunk_count": len(memory_chunks),
        },
''',
    '''        "maintenance": {
            "state_recovery_audit_due": audit_due,
            "state_compaction_cleanup_due": compaction_due,
            "continuity_check_required": audit_due,
            "memory_review_required": compaction_due,
            "state_recovery_audit_completed_turn": maintenance_state.get("state_recovery_audit_completed_turn"),
            "state_recovery_audit_status": maintenance_state.get("state_recovery_audit_status"),
            "state_recovery_audit_issue_count": maintenance_state.get("state_recovery_audit_issue_count", 0),
            "state_compaction_cleanup_completed_turn": maintenance_state.get("state_compaction_cleanup_completed_turn"),
            "state_compaction_cleanup_status": maintenance_state.get("state_compaction_cleanup_status"),
            "state_compaction_cleanup_issue_count": maintenance_state.get("state_compaction_cleanup_issue_count", 0),
            "memory_chunk_count": len(memory_chunks),
        },
''',
    "maintenance contract report",
)

director = ROOT / "app" / "director_bible.py"
replace_once(
    director,
    '''            "no_boring_loop": "если в текущем кадре нет meaningful beat, двигай ближайшее допустимое событие или последствие",
            "preserve_causality": "не создавай новый тайный ответ на ходу, если уже есть world_truth или hidden_lore",
''',
    '''            "no_boring_loop": "если в текущем кадре нет meaningful beat, двигай ближайшее допустимое событие или последствие",
            "sarcasm_calibration": "сухая ирония или лёгкий сарказм — около 5–7% видимого текста: одна-две короткие ноты, не в каждом абзаце; не превращай всех персонажей в одинаково язвительных",
            "preserve_causality": "не создавай новый тайный ответ на ходу, если уже есть world_truth или hidden_lore",
''',
    "director sarcasm calibration",
)
