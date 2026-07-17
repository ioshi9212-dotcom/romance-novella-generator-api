from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from app.id_utils import now_iso

STAGED_BOOTSTRAP_FILE = "pending_bootstrap_draft.json"
SINGLE_SECTIONS = {
    "protagonist",
    "story_plan",
    "director_bible",
    "current_state",
    "future_locks",
    "continuity",
}
ENTRY_SECTIONS = {"characters", "relationships", "knowledge", "npc_state"}
ALL_STAGED_SECTIONS = SINGLE_SECTIONS | ENTRY_SECTIONS
# The normalizer derives relationships, knowledge, NPC runtime, director state,
# future locks and continuity from the cast/story core. Requiring empty Action
# calls for those derived sections made long questionnaires fragile without
# adding any gameplay information.
REQUIRED_SECTIONS = {"characters", "story_plan", "current_state"}
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
PAIR_ID_RE = re.compile(r"^[A-Za-z0-9_-]+__[A-Za-z0-9_-]+$")


class BootstrapStageError(ValueError):
    def __init__(self, detail: str | dict[str, Any], *, status_code: int = 422):
        super().__init__(str(detail))
        self.detail = detail
        self.status_code = status_code


def _require_editable_session(manager: Any, session_id: str) -> dict[str, Any]:
    session = manager.storage.read_json(session_id, "session.json")
    status = session.get("status")
    if status not in {"bootstrap_pending", "bootstrap_review_pending"}:
        raise BootstrapStageError(
            f"Cannot stage bootstrap parts for session status: {status}",
            status_code=409,
        )
    return session


def _empty_draft() -> dict[str, Any]:
    return {
        "scene_history": [],
        "turns": [],
        "_staging": {
            "version": "novella.bootstrap_staging.v1",
            "updated_at": now_iso(),
        },
    }


def _load_draft(manager: Any, session_id: str) -> dict[str, Any]:
    draft = manager.storage.read_json(session_id, STAGED_BOOTSTRAP_FILE, default=_empty_draft())
    if not isinstance(draft, dict):
        raise BootstrapStageError("Stored bootstrap draft is not an object.", status_code=409)
    draft.setdefault("scene_history", [])
    draft.setdefault("turns", [])
    draft.setdefault("_staging", {})
    return draft


def _validate_item_id(section: str, item_id: str | None) -> str:
    value = (item_id or "").strip()
    if not value:
        raise BootstrapStageError(f"item_id is required for section {section}.")
    if not ID_RE.fullmatch(value):
        raise BootstrapStageError(f"Invalid item_id for section {section}: {value}")
    return value


def _valid_character_id(value: Any) -> str | None:
    text = str(value or "").strip()
    return text if ID_RE.fullmatch(text) else None


def _valid_pair_id(value: Any) -> str | None:
    text = str(value or "").strip()
    return text if PAIR_ID_RE.fullmatch(text) else None


