from __future__ import annotations

from hashlib import sha256
from typing import Any

from app.service import NovellaService


def _is_dict(value: Any) -> bool:
    return isinstance(value, dict)


def _packet_report(pending: Any) -> dict[str, Any] | None:
    if not isinstance(pending, dict) or not pending:
        return None
    chunks = pending.get("chunks", [])
    if not isinstance(chunks, list):
        chunks = []
    try:
        last_delivered = int(pending.get("last_delivered_chunk_index", 0))
    except (TypeError, ValueError):
        last_delivered = 0
    total_chars = sum(len(str(chunk)) for chunk in chunks)
    digest_ok = None
    if chunks and pending.get("content_sha256"):
        raw = "".join(str(chunk) for chunk in chunks)
        digest_ok = sha256(raw.encode("utf-8")).hexdigest() == pending.get(
            "content_sha256"
        )
    computed_complete = bool(chunks) and last_delivered >= len(chunks) - 1
    return {
        "status": pending.get("status"),
        "packet_type": pending.get("packet_type"),
        "packet_id": pending.get("packet_id"),
        "turn_number": pending.get("turn_number"),
        "turn_revision": pending.get("turn_revision"),
        "cycle_position": pending.get("cycle_position"),
        "expected_state_revision": pending.get("expected_state_revision"),
        "chunk_count": len(chunks),
        "delivered_chunk_count": min(last_delivered + 1, len(chunks)) if chunks else 0,
        "all_chunks_delivered": bool(pending.get("all_chunks_delivered", False)),
        "computed_all_chunks_delivered": computed_complete,
        "total_chars": total_chars,
        "largest_chunk_chars": max((len(str(chunk)) for chunk in chunks), default=0),
        "content_digest_ok": digest_ok,
        "runtime_repacked": bool(pending.get("runtime_repacked", False)),
        "runtime_repacked_from_chunk_count": pending.get(
            "runtime_repacked_from_chunk_count"
        ),
        "runtime_chunk_chars": pending.get("runtime_chunk_chars"),
        "created_at": pending.get("created_at"),
        "committed_at": pending.get("committed_at"),
    }


