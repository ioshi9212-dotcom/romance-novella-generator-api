from pathlib import Path
from typing import Any
import json
import re
from jsonschema import Draft202012Validator

from app.character_profiles import (
    SIGNIFICANT_CAST_STATUSES,
    behavior_signature,
    prepare_bootstrap_cast,
)
from app.directional_relationships import prepare_directional_relationships
from app.id_utils import pair_id


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

PROFILE_TEXT_FIELDS = {
    "inner_logic": ["core_need", "main_fear", "blind_spot", "contradiction"],
    "behavior": [
        "conflict_style",
        "care_style",
        "closeness_style",
        "touch_style",
        "stress_response",
        "rejection_response",
        "change_inertia",
        "inconvenient_pattern",
    ],
    "speech_profile": ["baseline", "under_pressure"],
    "life_outside_player": ["current_obligation", "private_problem", "person_or_place_that_matters"],
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



def _is_placeholder(value: Any) -> bool:
    text = " ".join(str(value or "").strip().lower().split())
    exact = {"", "—", "-", "не указано", "старт", "стартовая локация", "начало истории", "будет уточняться", "сеттинг будет уточняться"}
    snippets = ("будет уточняться", "не указано", "placeholder", "живая, узнаваемая речь", "заметная привычка")
    return text in exact or any(snippet in text for snippet in snippets)



def _validate_not_placeholder(value: Any, location: str, errors: list[str]) -> None:
    if _is_placeholder(value):
        errors.append(f"{location} must be filled with story-specific content, not placeholder: {value!r}")



def _validate_character_profile(character_id: str, card: dict[str, Any], errors: list[str]) -> None:
    cast_status = card.get("cast_status")
    if cast_status not in SIGNIFICANT_CAST_STATUSES | {"background"}:
        errors.append(f"characters.{character_id}.cast_status is invalid: {cast_status!r}")
        return

    expected_known = cast_status in {"player", "known_core", "known_support"}
    if bool(card.get("known_to_player")) != expected_known:
        errors.append(f"characters.{character_id}.known_to_player conflicts with cast_status={cast_status}")
    if cast_status == "hidden_core":
        if card.get("introduced") is not False or card.get("available_to_scene") is not False or card.get("show_in_preview") is not False:
            errors.append(f"characters.{character_id} hidden_core must remain unavailable and hidden before reveal")
    if cast_status in {"player", "known_core", "known_support"} and card.get("show_in_preview") is not True:
        errors.append(f"characters.{character_id} visible starting cast must be shown in preview")

    for object_key, field_names in PROFILE_TEXT_FIELDS.items():
        block = card.get(object_key)
        if not isinstance(block, dict):
            errors.append(f"characters.{character_id}.{object_key} must be an object")
            continue
        for field_name in field_names:
            _validate_not_placeholder(block.get(field_name), f"characters.{character_id}.{object_key}.{field_name}", errors)

    speech_profile = card.get("speech_profile") or {}
    for field_name in ("verbal_habits", "avoids"):
        values = speech_profile.get(field_name)
        if not isinstance(values, list) or not values:
            errors.append(f"characters.{character_id}.speech_profile.{field_name} must contain at least one concrete item")
        elif any(_is_placeholder(item) for item in values):
            errors.append(f"characters.{character_id}.speech_profile.{field_name} contains a placeholder")

    social_triggers = card.get("social_triggers")
    if not isinstance(social_triggers, list) or len(social_triggers) < 2:
        errors.append(f"characters.{character_id}.social_triggers must contain at least 2 behavior/interpretation/reaction entries")
    else:
        for index, trigger in enumerate(social_triggers):
            if not isinstance(trigger, dict):
                errors.append(f"characters.{character_id}.social_triggers[{index}] must be an object")
                continue
            for field_name in ("behavior", "interpretation", "usual_reaction"):
                _validate_not_placeholder(trigger.get(field_name), f"characters.{character_id}.social_triggers[{index}].{field_name}", errors)



def _repair_string_relationship_directions(data: dict[str, Any]) -> None:
    relationships = data.get("relationships") if isinstance(data.get("relationships"), dict) else {}
    preserved_views: list[tuple[str, str, str]] = []
    for pair_key, relationship in relationships.items():
        if not isinstance(relationship, dict):
            continue
        for direction_key in ("a_to_b", "b_to_a"):
            value = relationship.get(direction_key)
            if isinstance(value, str) and value.strip():
                preserved_views.append((str(pair_key), direction_key, value.strip()))

    prepare_directional_relationships(data)

    repaired = data.get("relationships") if isinstance(data.get("relationships"), dict) else {}
    for pair_key, direction_key, view_text in preserved_views:
        relationship = repaired.get(pair_key)
        direction = relationship.get(direction_key) if isinstance(relationship, dict) else None
        if isinstance(direction, dict):
            direction["current_view"] = view_text


def validate_bootstrap_result(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    prepare_bootstrap_cast(data)
    _repair_string_relationship_directions(data)
    errors.extend(_validate_with_schema(data, "bootstrap_output.schema.json"))
    for key in REQUIRED_BOOTSTRAP_KEYS:
        if key not in data:
            errors.append(f"missing key: {key}")

    characters = data.get("characters")
    if characters is not None and not isinstance(characters, dict):
        errors.append("characters must be object keyed by generated character_id")
    errors.extend(_validate_character_names(characters))

    protagonist = data.get("protagonist") or {}
    protagonist_id = protagonist.get("id")
    if isinstance(characters, dict):
        if not characters:
            errors.append("characters must contain at least the player character")
        player_ids: list[str] = []
        signatures: dict[tuple[str, str, str, str], str] = {}
        for character_id, card in characters.items():
            if isinstance(card, dict) and card.get("id") not in {None, character_id}:
                errors.append(f"characters.{character_id}.id must match its generated character_id key")
            if not isinstance(card, dict):
                continue
            _validate_not_placeholder(card.get("goal"), f"characters.{character_id}.goal", errors)
            _validate_not_placeholder(card.get("past_short"), f"characters.{character_id}.past_short", errors)
            _validate_character_profile(character_id, card, errors)
            if card.get("cast_status") == "player":
                player_ids.append(character_id)
            if card.get("cast_status") in SIGNIFICANT_CAST_STATUSES and character_id != protagonist_id:
                signature = behavior_signature(card)
                if signature in signatures:
                    errors.append(
                        f"characters.{character_id} duplicates the behavioral voice of characters.{signatures[signature]}; "
                        "significant NPCs need distinct care/conflict/stress/speech patterns"
                    )
                else:
                    signatures[signature] = character_id

        if player_ids != [protagonist_id]:
            errors.append(f"exactly protagonist.id must have cast_status=player; got {player_ids}")

    if protagonist and protagonist.get("id") not in (characters or {}):
        errors.append("protagonist.id must exist inside characters and use the generated character_id")
    if protagonist and "name" in protagonist:
        errors.extend(_validate_display_name(protagonist.get("name"), "protagonist"))

    knowledge = data.get("knowledge") or {}
    if isinstance(characters, dict) and isinstance(knowledge, dict):
        for character_id in characters:
            if character_id not in knowledge:
                errors.append(f"knowledge must contain an entry for characters.{character_id}")

    relationships = data.get("relationships") or {}
    if isinstance(characters, dict) and isinstance(relationships, dict) and protagonist_id:
        for character_id, card in characters.items():
            if character_id == protagonist_id or not isinstance(card, dict):
                continue
            if card.get("cast_status") in {"known_core", "known_support"}:
                pid = pair_id(str(protagonist_id), str(character_id))
                if pid not in relationships:
                    errors.append(f"relationships must contain starting pair {pid} for known cast")

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

    hidden_ids = {
        character_id
        for character_id, card in (characters or {}).items()
        if isinstance(card, dict) and card.get("cast_status") == "hidden_core"
    }
    leaked_ids = hidden_ids & set(current_state.get("active_character_ids") or [])
    leaked_ids |= hidden_ids & set(current_state.get("nearby_character_ids") or [])
    if leaked_ids:
        errors.append(f"hidden_core characters cannot be active/nearby before reveal: {sorted(leaked_ids)}")

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
        patch_pair_id = str(patch.get("pair_id") or "")
        if "__" not in patch_pair_id or len([part for part in patch_pair_id.split("__") if part]) != 2:
            errors.append(f"proposed_updates.relationship_patches[{index}].pair_id must look like a__b")
    for index, card in enumerate(updates.get("new_or_updated_characters") or []):
        if isinstance(card, dict) and "name" in card:
            errors.extend(_validate_display_name(card.get("name"), f"proposed_updates.new_or_updated_characters[{index}]"))
    return errors


def validate_scene_state_invariants(data: dict[str, Any], bundle: dict[str, Any]) -> list[str]:
    """Validate identity and visibility references before any turn state is written."""
    errors: list[str] = []
    existing_characters = bundle.get("characters") if isinstance(bundle.get("characters"), dict) else {}
    updates = data.get("proposed_updates") if isinstance(data.get("proposed_updates"), dict) else {}
    continuity_patch = updates.get("continuity_patch") if isinstance(updates.get("continuity_patch"), dict) else {}
    progress_patch = continuity_patch.get("story_progress_patch")
    if progress_patch is not None:
        location = "proposed_updates.continuity_patch.story_progress_patch"
        if not isinstance(progress_patch, dict):
            errors.append(f"{location} must be an object")
        else:
            acts = ((bundle.get("story_plan") or {}).get("act_structure") or [])
            stored_progress = ((bundle.get("continuity") or {}).get("story_progress") or {})
            try:
                current_index = int(stored_progress.get("current_act_index", 0) or 0)
                requested_index = int(progress_patch.get("current_act_index", current_index))
            except (TypeError, ValueError):
                errors.append(f"{location}.current_act_index must be an integer")
            else:
                if requested_index < 0 or requested_index >= len(acts):
                    errors.append(f"{location}.current_act_index references a missing act: {requested_index}")
                if requested_index < current_index:
                    errors.append(f"{location} cannot move backwards from act {current_index} to {requested_index}")
                if requested_index > current_index + 1:
                    errors.append(f"{location} cannot jump over an act from {current_index} to {requested_index}")
                if requested_index != current_index:
                    if not str(progress_patch.get("reason") or "").strip():
                        errors.append(f"{location}.reason is required for an act transition")
                    if not str(progress_patch.get("source_in_scene") or "").strip():
                        errors.append(f"{location}.source_in_scene is required for an act transition")
    new_cards = {
        str(card.get("id")): card
        for card in (updates.get("new_or_updated_characters") or [])
        if isinstance(card, dict) and card.get("id")
    }

    for index, card in enumerate(updates.get("new_or_updated_characters") or []):
        if not isinstance(card, dict):
            continue
        character_id = str(card.get("id") or "").strip()
        if not character_id or character_id in existing_characters:
            continue
        cast_status = str(card.get("cast_status") or "known_support").strip()
        if cast_status == "background":
            continue
        if cast_status not in {"known_core", "known_support"}:
            errors.append(
                f"proposed_updates.new_or_updated_characters[{index}].cast_status must be known_core or known_support for a newly introduced significant NPC"
            )
            continue
        location = f"proposed_updates.new_or_updated_characters[{index}]"
        candidate = {
            **card,
            "cast_status": cast_status,
            "known_to_player": True,
            "introduced": True,
            "show_in_preview": True,
            "available_to_scene": True,
        }
        for field_name in ("age", "goal", "past_short"):
            _validate_not_placeholder(candidate.get(field_name), f"{location}.{field_name}", errors)
        for field_name in ("habits", "skills", "connections"):
            if not isinstance(candidate.get(field_name), list):
                errors.append(f"{location}.{field_name} must be an array in a complete significant NPC card")
        appearance = candidate.get("appearance") if isinstance(candidate.get("appearance"), dict) else {}
        for field_name in ("height", "build", "hair", "eyes", "face", "style"):
            _validate_not_placeholder(appearance.get(field_name), f"{location}.appearance.{field_name}", errors)
        personality = candidate.get("personality") if isinstance(candidate.get("personality"), dict) else {}
        for field_name in ("core", "flaws"):
            if not isinstance(personality.get(field_name), list) or not personality.get(field_name):
                errors.append(f"{location}.personality.{field_name} must contain concrete items")
        _validate_not_placeholder(personality.get("speech"), f"{location}.personality.speech", errors)
        _validate_character_profile(character_id, candidate, errors)

    characters = {
        **existing_characters,
        **{
            character_id: {
                **(existing_characters.get(character_id) if isinstance(existing_characters.get(character_id), dict) else {}),
                **card,
            }
            for character_id, card in new_cards.items()
        },
    }

    director_bible = bundle.get("director_bible") if isinstance(bundle.get("director_bible"), dict) else {}
    planned_reveals = {
        str(item.get("id")): item
        for item in (director_bible.get("planned_reveals") or [])
        if isinstance(item, dict) and item.get("id")
    }
    director_patches = updates.get("director_bible_patches") if isinstance(updates.get("director_bible_patches"), dict) else {}
    reveal_updates = {
        str(item.get("id")): item
        for item in (director_patches.get("reveal_updates") or [])
        if isinstance(item, dict) and item.get("id")
    }
    future_locks = bundle.get("future_locks") if isinstance(bundle.get("future_locks"), dict) else {}
    hidden_ids = {str(item) for item in (future_locks.get("hidden_character_ids") or [])}
    next_turn = int(((bundle.get("current_state") or {}).get("turn_number", 0)) or 0) + 1

    for index, patch in enumerate(updates.get("new_or_updated_characters") or []):
        if not isinstance(patch, dict):
            continue
        character_id = str(patch.get("id") or "").strip()
        existing = existing_characters.get(character_id) if isinstance(existing_characters.get(character_id), dict) else None
        if not existing or existing.get("cast_status") != "hidden_core":
            continue
        location = f"proposed_updates.new_or_updated_characters[{index}]"
        reveal_id = str(patch.get("reveal_id") or "").strip()
        if not reveal_id:
            errors.append(f"{location} cannot update hidden_core before an explicit reveal_id")
            continue
        if not str(patch.get("reason") or "").strip() or not str(patch.get("source_in_scene") or "").strip():
            errors.append(f"{location} reveal requires reason and source_in_scene")
        if character_id not in hidden_ids:
            errors.append(f"{location} character_id is not present in future_locks.hidden_character_ids: {character_id}")
        planned = planned_reveals.get(reveal_id)
        if not isinstance(planned, dict):
            errors.append(f"{location}.reveal_id references unknown planned reveal: {reveal_id}")
            continue
        related_ids = {str(item) for item in (planned.get("related_character_ids") or [])}
        if character_id not in related_ids:
            errors.append(f"{location}.reveal_id is not linked to character_id: {character_id}")
        if next_turn < int(planned.get("earliest_turn", 0) or 0):
            errors.append(f"{location} reveal attempted before earliest_turn")
        matching_update = reveal_updates.get(reveal_id)
        if not isinstance(matching_update, dict) or matching_update.get("status") != "revealed":
            errors.append(f"{location} requires matching director_bible_patches.reveal_updates status=revealed")
        characters[character_id] = {
            **existing,
            "cast_status": str(patch.get("revealed_cast_status") or "known_core"),
            "known_to_player": True,
            "introduced": True,
            "show_in_preview": True,
            "available_to_scene": True,
        }

    def validate_character_ref(character_id: Any, location: str, *, require_available: bool = True) -> str | None:
        value = str(character_id or "").strip()
        if not value or value not in characters:
            errors.append(f"{location} references unknown character_id: {value or '<empty>'}")
            return None
        card = characters[value] if isinstance(characters.get(value), dict) else {}
        if require_available and (
            card.get("available_to_scene") is False
            or card.get("introduced") is False
            or card.get("cast_status") == "hidden_core"
        ):
            errors.append(f"{location} references hidden or unavailable character_id: {value}")
            return None
        return value

    scene_patch = updates.get("scene_state_patch") if isinstance(updates.get("scene_state_patch"), dict) else {}
    for field_name in ("active_character_ids", "nearby_character_ids"):
        if field_name not in scene_patch:
            continue
        values = scene_patch.get(field_name)
        if not isinstance(values, list):
            errors.append(f"proposed_updates.scene_state_patch.{field_name} must be an array")
            continue
        seen: set[str] = set()
        for index, character_id in enumerate(values):
            validated = validate_character_ref(
                character_id,
                f"proposed_updates.scene_state_patch.{field_name}[{index}]",
            )
            if validated and validated in seen:
                errors.append(f"proposed_updates.scene_state_patch.{field_name} contains duplicate character_id: {validated}")
            if validated:
                seen.add(validated)

    for index, witness in enumerate(data.get("witnesses") or []):
        character_id = witness
        if isinstance(witness, dict):
            character_id = witness.get("character_id") or witness.get("id")
        validate_character_ref(character_id, f"witnesses[{index}]")

    for index, patch in enumerate(updates.get("knowledge_patches") or []):
        if isinstance(patch, dict):
            validate_character_ref(patch.get("character_id"), f"proposed_updates.knowledge_patches[{index}].character_id")

    player_id = str((bundle.get("current_state") or {}).get("player_character_id") or "")
    for index, patch in enumerate(updates.get("npc_state_patches") or []):
        if not isinstance(patch, dict):
            continue
        character_id = validate_character_ref(
            patch.get("character_id"),
            f"proposed_updates.npc_state_patches[{index}].character_id",
        )
        if character_id and character_id == player_id:
            errors.append(f"proposed_updates.npc_state_patches[{index}] cannot target the player character: {character_id}")

    for index, patch in enumerate(updates.get("relationship_patches") or []):
        if not isinstance(patch, dict):
            continue
        raw_pair_id = str(patch.get("pair_id") or "")
        parts = raw_pair_id.split("__")
        if len(parts) != 2 or not all(parts):
            continue
        left = validate_character_ref(parts[0], f"proposed_updates.relationship_patches[{index}].pair_id")
        right = validate_character_ref(parts[1], f"proposed_updates.relationship_patches[{index}].pair_id")
        if left and right and raw_pair_id != pair_id(left, right):
            errors.append(f"proposed_updates.relationship_patches[{index}].pair_id is not canonical: {raw_pair_id}")
        from_id = patch.get("from_character_id")
        to_id = patch.get("to_character_id")
        if from_id is not None:
            validated_from = validate_character_ref(from_id, f"proposed_updates.relationship_patches[{index}].from_character_id")
            if validated_from and validated_from not in {left, right}:
                errors.append(f"proposed_updates.relationship_patches[{index}].from_character_id is outside pair_id")
        if to_id is not None:
            validated_to = validate_character_ref(to_id, f"proposed_updates.relationship_patches[{index}].to_character_id")
            if validated_to and validated_to not in {left, right}:
                errors.append(f"proposed_updates.relationship_patches[{index}].to_character_id is outside pair_id")

    return errors
