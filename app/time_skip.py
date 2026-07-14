from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any

from app.director_bible import normalise_director_bible
from app.id_utils import now_iso
from app.scene_contract_builder import build_scene_contract


TIME_SKIP_MODES = {"nearest_event", "duration"}
TIME_SKIP_UNITS = ("hours", "days", "weeks", "months")
_UNIT_ORDER = {unit: index for index, unit in enumerate(TIME_SKIP_UNITS)}
_UNIT_HOURS = {"hours": 1, "days": 24, "weeks": 24 * 7, "months": 24 * 30}
_DEFAULT_MAX_AMOUNTS = {"hours": 24, "days": 14, "weeks": 4, "months": 1}
_EVENT_STATUSES = {"planned", "ready", "deferred"}


def _text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


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


def _integer(value: Any, fallback: int, minimum: int = 0, maximum: int = 9999) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = fallback
    return max(minimum, min(maximum, number))


def normalise_time_skip_control(value: Any, *, turn_number: int = 0) -> dict[str, Any]:
    source = deepcopy(value) if isinstance(value, dict) else {}
    explicit_allowed = source.get("allowed") if isinstance(source.get("allowed"), bool) else None
    default_blocker = "opening_scene_not_played" if turn_number <= 0 else "natural_pause_not_confirmed"
    allowed = bool(explicit_allowed) if explicit_allowed is not None else False
    blockers = _string_list(source.get("blockers"), 8)
    if not allowed and not blockers:
        blockers = [default_blocker]
    if allowed:
        blockers = []
    max_unit = _text(source.get("max_unit"), "days")
    if max_unit not in TIME_SKIP_UNITS:
        max_unit = "days"
    return {
        **source,
        "allowed": allowed,
        "reason": _text(
            source.get("reason"),
            "Сначала должна завершиться первая значимая сцена."
            if turn_number <= 0
            else "Пропуск разрешается только в явно сохранённой естественной паузе.",
        ),
        "blockers": blockers,
        "suggested_mode": _text(source.get("suggested_mode"), "nearest_event"),
        "max_unit": max_unit,
        "max_amount": _integer(source.get("max_amount"), _DEFAULT_MAX_AMOUNTS[max_unit], 1, 365),
    }


def prepare_time_skip_state(data: dict[str, Any]) -> dict[str, Any]:
    current_state = data.setdefault("current_state", {})
    if not isinstance(current_state, dict):
        current_state = {}
        data["current_state"] = current_state
    turn_number = _integer(current_state.get("turn_number"), 0)
    control = normalise_time_skip_control(current_state.get("time_skip_control"), turn_number=turn_number)
    current_state["time_skip_control"] = control
    return control


def _time_flow(bible: dict[str, Any]) -> dict[str, Any]:
    source = bible.get("time_flow") if isinstance(bible.get("time_flow"), dict) else {}
    allowed_units = [unit for unit in _string_list(source.get("allowed_units"), 4) if unit in TIME_SKIP_UNITS]
    if not allowed_units:
        allowed_units = ["hours", "days", "weeks"]
    max_amounts_source = source.get("max_amounts") if isinstance(source.get("max_amounts"), dict) else {}
    max_amounts = {
        unit: _integer(max_amounts_source.get(unit), _DEFAULT_MAX_AMOUNTS[unit], 1, 365)
        for unit in TIME_SKIP_UNITS
    }
    return {
        **source,
        "current_period": _text(source.get("current_period"), "early_story"),
        "default_mode": _text(source.get("default_mode"), "nearest_event"),
        "allow_nearest_event": source.get("allow_nearest_event") is not False,
        "allowed_units": allowed_units,
        "max_amounts": max_amounts,
        "last_skip": source.get("last_skip") if isinstance(source.get("last_skip"), dict) else None,
    }


def _event_distance(event: dict[str, Any]) -> tuple[str, int, int]:
    unit = _text(event.get("skip_unit"), "days")
    if unit not in TIME_SKIP_UNITS:
        unit = "days"
    amount = _integer(event.get("skip_amount"), 1, 0, 365)
    return unit, amount, amount * _UNIT_HOURS[unit]