def audit_runtime(service: NovellaService) -> dict[str, Any]:
    """Mechanically audit every Railway session without changing story canon."""

    sessions: list[dict[str, Any]] = []
    global_counts = {
        "sessions": 0,
        "sessions_with_errors": 0,
        "active_pending_turns": 0,
        "active_pending_audits": 0,
        "active_pending_turns_incomplete": 0,
        "active_pending_turns_fully_loaded": 0,
        "repacked_pending_packets": 0,
    }

    for session_dir in sorted(service.storage.sessions_dir.iterdir()):
        if not session_dir.is_dir():
            continue
        session_id = session_dir.name
        errors: list[str] = []
        warnings: list[str] = []
        try:
            session = service.storage.read_json(session_id, "session.json", default={})
            manifest = service.storage.read_json(session_id, "manifest.json", default={})
            novel = service.storage.read_json(session_id, "state/novel.json", default={})
            scene_state = service.storage.read_json(
                session_id, "state/scene_state.json", default={}
            )
        except Exception as exc:  # diagnostic endpoint must continue across sessions
            sessions.append(
                {
                    "session_id": session_id,
                    "errors": [f"unreadable session root: {type(exc).__name__}: {exc}"],
                }
            )
            global_counts["sessions"] += 1
            global_counts["sessions_with_errors"] += 1
            continue

        if not _is_dict(session):
            session = {}
            errors.append("session.json is missing or not an object")
        if not _is_dict(manifest):
            manifest = {}
            errors.append("manifest.json is missing or not an object")
        if not _is_dict(novel):
            novel = {}
            errors.append("state/novel.json is missing or not an object")
        if not _is_dict(scene_state):
            scene_state = {}
            errors.append("state/scene_state.json is missing or not an object")

        last_completed = int(session.get("last_completed_turn", 0) or 0)
        last_audited = int(session.get("last_audited_turn", 0) or 0)
        turns_since_audit = int(session.get("turns_since_audit", 0) or 0)
        state_revision = int(session.get("state_revision", 0) or 0)
        manifest_revision = int(manifest.get("state_revision", 0) or 0)

        if int(session.get("next_turn_number", last_completed + 1) or 0) != last_completed + 1:
            errors.append("session.next_turn_number does not equal last_completed_turn + 1")
        if turns_since_audit != last_completed - last_audited:
            errors.append("turns_since_audit does not equal last_completed_turn - last_audited_turn")
        expected_audit_required = turns_since_audit >= 15
        if bool(session.get("audit_required", False)) != expected_audit_required:
            errors.append("audit_required flag disagrees with turns_since_audit")
        if state_revision != manifest_revision:
            errors.append("session state_revision disagrees with manifest state_revision")

        character_ids = list(manifest.get("character_ids", []) or [])
        location_ids = list(manifest.get("location_ids", []) or [])
        object_ids = list(manifest.get("object_ids", []) or [])
        if len(character_ids) != len(set(character_ids)):
            errors.append("manifest contains duplicate character_ids")
        if len(location_ids) != len(set(location_ids)):
            errors.append("manifest contains duplicate location_ids")
        if len(object_ids) != len(set(object_ids)):
            errors.append("manifest contains duplicate object_ids")

        required_root_paths = [
            "state/novel.json",
            "state/hidden_lore.json",
            "state/plot_state.json",
            "state/director_plan.json",
            "state/world_state.json",
            "state/scene_state.json",
            "chronology/manifest.json",
        ]
        for relative in required_root_paths:
            if not (session_dir / relative).is_file():
                errors.append(f"missing {relative}")

        for character_id in character_ids:
            for name in ("card.json", "current_state.json", "relationships.json", "knowledge.json"):
                relative = f"characters/{character_id}/{name}"
                if not (session_dir / relative).is_file():
                    errors.append(f"missing {relative}")
        for location_id in location_ids:
            relative = f"locations/{location_id}.json"
            if not (session_dir / relative).is_file():
                errors.append(f"missing {relative}")
        for object_id in object_ids:
            relative = f"objects/{object_id}.json"
            if not (session_dir / relative).is_file():
                errors.append(f"missing {relative}")

        pov_character_id = str(novel.get("pov_character_id", "") or "")
        if pov_character_id and pov_character_id not in character_ids:
            errors.append("novel.pov_character_id is not registered in manifest.character_ids")
        for present_id in scene_state.get("present_character_ids", []) or []:
            if present_id not in character_ids:
                errors.append(f"scene_state references unknown present character {present_id}")
        scene_location = scene_state.get("location_id")
        if scene_location and scene_location not in location_ids:
            warnings.append(f"scene_state location {scene_location} is not in manifest.location_ids")
        if last_completed > 0:
            stored_scene_turn = int(scene_state.get("turn_number", 0) or 0)
            if stored_scene_turn not in {0, last_completed}:
                warnings.append(
                    f"scene_state.turn_number={stored_scene_turn} while last_completed_turn={last_completed}"
                )

        missing_turns: list[int] = []
        if last_completed > 0:
            for number in range(1, last_completed + 1):
                if not (session_dir / "turns" / f"turn_{number:06d}.json").is_file():
                    missing_turns.append(number)
                    if len(missing_turns) >= 30:
                        break
            if missing_turns:
                errors.append(
                    "missing committed turn files: " + ",".join(str(item) for item in missing_turns)
                )

        chronology_manifest = service.storage.read_json(
            session_id, "chronology/manifest.json", default={}
        )
        chronology_parts = []
        if isinstance(chronology_manifest, dict):
            chronology_parts = list(chronology_manifest.get("parts", []) or [])
            for part in chronology_parts:
                part_id = str(part.get("part_id", "")) if isinstance(part, dict) else ""
                if part_id and not (session_dir / "chronology" / f"{part_id}.json").is_file():
                    errors.append(f"missing chronology part {part_id}")

        pending_turn_raw = service.storage.read_json(
            session_id, "pending_turn.json", default={}
        )
        pending_audit_raw = service.storage.read_json(
            session_id, "pending_audit.json", default={}
        )
        pending_turn = _packet_report(pending_turn_raw)
        pending_audit = _packet_report(pending_audit_raw)

        if pending_turn and pending_turn.get("status") == "active":
            global_counts["active_pending_turns"] += 1
            if pending_turn.get("computed_all_chunks_delivered"):
                global_counts["active_pending_turns_fully_loaded"] += 1
            else:
                global_counts["active_pending_turns_incomplete"] += 1
            expected_revision = int(pending_turn.get("expected_state_revision") or 0)
            if expected_revision != state_revision:
                errors.append("active pending turn has stale expected_state_revision")
            pending_number = int(pending_turn.get("turn_number") or 0)
            pending_mode = (
                pending_turn_raw.get("mode") if isinstance(pending_turn_raw, dict) else None
            )
            expected_pending_number = last_completed if pending_mode == "revise_last" else last_completed + 1
            if pending_number != expected_pending_number:
                errors.append(
                    f"active pending turn_number={pending_number}, expected {expected_pending_number}"
                )
            if pending_turn.get("content_digest_ok") is False:
                errors.append("active pending turn packet digest mismatch")
            if pending_turn.get("all_chunks_delivered") != pending_turn.get(
                "computed_all_chunks_delivered"
            ):
                errors.append("active pending turn all_chunks_delivered flag is inconsistent")
            if pending_turn.get("runtime_repacked"):
                global_counts["repacked_pending_packets"] += 1

        if pending_audit and pending_audit.get("status") == "active":
            global_counts["active_pending_audits"] += 1
            expected_revision = int(pending_audit.get("expected_state_revision") or 0)
            if expected_revision != state_revision:
                errors.append("active pending audit has stale expected_state_revision")
            if pending_audit.get("content_digest_ok") is False:
                errors.append("active pending audit packet digest mismatch")
            if pending_audit.get("all_chunks_delivered") != pending_audit.get(
                "computed_all_chunks_delivered"
            ):
                errors.append("active pending audit all_chunks_delivered flag is inconsistent")
            if pending_audit.get("runtime_repacked"):
                global_counts["repacked_pending_packets"] += 1

        pov_name = ""
        if pov_character_id:
            card = service.storage.read_json(
                session_id,
                f"characters/{pov_character_id}/card.json",
                default={},
            )
            if isinstance(card, dict):
                identity = card.get("identity", {})
                if isinstance(identity, dict):
                    pov_name = str(identity.get("name", "") or "")

        row = {
            "session_id": session_id,
            "title": str(novel.get("title", "") or ""),
            "pov_character_id": pov_character_id,
            "pov_name": pov_name,
            "updated_at": session.get("updated_at"),
            "state_revision": state_revision,
            "last_completed_turn": last_completed,
            "last_audited_turn": last_audited,
            "turns_since_audit": turns_since_audit,
            "audit_required": bool(session.get("audit_required", False)),
            "counts": {
                "characters": len(character_ids),
                "locations": len(location_ids),
                "objects": len(object_ids),
                "chronology_parts": len(chronology_parts),
            },
            "pending_turn": pending_turn,
            "pending_audit": pending_audit,
            "errors": errors,
            "warnings": warnings,
        }
        sessions.append(row)
        global_counts["sessions"] += 1
        if errors:
            global_counts["sessions_with_errors"] += 1

    sessions.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return {
        "summary": global_counts,
        "packet_chunk_chars": service.settings.packet_chunk_chars,
        "sessions": sessions,
    }