def _normalize_relationship_entry(
    item_id: str | None,
    entry: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    supplied = str(item_id or "").strip()
    embedded = _valid_pair_id(entry.get("pair_id"))
    character_a = _valid_character_id(entry.get("character_a"))
    character_b = _valid_character_id(entry.get("character_b"))
    derived = f"{character_a}__{character_b}" if character_a and character_b else None
    supplied_valid = _valid_pair_id(supplied)

    candidates = {
        source: candidate
        for source, candidate in {
            "item_id": supplied_valid,
            "value.pair_id": embedded,
            "value.character_a/value.character_b": derived,
        }.items()
        if candidate
    }
    unique_candidates = set(candidates.values())
    if len(unique_candidates) > 1:
        raise BootstrapStageError(
            {
                "code": "relationship_id_conflict",
                "message": "Relationship identifiers disagree.",
                "candidates": candidates,
            }
        )
    if not unique_candidates:
        raise BootstrapStageError(
            {
                "code": "invalid_relationship_item_id",
                "received_item_id": supplied or None,
                "expected": "<character_a>__<character_b>",
                "recovery": "Provide value.pair_id or valid value.character_a and value.character_b.",
            }
        )

    canonical = next(iter(unique_candidates))
    canonical_a, canonical_b = canonical.split("__", 1)
    if character_a and character_a != canonical_a:
        raise BootstrapStageError(
            {
                "code": "relationship_id_conflict",
                "message": "value.character_a does not match the canonical relationship id.",
                "canonical_item_id": canonical,
                "character_a": character_a,
            }
        )
    if character_b and character_b != canonical_b:
        raise BootstrapStageError(
            {
                "code": "relationship_id_conflict",
                "message": "value.character_b does not match the canonical relationship id.",
                "canonical_item_id": canonical,
                "character_b": character_b,
            }
        )

    normalized = dict(entry)
    normalized["pair_id"] = canonical
    normalized["character_a"] = canonical_a
    normalized["character_b"] = canonical_b
    return canonical, normalized


def _normalize_relationship_bucket(entries: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for raw_item_id, raw_entry in entries.items():
        if not isinstance(raw_entry, dict):
            raise BootstrapStageError(
                {
                    "code": "invalid_relationship_entry",
                    "item_id": str(raw_item_id),
                    "message": "Each relationship entry must be an object.",
                }
            )
        canonical, entry = _normalize_relationship_entry(str(raw_item_id), raw_entry)
        if canonical in normalized and normalized[canonical] != entry:
            raise BootstrapStageError(
                {
                    "code": "duplicate_relationship_id",
                    "canonical_item_id": canonical,
                }
            )
        normalized[canonical] = entry
    return normalized


def _deep_merge(existing: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(existing)
    for key, value in patch.items():
        current = result.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            result[key] = _deep_merge(current, value)
        else:
            result[key] = deepcopy(value)
    return result


def _delete_field_paths(value: dict[str, Any], field_paths: list[str]) -> dict[str, Any]:
    result = deepcopy(value)
    for raw_path in field_paths:
        path = str(raw_path or "").strip()
        parts = path.split(".") if path else []
        if not parts or len(parts) > 12 or any(not part or len(part) > 128 for part in parts):
            raise BootstrapStageError(f"Invalid delete_fields path: {raw_path!r}")
        parent: Any = result
        for part in parts[:-1]:
            if not isinstance(parent, dict) or not isinstance(parent.get(part), dict):
                parent = None
                break
            parent = parent[part]
        if isinstance(parent, dict):
            parent.pop(parts[-1], None)
    return result


def bootstrap_stage_progress(draft: dict[str, Any]) -> dict[str, Any]:
    missing: list[str] = []
    for section in sorted(REQUIRED_SECTIONS):
        if section not in draft or not isinstance(draft.get(section), dict):
            missing.append(section)
    if isinstance(draft.get("characters"), dict) and not draft.get("characters"):
        if "characters" not in missing:
            missing.append("characters")

    counts = {
        section: len(draft.get(section) or {}) if isinstance(draft.get(section), dict) else 0
        for section in sorted(ENTRY_SECTIONS)
    }
    stored_sections = sorted(
        section
        for section in ALL_STAGED_SECTIONS
        if section in draft and isinstance(draft.get(section), dict)
    )
    return {
        "ready_to_finalize": not missing,
        "missing_sections": sorted(missing),
        "entry_counts": counts,
        "stored_sections": stored_sections,
    }


def save_bootstrap_part(
    manager: Any,
    session_id: str,
    *,
    section: str,
    value: dict[str, Any],
    item_id: str | None = None,
    delete_fields: list[str] | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    session = _require_editable_session(manager, session_id)
    if section not in ALL_STAGED_SECTIONS:
        raise BootstrapStageError(f"Unsupported bootstrap section: {section}")
    if not isinstance(value, dict):
        raise BootstrapStageError("value must be an object.")

    draft = _load_draft(manager, session_id)
    delete_fields = list(delete_fields or [])
    stored_item_id: str | None = None
    if section in ENTRY_SECTIONS:
        if item_id in {None, ""}:
            stored_section = _normalize_relationship_bucket(value) if section == "relationships" else deepcopy(value)
            draft[section] = _delete_field_paths(stored_section, delete_fields)
        else:
            bucket = draft.get(section)
            if not isinstance(bucket, dict):
                bucket = {}
            if section == "relationships":
                stored_item_id, normalized_patch = _normalize_relationship_entry(item_id, value)
                existing = bucket.get(stored_item_id) if isinstance(bucket.get(stored_item_id), dict) else {}
                stored_value = normalized_patch if replace else _deep_merge(existing, normalized_patch)
                stored_value = _delete_field_paths(stored_value, delete_fields)
                _, stored_value = _normalize_relationship_entry(stored_item_id, stored_value)
            else:
                stored_item_id = _validate_item_id(section, item_id)
                existing = bucket.get(stored_item_id) if isinstance(bucket.get(stored_item_id), dict) else {}
                stored_value = deepcopy(value) if replace else _deep_merge(existing, value)
                stored_value = _delete_field_paths(stored_value, delete_fields)
            bucket[stored_item_id] = stored_value
            draft[section] = bucket
    else:
        if item_id not in {None, ""}:
            raise BootstrapStageError(f"item_id is not allowed for section {section}.")
        existing = draft.get(section) if isinstance(draft.get(section), dict) else {}
        stored_value = deepcopy(value) if replace else _deep_merge(existing, value)
        draft[section] = _delete_field_paths(stored_value, delete_fields)

    staging_meta = draft.get("_staging") if isinstance(draft.get("_staging"), dict) else {}
    staging_meta.update({
        "version": "novella.bootstrap_staging.v1",
        "updated_at": now_iso(),
        "last_section": section,
        "last_item_id": stored_item_id,
    })
    draft["_staging"] = staging_meta
    manager.storage.write_json(session_id, STAGED_BOOTSTRAP_FILE, draft)

    return {
        "session_id": session_id,
        "status": session.get("status", "bootstrap_pending"),
        "section": section,
        "item_id": stored_item_id,
        "stored": True,
        "progress": bootstrap_stage_progress(draft),
    }


def assemble_staged_bootstrap(manager: Any, session_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    _require_editable_session(manager, session_id)
    draft = _load_draft(manager, session_id)
    progress = bootstrap_stage_progress(draft)
    if not progress["ready_to_finalize"]:
        raise BootstrapStageError(
            {
                "code": "bootstrap_parts_incomplete",
                "missing_sections": progress["missing_sections"],
                "entry_counts": progress["entry_counts"],
            },
            status_code=409,
        )

    assembled = {key: value for key, value in draft.items() if key != "_staging"}
    assembled["scene_history"] = []
    assembled["turns"] = []
    return assembled, progress
