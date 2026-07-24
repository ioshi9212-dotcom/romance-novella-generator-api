from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from app.models import (
    BootstrapPartRequest,
    BootstrapPartType,
    BootstrapSaveResponse,
    BootstrapValidationResponse,
    QuestionnaireRequest,
    SessionStatus,
    SessionSummary,
)
from app.sessions import get_session_summary
from app.storage import (
    atomic_write_json,
    deep_merge,
    execute_transaction,
    json_text,
    read_json,
    recover_transactions,
    require_session,
    safe_id,
    session_lock,
    utc_now,
)
from app.validator import validate_bootstrap, validate_part_content


def _metadata(root: Any) -> dict[str, Any]:
    return read_json(root / "session.json", default={}) or {}


def _save_metadata(root: Any, metadata: dict[str, Any]) -> None:
    metadata["updated_at"] = utc_now()
    atomic_write_json(root / "session.json", metadata)


def save_questionnaire(session_id: str, request: QuestionnaireRequest) -> SessionSummary:
    root = require_session(session_id)
    with session_lock(root):
        recover_transactions(root)
        metadata = _metadata(root)
        if metadata.get("status") in {SessionStatus.ACTIVE.value, SessionStatus.ARCHIVED.value}:
            raise HTTPException(status_code=409, detail="Questionnaire is closed")
        questionnaire_path = root / "bootstrap" / "questionnaire.json"
        questionnaire = read_json(questionnaire_path, default={"entries": []}) or {"entries": []}
        entries = questionnaire.setdefault("entries", [])
        entries.append({"saved_at": utc_now(), **request.model_dump()})
        atomic_write_json(questionnaire_path, questionnaire)
        metadata["status"] = (
            SessionStatus.CLARIFICATION.value
            if request.phase == "initial"
            else SessionStatus.BUILDING.value
        )
        _save_metadata(root, metadata)
    return get_session_summary(session_id)


def _part_path(root: Any, request: BootstrapPartRequest) -> Any:
    draft = root / "bootstrap" / "draft"
    if request.part_type == BootstrapPartType.CHARACTER:
        assert request.part_id is not None
        return draft / "characters" / f"{safe_id(request.part_id, 'character_id')}.json"
    return draft / f"{request.part_type.value}.json"


def save_bootstrap_part(session_id: str, request: BootstrapPartRequest) -> BootstrapSaveResponse:
    root = require_session(session_id)
    warnings = validate_part_content(request.part_type, request.part_id, request.content)
    with session_lock(root):
        recover_transactions(root)
        metadata = _metadata(root)
        if metadata.get("status") == SessionStatus.ACTIVE.value:
            raise HTTPException(status_code=409, detail="Bootstrap is already confirmed")
        path = _part_path(root, request)
        atomic_write_json(path, request.content)
        metadata["status"] = (
            SessionStatus.REVIEW_PENDING.value
            if request.part_type == BootstrapPartType.REVIEW
            else SessionStatus.BUILDING.value
        )
        if request.part_type == BootstrapPartType.PROFILE and request.content.get("title"):
            metadata["title"] = str(request.content["title"])[:160]
        _save_metadata(root, metadata)
    return BootstrapSaveResponse(
        status="saved",
        part_type=request.part_type,
        part_id=request.part_id,
        size_chars=len(json_text(request.content)),
        warnings=warnings,
    )


def validate_session_bootstrap(session_id: str) -> BootstrapValidationResponse:
    root = require_session(session_id)
    with session_lock(root):
        recover_transactions(root)
        return validate_bootstrap(root)


def _initial_relationships(cards: dict[str, dict[str, Any]]) -> dict[str, Any]:
    pairs: dict[str, Any] = {}
    for character_id, card in cards.items():
        for item in card.get("initial_relationships", []) or []:
            if not isinstance(item, dict):
                continue
            target = str(item.get("to_character_id") or "")
            metric = str(item.get("metric") or "")
            if not target or target not in cards or not metric or target == character_id:
                continue
            pair_id = "__".join(sorted((character_id, target)))
            pair = pairs.setdefault(pair_id, {"directions": {}, "history": []})
            direction = f"{character_id}->{target}"
            direction_data = pair["directions"].setdefault(direction, {"metrics": {}})
            direction_data["metrics"][metric] = max(0, min(100, int(item.get("value", 0))))
    return {"pairs": pairs}


def confirm_bootstrap(session_id: str) -> SessionSummary:
    root = require_session(session_id)
    with session_lock(root):
        recover_transactions(root)
        metadata = _metadata(root)
        if metadata.get("status") == SessionStatus.ACTIVE.value:
            return SessionSummary(**metadata)
        validation = validate_bootstrap(root)
        if not validation.ready:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "bootstrap_not_ready",
                    "missing": validation.missing,
                    "errors": validation.errors,
                    "warnings": validation.warnings,
                },
            )
        draft = root / "bootstrap" / "draft"
        writes: dict[str, str] = {}
        for name in ("profile", "lore", "hidden_canon", "plot", "current"):
            value = read_json(draft / f"{name}.json", default={}) or {}
            writes[f"state/{name}.json"] = json_text(value)

        cards: dict[str, dict[str, Any]] = {}
        index: dict[str, Any] = {"characters": {}}
        for path in sorted((draft / "characters").glob("*.json")):
            card = read_json(path, default={}) or {}
            character_id = path.stem
            cards[character_id] = card
            index["characters"][character_id] = {
                "id": character_id,
                "name": card.get("name"),
                "aliases": card.get("aliases", []),
                "tags": card.get("tags", []),
            }
            writes[f"state/characters/{character_id}.json"] = json_text(card)
            knowledge = {
                "character_id": character_id,
                "entries": card.get("starting_knowledge", []) or [],
            }
            writes[f"state/knowledge/{character_id}.json"] = json_text(knowledge)
        writes["state/characters/index.json"] = json_text(index)
        writes["state/relationships.json"] = json_text(_initial_relationships(cards))
        writes["state/chronology.jsonl"] = ""
        writes["state/scene_history.jsonl"] = ""

        metadata = deep_merge(
            metadata,
            {
                "status": SessionStatus.ACTIVE.value,
                "state_version": 1,
                "turn_number": 0,
                "updated_at": utc_now(),
                "confirmed_at": utc_now(),
            },
        )
        writes["session.json"] = json_text(metadata)
        execute_transaction(root, f"bootstrap_{uuid4().hex}", writes)
    return get_session_summary(session_id)
