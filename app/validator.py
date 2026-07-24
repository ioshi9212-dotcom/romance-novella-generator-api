from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.config import MAX_BOOTSTRAP_PART_CHARS, MAX_CHARACTER_CHARS, MAX_COMMIT_CHARS
from app.models import BootstrapPartType, BootstrapValidationResponse, CommitTurnRequest, TurnMode
from app.storage import compact_json_text, read_json, safe_id


PUBLIC_REVIEW_FORBIDDEN_KEYS = {
    "hidden_canon",
    "secret_truth",
    "secret_truths",
    "future_twist",
    "future_twists",
    "planned_betrayal",
    "planned_betrayals",
}


def _has_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in PUBLIC_REVIEW_FORBIDDEN_KEYS:
                return True
            if _has_forbidden_key(child):
                return True
    elif isinstance(value, list):
        return any(_has_forbidden_key(item) for item in value)
    return False


def validate_part_content(
    part_type: BootstrapPartType,
    part_id: str | None,
    content: dict[str, Any],
) -> list[str]:
    serialized = compact_json_text(content)
    limit = MAX_CHARACTER_CHARS if part_type == BootstrapPartType.CHARACTER else MAX_BOOTSTRAP_PART_CHARS
    if len(serialized) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"Bootstrap part is too large: {len(serialized)} > {limit}",
        )
    warnings: list[str] = []
    if part_type == BootstrapPartType.CHARACTER:
        assert part_id is not None
        safe_id(part_id, "character_id")
        content_id = str(content.get("id") or content.get("character_id") or part_id)
        if content_id != part_id:
            raise HTTPException(status_code=422, detail="Character id does not match part_id")
        if not content.get("name"):
            raise HTTPException(status_code=422, detail="Character requires name")
        for optional in ("appearance", "personality", "goals", "voice"):
            if not content.get(optional):
                warnings.append(f"character.{part_id}.{optional} is not specified")
    if part_type == BootstrapPartType.REVIEW and _has_forbidden_key(content):
        raise HTTPException(status_code=422, detail="Public review contains hidden-canon keys")
    return warnings


def validate_bootstrap(root: Path) -> BootstrapValidationResponse:
    draft = root / "bootstrap" / "draft"
    required = {
        "profile": draft / "profile.json",
        "lore": draft / "lore.json",
        "hidden_canon": draft / "hidden_canon.json",
        "plot": draft / "plot.json",
        "current": draft / "current.json",
        "review": draft / "review.json",
    }
    missing = [name for name, path in required.items() if not path.is_file()]
    errors: list[str] = []
    warnings: list[str] = []

    profile = read_json(required["profile"], default={}) or {}
    current = read_json(required["current"], default={}) or {}
    review = read_json(required["review"], default={}) or {}
    characters_dir = draft / "characters"
    character_files = sorted(characters_dir.glob("*.json")) if characters_dir.is_dir() else []
    character_ids = [path.stem for path in character_files]

    for field in ("title", "genre", "tone", "pov_id", "boundaries", "start"):
        if "profile" not in missing and not profile.get(field):
            errors.append(f"profile.{field} is required")

    pov_id = str(profile.get("pov_id") or "")
    if pov_id:
        try:
            safe_id(pov_id, "profile.pov_id")
        except HTTPException:
            errors.append("profile.pov_id is unsafe")
        if pov_id not in character_ids:
            errors.append("POV character card is missing")

    if not character_ids:
        errors.append("At least one character card is required")
    elif len(character_ids) == 1:
        warnings.append("Only the POV character exists; the story may need at least one NPC")

    for field in ("datetime", "location_id", "pov_state"):
        if "current" not in missing and not current.get(field):
            errors.append(f"current.{field} is required")

    if review and _has_forbidden_key(review):
        errors.append("Public review contains hidden-canon keys")

    for path in character_files:
        card = read_json(path, default={}) or {}
        if not card.get("name"):
            errors.append(f"character.{path.stem}.name is required")
        for optional in ("appearance", "personality", "goals", "voice"):
            if not card.get(optional):
                warnings.append(f"character.{path.stem}.{optional} is not specified")

    ready = not missing and not errors
    return BootstrapValidationResponse(
        ready=ready,
        missing=missing,
        errors=errors,
        warnings=warnings,
        character_ids=character_ids,
    )


def validate_commit_size(request: CommitTurnRequest) -> None:
    serialized = request.model_dump_json()
    if len(serialized) > MAX_COMMIT_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"Commit payload is too large: {len(serialized)} > {MAX_COMMIT_CHARS}",
        )


def validate_commit_semantics(mode: TurnMode, request: CommitTurnRequest) -> None:
    validate_commit_size(request)
    if mode == TurnMode.PLAY:
        if not request.scene_text.strip():
            raise HTTPException(status_code=422, detail="scene_text is required in play mode")
        if not request.scene_summary.strip():
            raise HTTPException(status_code=422, detail="scene_summary is required in play mode")
        if request.chronology_event is None:
            raise HTTPException(status_code=422, detail="chronology_event is required in play mode")
    elif request.scene_text.strip():
        raise HTTPException(status_code=422, detail="Technical and audit commits cannot contain a scene")
