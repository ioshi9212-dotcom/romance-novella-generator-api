from pathlib import Path
from typing import Any
import json
import re
from jsonschema import Draft202012Validator


REQUIRED_BOOTSTRAP_KEYS = [
    "protagonist",
    "characters",
    "relationships",
    "knowledge",
    "story_plan",
    "current_state",
]

CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
BANNED_RUSSIAN_NAME_PARTS = {
    "ivan", "petr", "peter", "sergey", "sergei", "alexey", "aleksey", "dmitry", "dimitri",
    "oleg", "egor", "yegor", "vladimir", "mikhail", "nikolai", "andrei", "andrey",
    "anastasia", "nastya", "anna", "anya", "ekaterina", "katya", "maria", "masha",
    "marina", "svetlana", "olga", "tatiana", "tatyana", "irina", "ivanov", "ivanova",
    "petrov", "petrova", "sidorov", "sidorova", "morozov", "morozova", "volkov", "volkova",
    "sokolov", "sokolova", "kuznetsov", "kuznetsova", "orlov", "orlova",
}


def _schema_path(filename: str) -> Path:
    return Path(__file__).resolve().parent.parent / "schemas" / filename


def _validate_with_schema(data: dict[str, Any], filename: str) -> list[str]:
    path = _schema_path(filename)
    if not path.exists():
        return [f"schema file not found: {filename}"]
    schema = json.loads(path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda error: list(error.path))
    result: list[str] = []
    for error in errors:
        location = ".".join(str(x) for x in error.path) or "root"
        result.append(f"{filename}:{location}: {error.message}")
    return result


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
        for character_id, card in characters.items():
            if isinstance(card, dict) and card.get("id") not in {None, character_id}:
                errors.append(f"characters.{character_id}.id must match its generated character_id key")

    protagonist = data.get("protagonist") or {}
    if protagonist and protagonist.get("id") not in (characters or {}):
        errors.append("protagonist.id must exist inside characters and use the generated character_id")
    if protagonist and "name" in protagonist:
        errors.extend(_validate_display_name(protagonist.get("name"), "protagonist"))

    story_plan = data.get("story_plan") or {}
    status_slots = story_plan.get("status_slots") or []
    if len(status_slots) != 2:
        errors.append("story_plan.status_slots must contain exactly 2 story-specific slots")

    current_state = data.get("current_state") or {}
    for key in ["date", "time", "location", "weather", "scene_state", "outfit", "inventory", "nearby_items"]:
        if key not in current_state:
            errors.append(f"current_state missing key: {key}")

    status = current_state.get("status") or {}
    for key in ["hunger", "fatigue", "injuries", "emotional_state", "skills", "custom"]:
        if key not in status:
            errors.append(f"current_state.status missing key: {key}")
    if len(status.get("custom") or []) != 2:
        errors.append("current_state.status.custom must contain exactly 2 story-specific slots")

    return errors


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
    header = scene.get("header") or {}
    if "player_name" in header:
        errors.extend(_validate_display_name(header.get("player_name"), "scene.header.player_name"))

    updates = data.get("proposed_updates") or {}
    for index, patch in enumerate(updates.get("knowledge_patches") or []):
        if not patch.get("source_in_scene"):
            errors.append(f"proposed_updates.knowledge_patches[{index}].source_in_scene is required")
        if not patch.get("reason"):
            errors.append(f"proposed_updates.knowledge_patches[{index}].reason is required")

    for index, patch in enumerate(updates.get("relationship_patches") or []):
        for key in ["pair_id", "change_type", "entry", "reason", "source_in_scene"]:
            if not patch.get(key):
                errors.append(f"proposed_updates.relationship_patches[{index}].{key} is required")

    for index, card in enumerate(updates.get("new_or_updated_characters") or []):
        if isinstance(card, dict) and "name" in card:
            errors.extend(_validate_display_name(card.get("name"), f"proposed_updates.new_or_updated_characters[{index}]"))

    return errors
