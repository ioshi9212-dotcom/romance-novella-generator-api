from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from app.models import (
    CreateSessionRequest,
    LegacyCreateSessionRequest,
    QuestionnaireRequest,
    SessionStatus,
    SessionSummary,
)
from app.questionnaire import new_questionnaire_document
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
RULES_VERSION = 2


def _new_session_id() -> str:
    return f"nov_{uuid4().hex}"


def _resume_code() -> str:
    return uuid4().hex[:12].upper()


def create_session(
    request: CreateSessionRequest | LegacyCreateSessionRequest,
) -> SessionSummary:
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
    initial_questionnaire = (
        QuestionnaireRequest(
            phase="initial",
            raw_answers=request.raw_answers,
            normalized=request.normalized,
            unknown_fields=request.unknown_fields,
            contradictions=request.contradictions,
        )
        if isinstance(request, CreateSessionRequest)
        else None
    )
    metadata = {
        "session_id": session_id,
        "resume_code": _resume_code(),
        "title": (request.title or "Новая новелла").strip(),
        "status": (
            SessionStatus.CLARIFICATION.value
            if initial_questionnaire is not None
            and initial_questionnaire.contradictions
            else SessionStatus.BUILDING.value
            if initial_questionnaire is not None
            else SessionStatus.QUESTIONNAIRE.value
        ),
        "schema_version": SCHEMA_VERSION,
        "rules_version": RULES_VERSION,
        "state_version": 0,
        "turn_number": 0,
        "questionnaire_confirmed": isinstance(request, CreateSessionRequest),
        "created_at": now,
        "updated_at": now,
    }
    atomic_write_json(root / "session.json", metadata)
    atomic_write_json(
        root / "bootstrap" / "questionnaire.json",
        new_questionnaire_document(
            initial_questionnaire,
            confirmed_questionnaire=(
                request.confirmed_questionnaire
                if isinstance(request, CreateSessionRequest)
                else None
            ),
        ),
    )
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
        questionnaire = read_json(
            root / "bootstrap" / "questionnaire.json",
            default={"entries": []},
        ) or {"entries": []}
        questionnaire_entries = questionnaire.get("entries", [])
        if not isinstance(questionnaire_entries, list):
            questionnaire_entries = []
        last_questionnaire_entry = (
            questionnaire_entries[-1]
            if questionnaire_entries and isinstance(questionnaire_entries[-1], dict)
            else {}
        )
        questionnaire_confirmation = questionnaire.get("confirmation", {})
        questionnaire_confirmed = (
            isinstance(questionnaire_confirmation, dict)
            and questionnaire_confirmation.get("status") == "confirmed"
        )
        metadata["questionnaire_confirmed"] = questionnaire_confirmed
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
            questionnaire_entry_count=len(questionnaire_entries),
            last_questionnaire_entry_id=last_questionnaire_entry.get("entry_id"),
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


def resume_session(resume_code: str) -> SessionSummary:
    normalized = resume_code.strip().upper()
    if len(normalized) not in {8, 12} or any(character not in "0123456789ABCDEF" for character in normalized):
        raise HTTPException(status_code=400, detail="Invalid resume code")
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    matches: list[str] = []
    for root in SESSIONS_DIR.iterdir():
        metadata = read_json(root / "session.json", default=None)
        if isinstance(metadata, dict) and str(metadata.get("resume_code") or "").upper() == normalized:
            matches.append(root.name)
    if not matches:
        raise HTTPException(status_code=404, detail="Resume code not found")
    if len(matches) > 1:
        raise HTTPException(status_code=409, detail="Resume code collision")
    return get_session_summary(matches[0])
