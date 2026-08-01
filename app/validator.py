from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.config import (
    MAX_BOOTSTRAP_PART_CHARS,
    MAX_CHARACTER_CHARS,
    MAX_COMMIT_CHARS,
    ROOT_DIR,
)
from app.models import BootstrapPartType, BootstrapValidationResponse, CommitTurnRequest, TurnMode
from app.storage import compact_json_text, deep_merge, read_json, safe_id


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


def _normalized_leaves(value: Any, path: str = "questionnaire.normalized") -> list[tuple[str, Any]]:
    leaves: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            leaves.extend(_normalized_leaves(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            leaves.extend(_normalized_leaves(child, f"{path}[{index}]"))
    elif value is not None and value != "":
        leaves.append((path, value))
    return leaves


def _normalized_text(value: str) -> str:
    return " ".join(value.casefold().replace("ё", "е").split())


def _contains_normalized_value(source: Any, expected: Any) -> bool:
    if isinstance(source, dict):
        return any(_contains_normalized_value(child, expected) for child in source.values())
    if isinstance(source, list):
        return any(_contains_normalized_value(child, expected) for child in source)
    if isinstance(expected, bool):
        return isinstance(source, bool) and source is expected
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return (
            isinstance(source, (int, float))
            and not isinstance(source, bool)
            and source == expected
        )
    if isinstance(expected, str) and isinstance(source, str):
        expected_text = _normalized_text(expected)
        source_text = _normalized_text(source)
        if expected_text == source_text:
            return True
        return len(expected_text) >= 4 and expected_text in source_text
    return source == expected


def _unmatched_questionnaire_facts(
    normalized: Any,
    state_parts: list[Any],
) -> list[str]:
    if not isinstance(normalized, dict):
        return []
    unmatched: list[str] = []
    for path, value in _normalized_leaves(normalized):
        if not any(_contains_normalized_value(part, value) for part in state_parts):
            rendered = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            unmatched.append(
                f"{path}={rendered} must be represented in a bootstrap state part"
            )
    return unmatched


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
    lore = read_json(required["lore"], default={}) or {}
    hidden_canon = read_json(required["hidden_canon"], default={}) or {}
    plot = read_json(required["plot"], default={}) or {}
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

    if "lore" not in missing:
        if not str(lore.get("summary") or "").strip():
            errors.append("lore.summary must be invented and saved by the director")
        if not isinstance(lore.get("world_rules"), list) or not lore.get("world_rules"):
            errors.append("lore.world_rules must contain at least one concrete rule")
        if not isinstance(lore.get("locations"), (dict, list)) or not lore.get("locations"):
            errors.append("lore.locations must contain the opening location")
        if not isinstance(lore.get("facts"), list):
            errors.append("lore.facts must be a list")

    if "hidden_canon" not in missing:
        for field in ("core_truths", "false_versions", "causal_chain", "constraints", "facts"):
            if not isinstance(hidden_canon.get(field), list):
                errors.append(f"hidden_canon.{field} must be a list")
        for field in ("core_truths", "causal_chain", "constraints"):
            if isinstance(hidden_canon.get(field), list) and not hidden_canon.get(field):
                errors.append(
                    f"hidden_canon.{field} must be invented and saved by the director"
                )

    if "plot" not in missing:
        lines = plot.get("lines")
        if not isinstance(lines, (dict, list)) or not lines:
            errors.append("plot.lines must contain at least one active story line")
        if not isinstance(plot.get("clocks"), (dict, list)):
            errors.append("plot.clocks must be an object or a list")
        if not isinstance(plot.get("npc_plans"), list) or not plot.get("npc_plans"):
            errors.append("plot.npc_plans must contain at least one autonomous NPC plan")

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
        elif (
            not isinstance(guidance.get("items_per_section"), int)
            or not 1 <= guidance["items_per_section"] <= 10
        ):
            errors.append("profile.presentation.guidance.items_per_section is invalid")
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

    pov_control = profile.get("pov_control") or {}
    if not isinstance(pov_control, dict):
        errors.append("profile.pov_control must be an object")
    else:
        for field in (
            "allow_routine_actions",
            "allow_involuntary_reactions",
            "allow_minor_dialogue",
            "require_pov_presence",
            "user_only_consequential_choices",
        ):
            if not isinstance(pov_control.get(field), bool):
                errors.append(f"profile.pov_control.{field} must be a boolean")

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

    for field in (
        "datetime",
        "location_id",
        "location_label",
        "season_or_period",
        "weather",
        "scene_condition",
        "pov_state",
    ):
        if "current" not in missing and not current.get(field):
            errors.append(f"current.{field} must be invented and saved by the director")

    if "current" not in missing and not isinstance(current.get("pov_state"), dict):
        errors.append("current.pov_state must be an object")
    if "current" not in missing:
        for field in (
            "clothing",
            "inventory",
            "present_character_ids",
            "nearby_character_ids",
            "scheduled_character_ids",
        ):
            if not isinstance(current.get(field), list):
                errors.append(f"current.{field} must be a list")

    if review and _has_forbidden_key(review):
        errors.append("Public review contains hidden-canon keys")
    if "review" not in missing and not review:
        errors.append("review must be generated from the completed draft")

    for path in character_files:
        card = read_json(path, default={}) or {}
        if not card.get("name"):
            errors.append(f"character.{path.stem}.name is required")
        for field in CHARACTER_OBJECT_FIELDS:
            if not isinstance(card.get(field), dict) or not card.get(field):
                errors.append(
                    f"character.{path.stem}.{field} must be invented and saved by the director"
                )
        for field in ("values", "flaws", "skills", "past", "tags"):
            if not isinstance(card.get(field), list) or not card.get(field):
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
    if not isinstance(questionnaire_entries, list) or not questionnaire_entries:
        errors.append("questionnaire must be saved before bootstrap confirmation")
    state_parts: list[Any] = [
        profile,
        lore,
        hidden_canon,
        plot,
        current,
        *(read_json(path, default={}) or {} for path in character_files),
    ]
    errors.extend(
        _unmatched_questionnaire_facts(
            last_entry.get("normalized", {}),
            state_parts,
        )
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
    else:
        if request.scene_text.strip():
            raise HTTPException(
                status_code=422,
                detail="Technical and audit commits cannot contain a scene",
            )
        if request.time_advance_minutes:
            raise HTTPException(
                status_code=422,
                detail="Technical and audit commits cannot advance story time",
            )
        if "datetime" in request.current_patch:
            raise HTTPException(
                status_code=422,
                detail="Technical and audit commits cannot patch current.datetime",
            )
        if request.chronology_event is not None:
            raise HTTPException(
                status_code=422,
                detail="Technical and audit commits cannot append a story chronology event",
            )


def _find_line(lines: list[str], prefix: str) -> int | None:
    for index, line in enumerate(lines):
        if line.strip().startswith(prefix):
            return index
    return None


def _guidance_item_count(lines: list[str], start: int, end: int) -> int:
    item_pattern = re.compile(r"^(?:[-*•]\s+|\d+[.)]\s+)")
    return sum(
        1
        for line in lines[start:end]
        if item_pattern.match(line.strip())
    )


def validate_scene_presentation(
    root: Path,
    request: CommitTurnRequest,
    next_turn_number: int,
) -> None:
    defaults = read_json(ROOT_DIR / "templates" / "profile.json", default={}) or {}
    stored = read_json(root / "state" / "profile.json", default={}) or {}
    profile = deep_merge(defaults, stored)
    presentation = profile.get("presentation", {}) or {}
    if not isinstance(presentation, dict):
        raise HTTPException(status_code=409, detail="Stored profile.presentation is invalid")

    lines = request.scene_text.rstrip().splitlines()
    errors: list[str] = []
    layout = str(presentation.get("layout") or "standard_novella")
    header_enabled = bool(presentation.get("header_enabled", True))
    header_end = 0

    if layout == "standard_novella" and header_enabled:
        required_prefixes = ("🎭 ", "📅 ", "🌦️ Погода:", "⚙️ Состояние сцены:", "✦ ", "🧥 Одежда:", "◈ Инвентарь:")
        positions = [_find_line(lines, prefix) for prefix in required_prefixes]
        for prefix, position in zip(required_prefixes, positions, strict=True):
            if position is None:
                errors.append(f"missing scene line: {prefix.strip()}")
        known_positions = [position for position in positions if position is not None]
        if known_positions and known_positions != sorted(known_positions):
            errors.append("scene header lines are in the wrong order")
        title = str(profile.get("title") or "").strip()
        if title and (not lines or not lines[0].strip().startswith(f"🎭 {title} ·")):
            errors.append("the first line must contain the stored title and story period")
        if positions[-1] is not None:
            header_end = positions[-1] + 1

        current = read_json(root / "state" / "current.json", default={}) or {}
        location_label = str(current.get("location_label") or "").strip()
        date_line_position = positions[1]
        if location_label and date_line_position is not None:
            if location_label not in lines[date_line_position]:
                errors.append("the location line must use current.location_label")
        pov_id = str(profile.get("pov_id") or "")
        pov_card = read_json(
            root / "state" / "characters" / f"{pov_id}.json",
            default={},
        ) or {}
        pov_name = str(pov_card.get("name") or "").strip()
        pov_line_position = positions[4]
        if pov_name and pov_line_position is not None:
            if not lines[pov_line_position].strip().startswith(f"✦ {pov_name} ·"):
                errors.append("the POV state line must use the stored POV name")

    guidance = presentation.get("guidance", {}) or {}
    guidance_enabled = isinstance(guidance, dict) and bool(guidance.get("enabled", False))
    guidance_headings = (
        "Что я могу сделать",
        "Что я могу сказать",
        "Что я могу подумать",
    )
    guidance_positions = [_find_line(lines, heading) for heading in guidance_headings]
    footer_prefixes = ("Состояние:", "Отношения:", "Ход:")
    footer_positions = [_find_line(lines, prefix) for prefix in footer_prefixes]

    if guidance_enabled:
        try:
            expected_items = int(guidance.get("items_per_section", 3) or 3)
        except (TypeError, ValueError):
            expected_items = 3
            errors.append("guidance.items_per_section must be an integer")
        for heading, position in zip(guidance_headings, guidance_positions, strict=True):
            if position is None or lines[position].strip() != heading:
                errors.append(f"missing exact guidance heading: {heading}")
        if all(position is not None for position in guidance_positions):
            boundaries = [
                guidance_positions[1],
                guidance_positions[2],
                next(
                    (
                        position
                        for position in footer_positions
                        if position is not None and position > guidance_positions[2]
                    ),
                    len(lines),
                ),
            ]
            for heading, start, end in zip(
                guidance_headings,
                guidance_positions,
                boundaries,
                strict=True,
            ):
                assert start is not None
                if _guidance_item_count(lines, start + 1, int(end)) != expected_items:
                    errors.append(
                        f"{heading} must contain exactly {expected_items} list items"
                    )
    elif any(position is not None for position in guidance_positions):
        errors.append("guidance blocks are disabled in profile.presentation")

    footer_requirements = (
        ("footer_state", "Состояние:", footer_positions[0]),
        ("footer_relationships", "Отношения:", footer_positions[1]),
        ("footer_turn", "Ход:", footer_positions[2]),
    )
    for setting, prefix, position in footer_requirements:
        enabled = bool(presentation.get(setting, True))
        if enabled and position is None:
            errors.append(f"missing footer line: {prefix}")
        if not enabled and position is not None:
            errors.append(f"footer line is disabled: {prefix}")
    if presentation.get("footer_turn", True) and footer_positions[2] is not None:
        if lines[footer_positions[2]].strip() != f"Ход: {next_turn_number}":
            errors.append(f"turn footer must be exactly: Ход: {next_turn_number}")

    body_end_candidates = [
        position
        for position in (*guidance_positions, *footer_positions)
        if position is not None and position >= header_end
    ]
    body_end = min(body_end_candidates) if body_end_candidates else len(lines)
    body = "\n".join(lines[header_end:body_end]).strip()
    try:
        minimum = int(presentation.get("scene_body_min_chars", 1500) or 1500)
        maximum = int(presentation.get("scene_body_max_chars", 2500) or 2500)
    except (TypeError, ValueError):
        minimum, maximum = 1500, 2500
        errors.append("scene body limits must be integers")
    if len(body) < minimum or len(body) > maximum:
        errors.append(
            f"scene body length must be {minimum}-{maximum} characters; got {len(body)}"
        )

    if errors:
        raise HTTPException(
            status_code=422,
            detail={"code": "scene_format_invalid", "errors": errors},
        )


def validate_audit_requirements(
    mode: TurnMode,
    request: CommitTurnRequest,
    packet: dict[str, Any],
) -> None:
    if not packet.get("audit_due"):
        return
    updates = request.audit_updates
    errors: list[str] = []
    if updates.get("continuity_checked") is not True:
        errors.append("audit_updates.continuity_checked must be true")
    if updates.get("chronology_checked") is not True:
        errors.append("audit_updates.chronology_checked must be true")
    checked_ids = updates.get("checked_character_ids")
    required_ids = {str(value) for value in packet.get("character_ids", [])}
    if not isinstance(checked_ids, list) or not required_ids.issubset(
        {str(value) for value in (checked_ids or [])}
    ):
        errors.append("audit_updates.checked_character_ids must include every session character")
    for field in ("issues", "repairs"):
        if not isinstance(updates.get(field), list):
            errors.append(f"audit_updates.{field} must be a list")
    if errors:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "continuity_audit_required",
                "mode": mode.value,
                "errors": errors,
            },
        )
