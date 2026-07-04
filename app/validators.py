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

    story_plan = data.get("story_plan") or {}
    status_slots = story_plan.get("status_slots") or []
    if len(status_slots) != 2:
        errors.append("story_plan.status_slots must contain exactly 2 story-specific slots")

    current_state = data.get("current_state") or {}
    status = current_state.get("status") or {}
    for key in ["hunger", "fatigue", "injuries", "emotional_state", "skills", "custom"]:
        if key not in status:
            errors.append(f"current_state.status missing key: {key}")
    if len(status.get("custom") or []) != 2:
        errors.append("current_state.status.custom must contain exactly 2 story-specific slots")

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
