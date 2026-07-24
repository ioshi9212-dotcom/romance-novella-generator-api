from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from app.models import CreateSessionRequest, SessionStatus, SessionSummary
from app.storage import (
    SESSIONS_DIR,
    atomic_write_json,
    read_json,
    recover_transactions,
    require_session,
    session_lock,
    session_root,
    utc_now,
)
from app.validator import validate_bootstrap


SCHEMA_VERSION = 1


def _new_session_id() -> str:
    return f"nov_{uuid4().hex}"


def _resume_code() -> str:
    return uuid4().hex[:8].upper()


def create_session(request: CreateSessionRequest) -> SessionSummary:
    session_id = _new_session_id()
    root = session_root(session_id)
    root.mkdir(parents=True, exist_ok=False)
    for directory in (
        "bootstrap/draft/characters",
        "state/characters",
        "state/knowledge",
        "scenes",
        "transactions/pending",
        "transactions/receipts",
    ):
        (root / directory).mkdir(parents=True, exist_ok=True)
    now = utc_now()
    metadata = {
        "session_id": session_id,
        "resume_code": _resume_code(),
        "title": (request.title or "Новая новелла").strip(),
        "status": SessionStatus.QUESTIONNAIRE.value,
        "schema_version": SCHEMA_VERSION,
        "rules_version": 1,
        "state_version": 0,
        "turn_number": 0,
        "created_at": now,
        "updated_at": now,
    }
    atomic_write_json(root / "session.json", metadata)
    atomic_write_json(root / "bootstrap" / "questionnaire.json", {"entries": []})
    (root / "journal.jsonl").write_text("", encoding="utf-8")
    return get_session_summary(session_id)


def _pending_turn_id(root: Path) -> str | None:
    pending_root = root / "transactions" / "pending"
    if not pending_root.is_dir():
        return None
    for directory in sorted(pending_root.iterdir(), reverse=True):
        metadata = read_json(directory / "metadata.json", default={}) or {}
        if metadata.get("status") == "open":
            return directory.name
    return None


def get_session_summary(session_id: str) -> SessionSummary:
    root = require_session(session_id)
    with session_lock(root):
        recover_transactions(root)
        metadata = read_json(root / "session.json", default={}) or {}
        validation = validate_bootstrap(root)
        review = read_json(root / "bootstrap" / "draft" / "review.json", default=None)
        current = read_json(root / "state" / "current.json", default=None)
        current_summary: dict[str, Any] | None = None
        if isinstance(current, dict):
            current_summary = {
                key: current.get(key)
                for key in (
                    "datetime",
                    "location_id",
                    "pov_state",
                    "present_character_ids",
                    "last_scene_end",
                )
                if key in current
            }
        return SessionSummary(
            **metadata,
            pending_turn_id=_pending_turn_id(root),
            bootstrap_missing=validation.missing,
            bootstrap_warnings=validation.warnings,
            review=review if isinstance(review, dict) else None,
            current_summary=current_summary,
        )


def list_sessions(limit: int = 20) -> list[SessionSummary]:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    candidates: list[tuple[str, str]] = []
    for root in SESSIONS_DIR.iterdir():
        metadata = read_json(root / "session.json", default=None)
        if isinstance(metadata, dict):
            candidates.append((str(metadata.get("updated_at") or ""), root.name))
    candidates.sort(reverse=True)
    return [get_session_summary(session_id) for _, session_id in candidates[:limit]]