def _pending_events(bible: dict[str, Any], current_turn: int) -> list[dict[str, Any]]:
    next_turn = current_turn + 1
    result = [
        item
        for item in bible.get("event_queue", [])
        if isinstance(item, dict)
        and item.get("status") in _EVENT_STATUSES
        and _integer(item.get("earliest_turn"), 0) <= next_turn
    ]
    result.sort(
        key=lambda item: (
            _event_distance(item)[2],
            -_integer(item.get("priority"), 0, 0, 100),
            _integer(item.get("earliest_turn"), 0),
        )
    )
    return result


def _event_is_within_duration(event: dict[str, Any], unit: str, amount: int) -> bool:
    _, _, event_hours = _event_distance(event)
    return event_hours <= amount * _UNIT_HOURS[unit]


def _target_frame_hint(current_state: dict[str, Any], unit: str | None, amount: int | None) -> dict[str, Any]:
    if not unit or amount is None:
        return {"date": None, "time": None, "deterministic": False}
    raw_date = _text(current_state.get("date"))
    raw_time = _text(current_state.get("time"), "00:00")
    try:
        base = datetime.fromisoformat(f"{raw_date}T{raw_time}")
    except ValueError:
        return {"date": None, "time": None, "deterministic": False}
    if unit == "hours":
        target = base + timedelta(hours=amount)
    elif unit == "days":
        target = base + timedelta(days=amount)
    elif unit == "weeks":
        target = base + timedelta(weeks=amount)
    else:
        target = base + timedelta(days=30 * amount)
    return {"date": target.date().isoformat(), "time": target.strftime("%H:%M"), "deterministic": True}


def assess_time_skip(
    bundle: dict[str, Any],
    *,
    mode: str,
    unit: str | None = None,
    amount: int | None = None,
) -> dict[str, Any]:
    current_state = bundle.get("current_state") if isinstance(bundle.get("current_state"), dict) else {}
    turn_number = _integer(current_state.get("turn_number"), 0)
    control = normalise_time_skip_control(current_state.get("time_skip_control"), turn_number=turn_number)
    bible = normalise_director_bible(bundle.get("director_bible"), bundle)
    flow = _time_flow(bible)
    blockers: list[str] = []

    if mode not in TIME_SKIP_MODES:
        blockers.append("unsupported_skip_mode")
    if not control["allowed"]:
        blockers.extend(control.get("blockers") or ["natural_pause_not_confirmed"])
    if any(isinstance(item, dict) and item.get("status") == "triggered" for item in bible.get("event_queue", [])):
        blockers.append("event_already_in_progress")

    target_event: dict[str, Any] | None = None
    effective_unit = unit
    effective_amount = amount
    pending_events = _pending_events(bible, turn_number)

    if mode == "nearest_event":
        if not flow["allow_nearest_event"]:
            blockers.append("nearest_event_skip_disabled")
        if pending_events:
            target_event = pending_events[0]
            effective_unit, effective_amount, _ = _event_distance(target_event)
        else:
            blockers.append("no_pending_event")
    elif mode == "duration":
        if unit not in TIME_SKIP_UNITS:
            blockers.append("duration_unit_required")
        else:
            effective_unit = unit
            effective_amount = _integer(amount, 0, 0, 365)
            if effective_amount <= 0:
                blockers.append("duration_amount_required")
            if unit not in flow["allowed_units"]:
                blockers.append("duration_unit_not_allowed")
            if _UNIT_ORDER[unit] > _UNIT_ORDER.get(control.get("max_unit"), _UNIT_ORDER["days"]):
                blockers.append("duration_exceeds_scene_control")
            max_allowed = min(
                _integer(flow["max_amounts"].get(unit), _DEFAULT_MAX_AMOUNTS[unit], 1, 365),
                control["max_amount"] if unit == control.get("max_unit") else _DEFAULT_MAX_AMOUNTS[unit],
            )
            if effective_amount > max_allowed:
                blockers.append("duration_amount_too_large")
            candidates = [item for item in pending_events if _event_is_within_duration(item, unit, effective_amount)]
            if candidates:
                candidates.sort(key=lambda item: (-_integer(item.get("priority"), 0, 0, 100), _event_distance(item)[2]))
                target_event = candidates[0]

    hidden_participants: list[str] = []
    if target_event:
        characters = bundle.get("characters") if isinstance(bundle.get("characters"), dict) else {}
        for character_id in _string_list(target_event.get("participants"), 12):
            card = characters.get(character_id) if isinstance(characters.get(character_id), dict) else {}
            if card.get("available_to_scene") is False or card.get("introduced") is False:
                hidden_participants.append(character_id)

    blockers = list(dict.fromkeys(blockers))
    return {
        "allowed": not blockers,
        "blockers": blockers,
        "control": control,
        "time_flow": flow,
        "mode": mode,
        "unit": effective_unit,
        "amount": effective_amount,
        "target_event": deepcopy(target_event) if target_event else None,
        "hidden_participant_ids": hidden_participants,
        "target_frame_hint": _target_frame_hint(current_state, effective_unit, effective_amount),
    }


