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

CHARACTER_OBJECT_FIELDS = (
    "appearance",
    "voice",
    "personality",
    "goals",
    "work",
    "schedule",
)
CHARACTER_LIST_FIELDS = (
    "aliases",
    "values",
    "flaws",
    "fears",
    "boundaries",
    "skills",
    "past",
    "connections",
    "tags",
    "starting_knowledge",
    "initial_relationships",
)


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
    if part_type == BootstrapPartType.PROFILE:
        for field in ("naming", "presentation", "prose_style", "start"):
            if field in content and not isinstance(content[field], dict):
                raise HTTPException(
                    status_code=422,
                    detail=f"profile.{field} must be an object",
                )
        for field in ("genre", "tone"):
            if field in content and not isinstance(content[field], (str, list)):
                raise HTTPException(
                    status_code=422,
                    detail=f"profile.{field} must be text or a list",
                )
        if "boundaries" in content and not isinstance(content["boundaries"], (dict, list)):
            raise HTTPException(
                status_code=422,
                detail="profile.boundaries must be an object or a list",
            )
    if part_type == BootstrapPartType.CHARACTER:
        if part_id is None:
            raise HTTPException(status_code=422, detail="part_id is required for character")
        safe_id(part_id, "character_id")
        content_id = str(content.get("id") or content.get("character_id") or part_id)
        if content_id != part_id:
            raise HTTPException(status_code=422, detail="Character id does not match part_id")
        if not content.get("name"):
            raise HTTPException(status_code=422, detail="Character requires name")
        for field in CHARACTER_OBJECT_FIELDS:
            value = content.get(field)
            if not isinstance(value, dict):
                raise HTTPException(
                    status_code=422,
                    detail=f"character.{part_id}.{field} must be an object",
                )
            if field in {"appearance", "personality", "goals", "voice"} and not value:
                warnings.append(
                    f"Director must invent character.{part_id}.{field} before confirmation"
                )
        for field in CHARACTER_LIST_FIELDS:
            value = content.get(field)
            if not isinstance(value, list):
                raise HTTPException(
                    status_code=422,
                    detail=f"character.{part_id}.{field} must be a list",
                )
        for index, item in enumerate(content.get("starting_knowledge", [])):
            if not isinstance(item, dict):
                raise HTTPException(
                    status_code=422,
                    detail=f"character.{part_id}.starting_knowledge[{index}] must be an object",
                )
        for index, item in enumerate(content.get("initial_relationships", [])):
            if not isinstance(item, dict):
                raise HTTPException(
                    status_code=422,
                    detail=f"character.{part_id}.initial_relationships[{index}] must be an object",
                )
            value = item.get("value", 0)
            try:
                int(value)
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"character.{part_id}.initial_relationships[{index}].value "
                        "must be an integer"
                    ),
                ) from exc
    if part_type == BootstrapPartType.CURRENT:
        if "pov_state" in content and not isinstance(content["pov_state"], dict):
            raise HTTPException(status_code=422, detail="current.pov_state must be an object")
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

    for field in ("title", "genre", "tone", "pov_id", "start"):
        if "profile" not in missing and not profile.get(field):
            errors.append(f"profile.{field} must be invented and saved by the director")

    if "profile" not in missing and "boundaries" not in profile:
        errors.append("profile.boundaries must be saved; use an empty list when there are none")

    presentation = profile.get("presentation") or {}
    if not isinstance(presentation, dict):
        errors.append("profile.presentation must be an object")
    else:
        minimum = presentation.get("scene_body_min_chars")
        maximum = presentation.get("scene_body_max_chars")
        if not isinstance(minimum, int) or not isinstance(maximum, int):
            errors.append("profile.presentation scene-body limits are required")
        elif minimum < 500 or maximum > 12000 or minimum > maximum:
            errors.append("profile.presentation scene-body limits are invalid")
        guidance = presentation.get("guidance")
        if not isinstance(guidance, dict) or "enabled" not in guidance:
            errors.append("profile.presentation.guidance is required")
        for field in (
            "layout",
            "header_enabled",
            "dialogue_format",
            "footer_state",
            "footer_relationships",
            "footer_turn",
        ):
            if field not in presentation:
                errors.append(f"profile.presentation.{field} is required")

    naming = profile.get("naming") or {}
    if not isinstance(naming, dict):
        errors.append("profile.naming must be an object")
    else:
        for field in ("origin", "script", "avoid_russian_names"):
            if field not in naming:
                errors.append(f"profile.naming.{field} is required")

    prose_style = profile.get("prose_style") or {}
    if not isinstance(prose_style, dict):
        errors.append("profile.prose_style must be an object")
    else:
        for field in (
            "mode",
            "seriousness",
            "description_detail",
            "literary_density",
            "pace",
            "directorial_irony",
        ):
            if not prose_style.get(field):
                errors.append(f"profile.prose_style.{field} is required")

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
            errors.append(f"current.{field} must be invented and saved by the director")

    if "current" not in missing and not isinstance(current.get("pov_state"), dict):
        errors.append("current.pov_state must be an object")

    if review and _has_forbidden_key(review):
        errors.append("Public review contains hidden-canon keys")
    if "review" not in missing and not review:
        errors.append("review must be generated from the completed draft")

    for path in character_files:
        card = read_json(path, default={}) or {}
        if not card.get("name"):
            errors.append(f"character.{path.stem}.name is required")
        for field in ("appearance", "personality", "goals", "voice"):
            if not isinstance(card.get(field), dict) or not card.get(field):
                errors.append(
                    f"character.{path.stem}.{field} must be invented and saved by the director"
                )

    questionnaire = read_json(
        root / "bootstrap" / "questionnaire.json",
        default={"entries": []},
    ) or {"entries": []}
    questionnaire_entries = questionnaire.get("entries", [])
    last_entry = (
        questionnaire_entries[-1]
        if isinstance(questionnaire_entries, list)
        and questionnaire_entries
        and isinstance(questionnaire_entries[-1], dict)
        else {}
    )
    user_questions = [
        str(item).strip()
        for item in (last_entry.get("contradictions", []) or [])
        if str(item).strip()
    ]
    director_repairs = [
        *(f"Create missing bootstrap part: {name}" for name in missing),
        *errors,
    ]

    ready = not missing and not errors and not user_questions
    next_action = (
        "ask_user"
        if user_questions
        else "repair_bootstrap"
        if director_repairs
        else "show_review"
    )
    return BootstrapValidationResponse(
        ready=ready,
        missing=missing,
        errors=errors,
        warnings=warnings,
        character_ids=character_ids,
        director_repairs=director_repairs,
        user_questions=user_questions,
        next_action=next_action,
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
