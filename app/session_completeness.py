from __future__ import annotations

from typing import Any

from app.models import CreateSessionRequest


_PLACEHOLDERS = {
    "",
    "-",
    "—",
    "...",
    "?",
    "none",
    "null",
    "tbd",
    "todo",
    "unknown",
    "не задано",
    "неизвестно",
    "не указано",
    "позже",
    "потом",
}


def _normalise(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().replace("ё", "е").split())


def _meaningful(value: Any) -> bool:
    if isinstance(value, str):
        return _normalise(value) not in _PLACEHOLDERS
    if isinstance(value, dict):
        return any(_meaningful(item) for item in value.values())
    if isinstance(value, list):
        return any(_meaningful(item) for item in value)
    return value is not None


def _text_chars(value: Any) -> int:
    if isinstance(value, str):
        return len(value.strip()) if _meaningful(value) else 0
    if isinstance(value, dict):
        return sum(_text_chars(item) for item in value.values())
    if isinstance(value, list):
        return sum(_text_chars(item) for item in value)
    return 0


def _require_keys(
    value: Any,
    *,
    label: str,
    meaningful: tuple[str, ...] = (),
    lists: tuple[str, ...] = (),
    issues: list[str],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        issues.append(f"{label} must be an object")
        return {}
    for key in meaningful:
        if key not in value or not _meaningful(value.get(key)):
            issues.append(f"{label}.{key} is missing or empty")
    for key in lists:
        if key not in value or not isinstance(value.get(key), list):
            issues.append(f"{label}.{key} must be an explicit array")
    return value


def _validate_novel(request: CreateSessionRequest, issues: list[str]) -> None:
    novel = _require_keys(
        request.novel,
        label="novel",
        meaningful=(
            "title",
            "genre",
            "tone",
            "style",
            "pov_character_id",
            "narration",
            "scene_length_chars",
        ),
        lists=("player_constraints", "content_constraints"),
        issues=issues,
    )
    if "choices_enabled" not in novel or not isinstance(
        novel.get("choices_enabled"), bool
    ):
        issues.append("novel.choices_enabled must be true or false")
    limits = novel.get("scene_length_chars")
    if isinstance(limits, dict):
        minimum = limits.get("min")
        maximum = limits.get("max")
        if not isinstance(minimum, int) or minimum < 1:
            issues.append("novel.scene_length_chars.min must be a positive integer")
        if not isinstance(maximum, int) or maximum < 1:
            issues.append("novel.scene_length_chars.max must be a positive integer")
        if isinstance(minimum, int) and isinstance(maximum, int) and maximum < minimum:
            issues.append("novel.scene_length_chars.max must not be below min")
        if not _meaningful(limits.get("scope")):
            issues.append("novel.scene_length_chars.scope is missing or empty")


def _validate_setup_source(
    request: CreateSessionRequest,
    *,
    character_ids: set[str],
    location_ids: set[str],
    issues: list[str],
) -> None:
    source = request.setup_source
    if source is None:
        issues.append("setup_source is required and must keep the player's exact setup wording")
        return
    if sum(_text_chars(message) for message in source.messages) < 20:
        issues.append("setup_source.messages is too short to contain the confirmed setup")

    expected_player_ids = {
        item.character_id for item in request.characters if item.card.origin == "player"
    }
    supplied_player_ids = set(source.expected_player_character_ids)
    if supplied_player_ids != expected_player_ids:
        issues.append(
            "setup_source.expected_player_character_ids must exactly match all player characters"
        )
    supplied_location_ids = set(source.expected_location_ids)
    if supplied_location_ids != location_ids:
        issues.append(
            "setup_source.expected_location_ids must exactly match all stored starting locations"
        )

    mapped_paths = [
        path.strip()
        for row in source.coverage
        for path in row.stored_in
        if path.strip()
    ]
    simple_roots = {
        "novel",
        "hidden_lore",
        "plot_state",
        "director_plan",
        "world_state",
        "scene_state",
    }
    for path in mapped_paths:
        parts = path.split(".")
        root = parts[0]
        valid = root in simple_roots
        if root == "characters" and len(parts) >= 2:
            valid = parts[1] in character_ids
        elif root == "locations" and len(parts) >= 2:
            valid = parts[1] in location_ids
        elif root == "objects" and len(parts) >= 2:
            valid = parts[1] in {item.object_id for item in request.objects}
        if not valid:
            issues.append(f"setup_source coverage contains unknown state path {path}")

    for character_id in sorted(expected_player_ids):
        if not any(path.startswith(f"characters.{character_id}.") for path in mapped_paths):
            issues.append(
                f"setup_source coverage does not map player character {character_id}"
            )
    for location_id in sorted(location_ids):
        if not any(path.startswith(f"locations.{location_id}.") for path in mapped_paths):
            issues.append(f"setup_source coverage does not map location {location_id}")


def _validate_story_state(
    request: CreateSessionRequest,
    *,
    character_ids: set[str],
    location_ids: set[str],
    issues: list[str],
) -> None:
    hidden_lore = _require_keys(
        request.hidden_lore,
        label="hidden_lore",
        lists=(
            "facts",
            "secrets",
            "reveal_conditions",
            "false_versions_in_world",
            "protected_until",
        ),
        issues=issues,
    )
    if not any(
        _meaningful(hidden_lore.get(key))
        for key in ("facts", "secrets", "false_versions_in_world")
    ):
        issues.append("hidden_lore needs at least one concrete director-only fact")

    plot_state = _require_keys(
        request.plot_state,
        label="plot_state",
        lists=(
            "active_lines",
            "open_threads",
            "pending_consequences",
            "foreshadowing",
            "resolved_history",
            "next_pressure_points",
        ),
        issues=issues,
    )
    if not any(
        _meaningful(plot_state.get(key))
        for key in ("active_lines", "open_threads", "next_pressure_points")
    ):
        issues.append("plot_state needs an active line, open thread or next pressure point")

    world = _require_keys(
        request.world_state,
        label="world_state",
        meaningful=("story_datetime", "global_situation", "character_whereabouts"),
        lists=(
            "global_situation",
            "character_whereabouts",
            "offscreen_actions",
            "active_dangers",
            "location_availability",
        ),
        issues=issues,
    )
    whereabouts = world.get("character_whereabouts", [])
    mapped_characters: set[str] = set()
    if isinstance(whereabouts, list):
        for index, item in enumerate(whereabouts):
            item = _require_keys(
                item,
                label=f"world_state.character_whereabouts.{index}",
                meaningful=("character_id", "location_id"),
                issues=issues,
            )
            character_id = str(item.get("character_id", ""))
            location_id = str(item.get("location_id", ""))
            if character_id:
                mapped_characters.add(character_id)
                if character_id not in character_ids:
                    issues.append(
                        f"world_state.character_whereabouts.{index}.character_id is unknown"
                    )
            if location_id and location_id not in location_ids:
                issues.append(
                    f"world_state.character_whereabouts.{index}.location_id is unknown"
                )
    for character_id in sorted(character_ids - mapped_characters):
        issues.append(f"world_state has no whereabouts for {character_id}")


def _validate_director_plan(
    request: CreateSessionRequest,
    *,
    character_ids: set[str],
    pov_character_id: str,
    issues: list[str],
) -> None:
    plan = request.director_plan.model_dump(mode="json")
    if not any(_meaningful(item) for item in plan.get("active_threads", [])):
        issues.append("director_plan.active_threads needs at least one concrete thread")
    if not any(_meaningful(item) for item in plan.get("character_agendas", [])):
        issues.append("director_plan.character_agendas needs at least one concrete agenda")
    for index, thread in enumerate(plan.get("active_threads", [])):
        _require_keys(
            thread,
            label=f"director_plan.active_threads.{index}",
            meaningful=("thread_id", "current_question", "current_pressure", "status"),
            issues=issues,
        )

    agenda_ids: set[str] = set()
    for index, agenda in enumerate(plan.get("character_agendas", [])):
        agenda = _require_keys(
            agenda,
            label=f"director_plan.character_agendas.{index}",
            meaningful=("character_id", "current_goal", "next_plausible_action"),
            lists=("conditions",),
            issues=issues,
        )
        character_id = str(agenda.get("character_id", ""))
        if character_id:
            agenda_ids.add(character_id)
            if character_id not in character_ids:
                issues.append(
                    f"director_plan.character_agendas.{index}.character_id is unknown"
                )

    required_agendas = {
        item.character_id
        for item in request.characters
        if item.character_id != pov_character_id
        and item.card.record_status == "active"
        and item.card.story_status != "retired"
    }
    for character_id in sorted(required_agendas - agenda_ids):
        issues.append(f"director_plan has no agenda for {character_id}")


def _validate_scene_and_characters(
    request: CreateSessionRequest,
    *,
    character_ids: set[str],
    location_ids: set[str],
    pov_character_id: str,
    issues: list[str],
) -> None:
    scene = _require_keys(
        request.scene_state,
        label="scene_state",
        meaningful=(
            "scene_id",
            "story_datetime",
            "location_id",
            "zone",
            "present_character_ids",
            "lighting",
            "weather",
            "continue_from",
        ),
        lists=(
            "present_character_ids",
            "entered_character_ids",
            "left_character_ids",
            "positions",
            "important_objects",
            "clothing",
            "doors_and_windows",
            "active_sounds",
            "unfinished_actions",
        ),
        issues=issues,
    )
    if scene.get("turn_number") != 0:
        issues.append("scene_state.turn_number must be 0 when a new session is created")
    present_ids = scene.get("present_character_ids", [])
    if isinstance(present_ids, list):
        unknown_present = sorted({str(item) for item in present_ids} - character_ids)
        for character_id in unknown_present:
            issues.append(f"scene_state contains unknown character {character_id}")
        if pov_character_id and pov_character_id not in present_ids:
            issues.append("scene_state.present_character_ids must include the POV character")
    scene_location = str(scene.get("location_id", ""))
    if scene_location and scene_location not in location_ids:
        issues.append("scene_state.location_id is not present in locations")
    if scene.get("story_datetime") != request.world_state.get("story_datetime"):
        issues.append("scene_state.story_datetime must match world_state.story_datetime")

    minimum_card_chars = {
        "noticeable": 80,
        "recurring": 180,
        "important": 300,
        "player_defined": 350,
    }
    for index, character in enumerate(request.characters):
        character_id = character.character_id
        card = character.card.model_dump(mode="json")
        minimum = minimum_card_chars[character.card.card_level]
        if _text_chars(card) < minimum:
            issues.append(
                f"characters.{index}.card is too shallow for {character.card.card_level}"
            )

        current = _require_keys(
            character.current_state,
            label=f"characters.{index}.current_state",
            meaningful=(
                "character_id",
                "current_location_id",
                "clothing",
                "current_goal",
                "nearest_intention",
                "offscreen_activity",
                "last_action",
            ),
            lists=("physical_state", "clothing", "carried_object_ids"),
            issues=issues,
        )
        if current.get("character_id") != character_id:
            issues.append(f"characters.{index}.current_state.character_id does not match")
        current_location = str(current.get("current_location_id", ""))
        if current_location and current_location not in location_ids:
            issues.append(
                f"characters.{index}.current_state.current_location_id is unknown"
            )
        for key in ("available_now", "present_in_scene"):
            if key not in current or not isinstance(current.get(key), bool):
                issues.append(f"characters.{index}.current_state.{key} must be true or false")
        if current.get("last_updated_turn") != 0:
            issues.append(
                f"characters.{index}.current_state.last_updated_turn must be 0"
            )
        expected_present = character_id in present_ids if isinstance(present_ids, list) else False
        if isinstance(current.get("present_in_scene"), bool) and (
            current["present_in_scene"] != expected_present
        ):
            issues.append(
                f"characters.{index}.current_state.present_in_scene disagrees with scene_state"
            )

        relationships = character.relationships.model_dump(mode="json")
        if relationships.get("owner_character_id") != character_id:
            issues.append(f"characters.{index}.relationships.owner_character_id does not match")
        for relation_index, relation in enumerate(relationships.get("relations", [])):
            target_id = str(relation.get("target_character_id", ""))
            if target_id not in character_ids:
                issues.append(
                    f"characters.{index}.relationships.relations.{relation_index} "
                    "target is unknown"
                )

        knowledge = _require_keys(
            character.knowledge,
            label=f"characters.{index}.knowledge",
            meaningful=("character_id",),
            lists=("entries", "wrong_beliefs"),
            issues=issues,
        )
        if knowledge.get("character_id") != character_id:
            issues.append(f"characters.{index}.knowledge.character_id does not match")


def create_session_completeness_issues(request: CreateSessionRequest) -> list[str]:
    """Return mechanical signs that a current createSession payload was abbreviated.

    Legacy Action schemas remain accepted by the runtime. Contract 2.0 is the current schema and
    must contain the full initial state; otherwise Railway must refuse to call the novella ready.
    """

    if request.runtime_contract_version != "2.0":
        return []

    issues: list[str] = []
    character_ids = {item.character_id for item in request.characters}
    location_ids = {item.location_id for item in request.locations}
    pov_character_id = str(request.novel.get("pov_character_id", ""))

    _validate_novel(request, issues)
    _validate_setup_source(
        request,
        character_ids=character_ids,
        location_ids=location_ids,
        issues=issues,
    )
    _validate_story_state(
        request,
        character_ids=character_ids,
        location_ids=location_ids,
        issues=issues,
    )
    if not request.locations:
        issues.append("locations needs at least one complete starting location")
    if pov_character_id and pov_character_id not in character_ids:
        issues.append("novel.pov_character_id is not present in characters")
    _validate_director_plan(
        request,
        character_ids=character_ids,
        pov_character_id=pov_character_id,
        issues=issues,
    )
    _validate_scene_and_characters(
        request,
        character_ids=character_ids,
        location_ids=location_ids,
        pov_character_id=pov_character_id,
        issues=issues,
    )
    return issues
