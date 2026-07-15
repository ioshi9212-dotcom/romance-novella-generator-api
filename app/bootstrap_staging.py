from __future__ import annotations

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
REQUIRED_SECTIONS = SINGLE_SECTIONS | ENTRY_SECTIONS
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
    pattern = PAIR_ID_RE if section == "relationships" else ID_RE
    if not pattern.fullmatch(value):
        raise BootstrapStageError(f"Invalid item_id for section {section}: {value}")
    return value


def bootstrap_stage_progress(draft: dict[str, Any]) -> dict[str, Any]:
    missing: list[str] = []
    for section in sorted(SINGLE_SECTIONS):
        if section not in draft or not isinstance(draft.get(section), dict):
            missing.append(section)
    for section in sorted(ENTRY_SECTIONS):
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
        for section in REQUIRED_SECTIONS
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
) -> dict[str, Any]:
    session = _require_editable_session(manager, session_id)
    if section not in ALL_STAGED_SECTIONS:
        raise BootstrapStageError(f"Unsupported bootstrap section: {section}")
    if not isinstance(value, dict):
        raise BootstrapStageError("value must be an object.")

    draft = _load_draft(manager, session_id)
    stored_item_id: str | None = None
    if section in ENTRY_SECTIONS:
        if item_id in {None, ""}:
            draft[section] = value
        else:
            stored_item_id = _validate_item_id(section, item_id)
            bucket = draft.get(section)
            if not isinstance(bucket, dict):
                bucket = {}
            bucket[stored_item_id] = value
            draft[section] = bucket
    else:
        if item_id not in {None, ""}:
            raise BootstrapStageError(f"item_id is not allowed for section {section}.")
        draft[section] = value

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
