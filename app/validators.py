from pathlib import Path
from typing import Any
import json
from jsonschema import Draft202012Validator


REQUIRED_BOOTSTRAP_KEYS = [
    "protagonist",
    "characters",
    "relationships",
    "knowledge",
    "story_plan",
    "current_state",
]


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


def validate_bootstrap_result(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    errors.extend(_validate_with_schema(data, "bootstrap_output.schema.json"))

    for key in REQUIRED_BOOTSTRAP_KEYS:
        if key not in data:
            errors.append(f"missing key: {key}")

    characters = data.get("characters")
    if characters is not None and not isinstance(characters, dict):
        errors.append("characters must be object keyed by character_id")

    protagonist = data.get("protagonist") or {}
    if protagonist and protagonist.get("id") not in (characters or {}):
        errors.append("protagonist.id must exist inside characters")

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
    return errors
