from pathlib import Path
from typing import Any
import json
import re
from jsonschema import Draft202012Validator

REQUIRED_BOOTSTRAP_KEYS = ["protagonist", "characters", "relationships", "knowledge", "story_plan", "current_state"]
CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
BANNED_RUSSIAN_NAME_PARTS = {"ivan", "petr", "peter", "sergey", "sergei", "alexey", "aleksey", "dmitry", "dimitri", "oleg", "egor", "yegor", "vladimir", "mikhail", "nikolai", "andrei", "andrey", "anastasia", "nastya", "anna", "anya", "ekaterina", "katya", "maria", "masha", "marina", "svetlana", "olga", "tatiana", "tatyana", "irina", "ivanov", "ivanova", "petrov", "petrova", "sidorov", "sidorova", "morozov", "morozova", "volkov", "volkova", "sokolov", "sokolova", "kuznetsov", "kuznetsova", "orlov", "orlova"}

MIN_SCENE_BODY_CHARS = 500
MIN_RENDERED_TEXT_CHARS = 1000
REQUIRED_TRUE_SAFETY_CHECKS = [
    "used_only_loaded_characters",
    "respected_knowledge_boundaries",
    "no_hidden_future_reveal",
    "no_major_player_character_choice",
    "respected_player_input_order",
    "showed_only_scene_relationships",
    "header_has_no_focus_or_active_list",
]
FORBIDDEN_HEADER_MARKERS = ["POV", "Фокус", "В сцене", "active_character_ids", "active ids"]


def _schema_path(filename: str) -> Path:
    return Path(__file__).resolve().parent.parent / "schemas" / filename


def _validate_with_schema(data: dict[str, Any], filename: str) -> list[str]:
    path = _schema_path(filename)
    if not path.exists():
        return [f"schema file not found: {filename}"]
    schema = json.loads(path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda error: list(error.path))
    return [f"{filename}:{'.'.join(str(x) for x in error.path) or 'root'}: {error.message}" for error in errors]


