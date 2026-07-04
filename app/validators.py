from typing import Any


REQUIRED_BOOTSTRAP_KEYS = [
    "protagonist",
    "characters",
    "relationships",
    "knowledge",
    "story_plan",
    "current_state",
]


def validate_bootstrap_result(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in REQUIRED_BOOTSTRAP_KEYS:
        if key not in data:
            errors.append(f"missing key: {key}")

    characters = data.get("characters")
    if characters is not None and not isinstance(characters, dict):
        errors.append("characters must be object keyed by character_id")

    protagonist = data.get("protagonist")
    if protagonist and protagonist.get("id") not in (characters or {}):
        errors.append("protagonist.id must exist inside characters")

    return errors


def validate_scene_response(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if data.get("response_version") != "novella.scene_response.v1":
        errors.append("response_version must be novella.scene_response.v1")
    if "scene" not in data:
        errors.append("missing scene")
    if "proposed_updates" not in data:
        errors.append("missing proposed_updates")
    return errors