def build_time_skip_contract(
    bundle: dict[str, Any],
    *,
    player_input: str,
    mode: str,
    unit: str | None = None,
    amount: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    assessment = assess_time_skip(bundle, mode=mode, unit=unit, amount=amount)
    if not assessment["allowed"]:
        raise ValueError("Time skip is blocked: " + ", ".join(assessment["blockers"]))
    contract = build_scene_contract(bundle, player_input=player_input)
    target_event = assessment.get("target_event") if isinstance(assessment.get("target_event"), dict) else None
    contract["time_skip_request"] = {
        "kind": "time_skip",
        "mode": mode,
        "requested_duration": {
            "unit": assessment.get("unit"),
            "amount": assessment.get("amount"),
        },
        "target_event": target_event,
        "target_frame_hint": assessment.get("target_frame_hint"),
        "hidden_participant_ids": assessment.get("hidden_participant_ids", []),
        "rules": {
            "summarise_not_replay": "пропущенный период сожми в 2–5 причинных beat; не разыгрывай каждый день",
            "npc_lives_continue": "покажи только значимые самостоятельные изменения NPC, вытекающие из их целей и runtime",
            "no_player_choice": "не приписывай героине признание, согласие, прощение, отношения, увольнение, переезд или иной важный выбор",
            "open_on_beat": "заверши переход не пустым утром, а ближайшим meaningful beat или последствием",
            "hidden_delivery": "hidden_core может проявиться косвенно; не выводи его напрямую без сохранённого unlock",
            "state_patch_required": "scene_state_patch обязан обновить date/time и time_skip_control для нового кадра",
            "time_skip_result_required": "верни time_skip_result с elapsed, routine_summary, target_event_id и флагами безопасности",
        },
    }
    return contract, assessment


def validate_time_skip_scene_response(
    pending: dict[str, Any],
    scene_response: dict[str, Any],
    bundle: dict[str, Any],
) -> list[str]:
    if pending.get("turn_kind") != "time_skip":
        return []
    errors: list[str] = []
    request = pending.get("time_skip_request") if isinstance(pending.get("time_skip_request"), dict) else {}
    result = scene_response.get("time_skip_result") if isinstance(scene_response.get("time_skip_result"), dict) else None
    if result is None:
        return ["time_skip_result is required for advanceTime"]
    if result.get("opened_at_meaningful_beat") is not True:
        errors.append("time_skip_result.opened_at_meaningful_beat must be true")
    if result.get("skipped_major_player_choice") is not False:
        errors.append("time_skip_result.skipped_major_player_choice must be false")
    routine = _string_list(result.get("routine_summary"), 8)
    if not routine:
        errors.append("time_skip_result.routine_summary must contain at least one causal summary beat")

    elapsed = result.get("elapsed") if isinstance(result.get("elapsed"), dict) else {}
    expected_unit = request.get("unit")
    expected_amount = _integer(request.get("amount"), 0)
    if expected_unit and expected_amount > 0:
        if elapsed.get("unit") != expected_unit or _integer(elapsed.get("amount"), 0) != expected_amount:
            errors.append("time_skip_result.elapsed must match the selected skip duration")

    target_event = request.get("target_event") if isinstance(request.get("target_event"), dict) else None
    expected_event_id = target_event.get("id") if target_event else None
    if expected_event_id and result.get("target_event_id") != expected_event_id:
        errors.append("time_skip_result.target_event_id must match the selected director event")

    proposed = scene_response.get("proposed_updates") if isinstance(scene_response.get("proposed_updates"), dict) else {}
    state_patch = proposed.get("scene_state_patch") if isinstance(proposed.get("scene_state_patch"), dict) else {}
    if not _text(state_patch.get("date")) or not _text(state_patch.get("time")):
        errors.append("time skip scene_state_patch must set non-empty date and time")
    control = state_patch.get("time_skip_control") if isinstance(state_patch.get("time_skip_control"), dict) else None
    if control is None or not isinstance(control.get("allowed"), bool):
        errors.append("time skip scene_state_patch.time_skip_control.allowed is required")
    elif control.get("allowed") is not False:
        errors.append("time skip must close time_skip_control until the new scene reaches another natural pause")

    if expected_event_id:
        director = proposed.get("director_bible_patches") if isinstance(proposed.get("director_bible_patches"), dict) else {}
        event_updates = [item for item in _list(director.get("event_updates")) if isinstance(item, dict)]
        matching = [item for item in event_updates if item.get("id") == expected_event_id]
        if not matching or matching[0].get("status") not in {"triggered", "completed"}:
            errors.append("selected time skip event must be marked triggered or completed")
    return errors


def record_time_skip_result(
    storage: Any,
    session_id: str,
    pending: dict[str, Any],
    scene_response: dict[str, Any],
    bundle: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    if pending.get("turn_kind") != "time_skip":
        return result
    time_result = scene_response.get("time_skip_result") if isinstance(scene_response.get("time_skip_result"), dict) else {}
    current_state = storage.read_json(session_id, "current_state.json", default=bundle.get("current_state", {}))
    data = {
        **bundle,
        "current_state": current_state,
        "director_bible": storage.read_json(session_id, "director_bible.json", default=bundle.get("director_bible", {})),
    }
    bible = normalise_director_bible(data.get("director_bible"), data)
    flow = _time_flow(bible)
    request = pending.get("time_skip_request") if isinstance(pending.get("time_skip_request"), dict) else {}
    entry = {
        "turn": _integer(current_state.get("turn_number"), 0),
        "type": "time_skip",
        "mode": request.get("mode"),
        "elapsed": deepcopy(time_result.get("elapsed")) if isinstance(time_result.get("elapsed"), dict) else {},
        "target_event_id": time_result.get("target_event_id"),
        "routine_summary": _string_list(time_result.get("routine_summary"), 8),
        "from_frame": request.get("from_frame", {}),
        "to_frame": {"date": current_state.get("date"), "time": current_state.get("time"), "location": current_state.get("location")},
        "recorded_at": now_iso(),
    }
    flow["last_skip"] = entry
    bible["time_flow"] = flow
    bible["history"] = (bible.get("history", []) + [entry])[-30:]
    storage.write_json(session_id, "director_bible.json", bible)
    result.setdefault("applied", {})["time_skip"] = {
        "mode": entry["mode"],
        "elapsed": entry["elapsed"],
        "target_event_id": entry["target_event_id"],
    }
    result.setdefault("next_builder_hints", {})["time_skip"] = {
        "current_date": current_state.get("date"),
        "current_time": current_state.get("time"),
        "time_skip_control": current_state.get("time_skip_control", {}),
    }
    return result