def _validate_display_name(name: Any, location: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(name, str) or not name.strip():
        errors.append(f"{location}.name must be a non-empty string")
        return errors
    stripped = name.strip()
    if CYRILLIC_RE.search(stripped):
        errors.append(f"{location}.name must use Latin script only, not Cyrillic: {stripped!r}")
    parts = {part.lower().strip("-_. '") for part in re.split(r"\s+", stripped) if part.strip()}
    banned = parts & BANNED_RUSSIAN_NAME_PARTS
    if banned:
        errors.append(f"{location}.name looks Russian/Slavic and is not allowed by naming rules: {stripped!r}")
    if len(stripped.split()) < 2:
        errors.append(f"{location}.name should include given name and surname, with given name and surname")
    return errors


def _validate_character_names(characters: Any, prefix: str = "characters") -> list[str]:
    errors: list[str] = []
    if not isinstance(characters, dict):
        return errors
    for character_id, card in characters.items():
        if isinstance(card, dict) and "name" in card:
            errors.extend(_validate_display_name(card.get("name"), f"{prefix}.{character_id}"))
    return errors


def _validate_not_placeholder(value: Any, location: str, errors: list[str]) -> None:
    text = str(value or "").strip().lower()
    placeholders = {"", "—", "-", "не указано", "старт", "стартовая локация", "начало истории", "будет уточняться", "сеттинг будет уточняться"}
    if text in placeholders:
        errors.append(f"{location} must be filled with story-specific content, not placeholder: {value!r}")


def validate_bootstrap_result(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    errors.extend(_validate_with_schema(data, "bootstrap_output.schema.json"))
    for key in REQUIRED_BOOTSTRAP_KEYS:
        if key not in data:
            errors.append(f"missing key: {key}")

    characters = data.get("characters")
    if characters is not None and not isinstance(characters, dict):
        errors.append("characters must be object keyed by generated character_id")
    errors.extend(_validate_character_names(characters))

    if isinstance(characters, dict):
        if not characters:
            errors.append("characters must contain at least the player character")
        for character_id, card in characters.items():
            if isinstance(card, dict) and card.get("id") not in {None, character_id}:
                errors.append(f"characters.{character_id}.id must match its generated character_id key")
            if isinstance(card, dict):
                _validate_not_placeholder(card.get("goal"), f"characters.{character_id}.goal", errors)
                _validate_not_placeholder(card.get("past_short"), f"characters.{character_id}.past_short", errors)

    protagonist = data.get("protagonist") or {}
    if protagonist and protagonist.get("id") not in (characters or {}):
        errors.append("protagonist.id must exist inside characters and use the generated character_id")
    if protagonist and "name" in protagonist:
        errors.extend(_validate_display_name(protagonist.get("name"), "protagonist"))

    story_plan = data.get("story_plan") or {}
    required_story_keys = ["genre", "language", "tone", "setting_summary", "main_premise", "protagonist_start", "player_goal", "central_conflict", "central_question", "opening_scene_intent", "act_structure", "character_arcs", "relationship_focus", "open_threads", "forbidden_drift", "current_story_position", "status_slots"]
    for key in required_story_keys:
        if key not in story_plan:
            errors.append(f"story_plan missing key: {key}")
    for key in ["setting_summary", "main_premise", "protagonist_start", "player_goal", "central_conflict", "central_question", "opening_scene_intent"]:
        _validate_not_placeholder(story_plan.get(key), f"story_plan.{key}", errors)
    if len(story_plan.get("status_slots") or []) != 2:
        errors.append("story_plan.status_slots must contain exactly 2 story-specific slots")

    current_state = data.get("current_state") or {}
    for key in ["date", "time", "location", "weather", "scene_state", "outfit", "inventory", "nearby_items"]:
        if key not in current_state:
            errors.append(f"current_state missing key: {key}")
    for key in ["time", "location", "weather", "scene_state", "outfit"]:
        _validate_not_placeholder(current_state.get(key), f"current_state.{key}", errors)

    status = current_state.get("status") or {}
    for key in ["hunger", "fatigue", "injuries", "emotional_state", "skills", "custom"]:
        if key not in status:
            errors.append(f"current_state.status missing key: {key}")
    if len(status.get("custom") or []) != 2:
        errors.append("current_state.status.custom must contain exactly 2 story-specific slots")
    return errors


def _header_block(rendered_text: str) -> str:
    delimiter = "━━━━━━━━━━━━━━━━━━━━"
    if delimiter in rendered_text:
        return rendered_text.split(delimiter, 1)[0]
    return rendered_text[:600]


def validate_scene_response(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    errors.extend(_validate_with_schema(data, "scene_response.schema.json"))
    if data.get("response_version") != "novella.scene_response.v1":
        errors.append("response_version must be novella.scene_response.v1")
    if "scene" not in data:
        errors.append("missing scene")
    if "proposed_updates" not in data:
        errors.append("missing proposed_updates")

    scene = data.get("scene") or {}
    body = scene.get("body") if isinstance(scene, dict) else ""
    rendered_text = scene.get("rendered_text") if isinstance(scene, dict) else ""

    if not isinstance(body, str) or len(body.strip()) < MIN_SCENE_BODY_CHARS:
        errors.append(f"scene.body must be a real scene body, at least {MIN_SCENE_BODY_CHARS} characters")
    if str(body).strip().lower() in {"debug_stub", "сцена сыграна.", "scene played."}:
        errors.append("scene.body must not be a stub or placeholder")

    if not isinstance(rendered_text, str) or len(rendered_text.strip()) < MIN_RENDERED_TEXT_CHARS:
        errors.append(f"scene.rendered_text must be full visible scene text, at least {MIN_RENDERED_TEXT_CHARS} characters")
    else:
        header = _header_block(rendered_text)
        for marker in FORBIDDEN_HEADER_MARKERS:
            if marker in header:
                errors.append(f"scene.rendered_text header must not contain technical/meta marker: {marker}")
        for required_marker in ["🎭", "🕒", "📍", "✦ Что можно сделать", "✦ Что можно сказать", "✦ Мысли", "✦ Состояние", "✦ Отношения"]:
            if required_marker not in rendered_text:
                errors.append(f"scene.rendered_text missing required visible block/marker: {required_marker}")

    safety_checks = data.get("safety_checks")
    if not isinstance(safety_checks, dict):
        errors.append("safety_checks must be an object")
    else:
        for key in REQUIRED_TRUE_SAFETY_CHECKS:
            if safety_checks.get(key) is not True:
                errors.append(f"safety_checks.{key} must be true")

    updates = data.get("proposed_updates") or {}
    for index, patch in enumerate(updates.get("knowledge_patches") or []):
        if not patch.get("character_id"):
            errors.append(f"proposed_updates.knowledge_patches[{index}].character_id is required")
        if not patch.get("source_in_scene"):
            errors.append(f"proposed_updates.knowledge_patches[{index}].source_in_scene is required")
        if not patch.get("reason"):
            errors.append(f"proposed_updates.knowledge_patches[{index}].reason is required")
    for index, patch in enumerate(updates.get("relationship_patches") or []):
        for key in ["pair_id", "change_type", "entry", "reason", "source_in_scene"]:
            if not patch.get(key):
                errors.append(f"proposed_updates.relationship_patches[{index}].{key} is required")
        pair_id = str(patch.get("pair_id") or "")
        if "__" not in pair_id or len([part for part in pair_id.split("__") if part]) != 2:
            errors.append(f"proposed_updates.relationship_patches[{index}].pair_id must look like a__b")
    for index, card in enumerate(updates.get("new_or_updated_characters") or []):
        if isinstance(card, dict) and "name" in card:
            errors.extend(_validate_display_name(card.get("name"), f"proposed_updates.new_or_updated_characters[{index}]"))
    return errors
