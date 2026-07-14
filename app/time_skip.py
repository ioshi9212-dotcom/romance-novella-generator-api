from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.director_bible import build_director_guidance, normalise_director_bible
from app.npc_runtime import compact_npc_runtime_entry
from app.scene_contract_builder import build_scene_contract


TIME_SKIP_ACTION = "Пропустить время до ближайших событий"
TIME_SKIP_COMMANDS = {
    "пропустить время до ближайших событий",
    "пропустить время до ближайшего события",
    "пропустить время",
    "перейти к ближайшему событию",
}


class TimeSkipUnavailable(ValueError):
    pass


def _text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    if isinstance(value, str):
        return value.strip() or fallback
    return str(value).strip() or fallback


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _string_list(value: Any, limit: int = 12) -> list[str]:
    result: list[str] = []
    for item in _list(value)[:limit]:
        text = _text(item)
        if text and text not in result:
            result.append(text)
    return result


def _integer(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _normalised_command(value: Any) -> str:
    text = " ".join(_text(value).lower().replace("ё", "е").split())
    return text.strip(" .!?")


def is_time_skip_command(player_input: str) -> bool:
    return _normalised_command(player_input) in TIME_SKIP_COMMANDS


def normalise_time_skip_state(current_state: Any) -> dict[str, Any]:
    current_state = current_state if isinstance(current_state, dict) else {}
    source = current_state.get("time_skip_state") if isinstance(current_state.get("time_skip_state"), dict) else {}
    allowed = bool(source.get("allowed", False))
    return {
        **source,
        "allowed": allowed,
        "reason": _text(
            source.get("reason"),
            "Пропуск времени ещё не открыт: нужна естественная пауза после завершённого смыслового бита.",
        ),
        "suggested_horizon": _text(source.get("suggested_horizon"), "до ближайшего значимого события"),
        "set_on_turn": _integer(source.get("set_on_turn"), _integer(current_state.get("turn_number"), 0)),
        "blocked_by": _string_list(source.get("blocked_by"), 8),
    }


def _participant_available(characters: dict[str, Any], character_id: str) -> bool:
    card = characters.get(character_id)
    if not isinstance(card, dict):
        return False
    if card.get("cast_status") == "hidden_core":
        return bool(card.get("introduced") is True and card.get("available_to_scene") is True)
    return card.get("available_to_scene") is not False


def select_time_skip_event(bundle: dict[str, Any]) -> dict[str, Any] | None:
    bible = normalise_director_bible(bundle.get("director_bible"), bundle)
    current_state = bundle.get("current_state") if isinstance(bundle.get("current_state"), dict) else {}
    current_turn = _integer(current_state.get("turn_number"), 0)
    next_turn = current_turn + 1
    characters = bundle.get("characters") if isinstance(bundle.get("characters"), dict) else {}

    candidates: list[dict[str, Any]] = []
    for event in bible.get("event_queue", []):
        if not isinstance(event, dict) or event.get("status") not in {"planned", "ready", "deferred"}:
            continue
        participants = _string_list(event.get("participants"), 12)
        if any(not _participant_available(characters, character_id) for character_id in participants):
            continue
        candidates.append(event)

    if not candidates:
        return None

    def sort_key(event: dict[str, Any]) -> tuple[int, int, int, int]:
        earliest = _integer(event.get("earliest_turn"), next_turn)
        latest = _integer(event.get("latest_turn"), 0)
        ready_rank = 0 if earliest <= next_turn else 1
        urgency = latest if latest > 0 else 999999
        return (ready_rank, -_integer(event.get("priority"), 0), earliest, urgency)

    candidates.sort(key=sort_key)
    return deepcopy(candidates[0])


def time_skip_availability(bundle: dict[str, Any]) -> dict[str, Any]:
    current_state = bundle.get("current_state") if isinstance(bundle.get("current_state"), dict) else {}
    state = normalise_time_skip_state(current_state)
    if not state["allowed"]:
        return {"allowed": False, "reason": state["reason"], "state": state, "target_event": None}
    if state.get("blocked_by"):
        return {
            "allowed": False,
            "reason": "Пропуск времени заблокирован: " + ", ".join(state["blocked_by"]),
            "state": state,
            "target_event": None,
        }
    target = select_time_skip_event(bundle)
    if target is None:
        return {
            "allowed": False,
            "reason": "В director_bible нет ближайшего допустимого события без скрытого или недоступного участника.",
            "state": state,
            "target_event": None,
        }
    return {"allowed": True, "reason": state["reason"], "state": state, "target_event": target}


def _compact_event(event: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "id",
        "title",
        "status",
        "priority",
        "earliest_turn",
        "latest_turn",
        "conditions",
        "participants",
        "purpose",
        "scene_pressure",
        "next_if_ignored",
        "time_hint",
    )
    return {key: event.get(key) for key in keys if key in event}


def _target_context(bundle: dict[str, Any], target_ids: set[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    knowledge = bundle.get("knowledge") if isinstance(bundle.get("knowledge"), dict) else {}
    npc_state = bundle.get("npc_state") if isinstance(bundle.get("npc_state"), dict) else {}
    relationships = bundle.get("relationships") if isinstance(bundle.get("relationships"), dict) else {}

    character_context: dict[str, Any] = {}
    for character_id in sorted(target_ids):
        knowledge_entry = knowledge.get(character_id) if isinstance(knowledge.get(character_id), dict) else {}
        character_context[character_id] = {
            "knowledge": {
                "known_facts": _list(knowledge_entry.get("known_facts"))[-8:],
                "observations": _list(knowledge_entry.get("observations"))[-6:],
                "assumptions": _list(knowledge_entry.get("assumptions"))[-6:],
                "wrong_beliefs": _list(knowledge_entry.get("wrong_beliefs"))[-6:],
                "does_not_know": _string_list(knowledge_entry.get("does_not_know"), 8),
                "must_not_assume": _string_list(knowledge_entry.get("must_not_assume"), 8),
                "recent_memories": _string_list(knowledge_entry.get("recent_memories"), 6),
            },
            "npc_runtime": compact_npc_runtime_entry(npc_state.get(character_id)),
        }

    target_relationships: dict[str, Any] = {}
    for relationship_id, relationship in relationships.items():
        if not isinstance(relationship, dict):
            continue
        a = _text(relationship.get("character_a"))
        b = _text(relationship.get("character_b"))
        if a in target_ids and b in target_ids:
            target_relationships[str(relationship_id)] = relationship
    return character_context, target_relationships


def build_time_skip_contract(bundle: dict[str, Any], player_input: str) -> dict[str, Any]:
    availability = time_skip_availability(bundle)
    if not availability["allowed"]:
        raise TimeSkipUnavailable(availability["reason"])

    base = build_scene_contract(bundle, player_input=player_input)
    target = availability["target_event"]
    target_participants = set(_string_list(target.get("participants"), 12))
    player_id = _text((base.get("current_frame") or {}).get("player_character_id"), "pc_01")
    target_participants.add(player_id)

    director_guidance = deepcopy(build_director_guidance(bundle))
    director_guidance["due_or_next_events"] = [_compact_event(target)]
    director_guidance["character_functions"] = {
        character_id: entry
        for character_id, entry in (director_guidance.get("character_functions") or {}).items()
        if character_id in target_participants
    }

    loaded_characters = [
        item
        for item in base.get("loaded_characters", [])
        if isinstance(item, dict) and item.get("character_id") in target_participants
    ]
    known_loaded_ids = {item.get("character_id") for item in loaded_characters if isinstance(item, dict)}
    characters = bundle.get("characters") if isinstance(bundle.get("characters"), dict) else {}
    for character_id in target_participants:
        if character_id in known_loaded_ids:
            continue
        card = characters.get(character_id)
        if isinstance(card, dict) and _participant_available(characters, character_id):
            loaded_characters.append({
                "character_id": character_id,
                "display_name": card.get("display_name") or card.get("name") or character_id,
                "load_reason": ["time_skip_target_event"],
                "card": card,
            })

    character_context, target_relationships = _target_context(bundle, target_participants)
    return {
        **base,
        "contract_version": "novella.time_skip_contract.v1",
        "loaded_characters": loaded_characters,
        "director_guidance": director_guidance,
        "time_skip": {
            "mode": "explicit_player_requested_transition",
            "exact_player_action": TIME_SKIP_ACTION,
            "target_event": _compact_event(target),
            "target_character_context": character_context,
            "target_relationships": target_relationships,
            "suggested_horizon": availability["state"].get("suggested_horizon"),
            "allowed_units": ["hours", "days", "weeks", "months"],
            "transition_rules": {
                "summarise_not_play_every_hour": "Коротко покажи только изменения и последствия пропущенного времени; не разыгрывай рутину по дням.",
                "open_on_event_not_after_it": "Заверши переход входом в ближайшее событие. Не решай само событие и не перескакивай через важный выбор игрока.",
                "npc_lives_continue": "NPC могут действовать за кадром по своим целям; сохраняй конкретные последствия через npc_state/relationship/knowledge patches.",
                "no_player_choice_in_summary": "Не назначай героине согласие, романтическое решение, переезд, увольнение, обещание или иной важный выбор.",
                "state_must_advance": "Обнови date, time, location, scene_state, active_character_ids и time_skip_state.",
                "target_event_status": "Верни director_bible_patches.event_updates для target_event.id со status=triggered.",
            },
            "required_metadata": {
                "time_skip.applied": True,
                "time_skip.target_event_id": target.get("id"),
                "time_skip.elapsed_summary": "краткое описание реально прошедшего интервала",
            },
        },
        "output_requirements": {
            **(base.get("output_requirements") or {}),
            "time_skip_mode": "Generate a transition scene_response, call applyTurnResult, then show only response.message_to_user.",
        },
    }


def ensure_time_skip_state_patch(scene_response: dict[str, Any], pending: dict[str, Any]) -> dict[str, Any]:
    response = deepcopy(scene_response)
    updates = response.setdefault("proposed_updates", {})
    if not isinstance(updates, dict):
        updates = {}
        response["proposed_updates"] = updates
    scene_patch = updates.setdefault("scene_state_patch", {})
    if not isinstance(scene_patch, dict):
        scene_patch = {}
        updates["scene_state_patch"] = scene_patch

    if "time_skip_state" not in scene_patch:
        if pending.get("turn_mode") == "time_skip":
            scene_patch["time_skip_state"] = {
                "allowed": False,
                "reason": "Пропуск выполнен; новая пауза должна быть создана следующей сценой.",
                "suggested_horizon": "до следующей естественной паузы",
            }
        else:
            scene_patch["time_skip_state"] = {
                "allowed": False,
                "reason": "Сцена продолжилась; новая естественная пауза ещё не подтверждена.",
                "suggested_horizon": "до ближайшего значимого события",
            }
    return response


def validate_time_skip_scene_response(
    scene_response: dict[str, Any],
    pending: dict[str, Any],
    bundle: dict[str, Any],
) -> list[str]:
    if pending.get("turn_mode") != "time_skip":
        return []

    errors: list[str] = []
    target_event_id = _text(pending.get("target_event_id"))
    updates = scene_response.get("proposed_updates") if isinstance(scene_response.get("proposed_updates"), dict) else {}
    scene_patch = updates.get("scene_state_patch") if isinstance(updates.get("scene_state_patch"), dict) else {}
    for field in ("date", "time", "location", "scene_state", "active_character_ids", "time_skip_state"):
        if field not in scene_patch:
            errors.append(f"time skip requires proposed_updates.scene_state_patch.{field}")

    time_state = scene_patch.get("time_skip_state") if isinstance(scene_patch.get("time_skip_state"), dict) else {}
    if time_state.get("allowed") is not False:
        errors.append("time skip response must set time_skip_state.allowed=false")

    metadata = scene_response.get("metadata") if isinstance(scene_response.get("metadata"), dict) else {}
    time_meta = metadata.get("time_skip") if isinstance(metadata.get("time_skip"), dict) else {}
    if time_meta.get("applied") is not True:
        errors.append("time skip response metadata.time_skip.applied must be true")
    if _text(time_meta.get("target_event_id")) != target_event_id:
        errors.append("time skip response metadata.time_skip.target_event_id must match pending target event")
    if not _text(time_meta.get("elapsed_summary")):
        errors.append("time skip response metadata.time_skip.elapsed_summary is required")

    director_patches = updates.get("director_bible_patches") if isinstance(updates.get("director_bible_patches"), dict) else {}
    event_updates = [item for item in _list(director_patches.get("event_updates")) if isinstance(item, dict)]
    target_updates = [item for item in event_updates if _text(item.get("id")) == target_event_id]
    if not target_updates:
        errors.append("time skip response must update the selected target event")
    elif not any(_text(item.get("status")) == "triggered" for item in target_updates):
        errors.append("time skip target event must transition to status=triggered")

    header = ((scene_response.get("scene") or {}).get("header") or {}) if isinstance(scene_response.get("scene"), dict) else {}
    for field in ("date", "time", "location", "scene_state"):
        if field in scene_patch and _text(header.get(field)) != _text(scene_patch.get(field)):
            errors.append(f"time skip scene.header.{field} must match scene_state_patch.{field}")

    current_state = bundle.get("current_state") if isinstance(bundle.get("current_state"), dict) else {}
    if _text(scene_patch.get("date")) == _text(current_state.get("date")) and _text(scene_patch.get("time")) == _text(current_state.get("time")):
        errors.append("time skip must advance date or time")
    return errors
