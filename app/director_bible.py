from __future__ import annotations

from copy import deepcopy
from typing import Any
import re


EVENT_STATUSES = {"planned", "ready", "triggered", "completed", "blocked", "deferred"}
HOOK_STATUSES = {"active", "advanced", "resolved", "dormant"}
REVEAL_STATUSES = {"locked", "available", "revealed", "deferred"}
CONFLICT_STATUSES = {"active", "escalated", "cooling", "resolved", "dormant"}
TIME_SKIP_UNITS = {"hours", "days", "weeks", "months"}

_EVENT_TRANSITIONS = {
    "planned": EVENT_STATUSES,
    "ready": {"ready", "triggered", "completed", "blocked", "deferred"},
    "triggered": {"triggered", "completed", "blocked", "deferred"},
    "deferred": {"deferred", "ready", "triggered", "completed", "blocked"},
    "blocked": {"blocked", "deferred", "ready"},
    "completed": {"completed"},
}
_REVEAL_TRANSITIONS = {
    "locked": {"locked", "available", "deferred"},
    "available": {"available", "revealed", "deferred"},
    "deferred": {"deferred", "available", "revealed"},
    "revealed": {"revealed"},
}


def _text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    if isinstance(value, str):
        return value.strip() or fallback
    if isinstance(value, (int, float, bool)):
        return str(value)
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


def _safe_id(value: Any, fallback: str) -> str:
    text = _text(value, fallback).lower()
    text = re.sub(r"[^a-z0-9_-]+", "_", text).strip("_")
    return text[:96] or fallback


def _integer(value: Any, fallback: int, minimum: int = 0, maximum: int = 9999) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = fallback
    return max(minimum, min(maximum, number))


def _normalise_time_flow(value: Any, story_plan: dict[str, Any]) -> dict[str, Any]:
    source = deepcopy(value) if isinstance(value, dict) else {}
    allowed_units = [unit for unit in _string_list(source.get("allowed_units"), 4) if unit in TIME_SKIP_UNITS]
    if not allowed_units:
        allowed_units = ["hours", "days", "weeks"]
    maxima = source.get("max_amounts") if isinstance(source.get("max_amounts"), dict) else {}
    return {
        **source,
        "current_period": _text(source.get("current_period") or story_plan.get("current_story_position"), "early_story"),
        "default_mode": _text(source.get("default_mode"), "nearest_event"),
        "allow_nearest_event": source.get("allow_nearest_event") is not False,
        "allowed_units": allowed_units,
        "max_amounts": {
            "hours": _integer(maxima.get("hours"), 24, 1, 365),
            "days": _integer(maxima.get("days"), 14, 1, 365),
            "weeks": _integer(maxima.get("weeks"), 4, 1, 52),
            "months": _integer(maxima.get("months"), 1, 1, 12),
        },
        "last_skip": source.get("last_skip") if isinstance(source.get("last_skip"), dict) else None,
    }


def _character_ids(data: dict[str, Any]) -> list[str]:
    characters = data.get("characters") if isinstance(data.get("characters"), dict) else {}
    return [str(character_id) for character_id in characters]


def _player_id(data: dict[str, Any]) -> str:
    current_state = data.get("current_state") if isinstance(data.get("current_state"), dict) else {}
    protagonist = data.get("protagonist") if isinstance(data.get("protagonist"), dict) else {}
    return _text(current_state.get("player_character_id") or protagonist.get("id"), "pc_01")


def _significant_character_ids(data: dict[str, Any]) -> list[str]:
    characters = data.get("characters") if isinstance(data.get("characters"), dict) else {}
    player_id = _player_id(data)
    result: list[str] = []
    for character_id, card in characters.items():
        if character_id == player_id or not isinstance(card, dict):
            continue
        if card.get("cast_status") in {"known_core", "known_support", "hidden_core"}:
            result.append(str(character_id))
    return result


def _default_character_functions(data: dict[str, Any]) -> dict[str, Any]:
    characters = data.get("characters") if isinstance(data.get("characters"), dict) else {}
    result: dict[str, Any] = {}
    for character_id in _significant_character_ids(data):
        card = characters.get(character_id, {}) if isinstance(characters.get(character_id), dict) else {}
        behavior = card.get("behavior") if isinstance(card.get("behavior"), dict) else {}
        life = card.get("life_outside_player") if isinstance(card.get("life_outside_player"), dict) else {}
        result[character_id] = {
            "story_role": _text(card.get("role"), "значимый участник истории"),
            "pressure_source": _text(life.get("private_problem") or behavior.get("inconvenient_pattern"), "собственная проблема создаёт давление"),
            "conflict_function": _text(behavior.get("conflict_style"), "осложняет ситуацию своим способом реагировать"),
            "private_goal": _text(card.get("goal"), "добивается собственной цели"),
            "do_not_flatten_into": _text(behavior.get("care_style"), "не превращать в удобную поддержку героини"),
        }
    return result


def _default_hooks(data: dict[str, Any]) -> list[dict[str, Any]]:
    story_plan = data.get("story_plan") if isinstance(data.get("story_plan"), dict) else {}
    open_threads = _string_list(story_plan.get("open_threads"), 4)
    if not open_threads:
        open_threads = [_text(story_plan.get("central_conflict"), "центральный конфликт должен начать давить на героиню")]
    result = []
    for index, thread in enumerate(open_threads, start=1):
        result.append({
            "id": f"hook_{index:02d}",
            "hook": thread,
            "status": "active",
            "related_character_ids": [],
            "pressure": "крючок должен возвращаться через людей, последствия или среду",
            "next_escalation": "дать новый видимый след, цену или неправильный вывод",
            "earliest_turn": max(1, index),
        })
    return result


def _default_hidden_lore(data: dict[str, Any]) -> list[dict[str, Any]]:
    future_locks = data.get("future_locks") if isinstance(data.get("future_locks"), dict) else {}
    story_plan = data.get("story_plan") if isinstance(data.get("story_plan"), dict) else {}
    locked = _string_list(future_locks.get("do_not_reveal_yet"), 4)
    if not locked:
        locked = [_text(story_plan.get("central_conflict"), "у центрального конфликта есть скрытая причинная основа")]
    return [
        {
            "id": f"lore_{index:02d}",
            "truth": item,
            "status": "locked",
            "reveal_policy": "раскрывать через последствия, свидетельства и отношения, а не авторское объяснение",
            "known_by": [],
            "related_character_ids": [],
            "evidence_chain": [],
        }
        for index, item in enumerate(locked, start=1)
    ]


def _default_reveals(data: dict[str, Any], hidden_lore: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, lore in enumerate(hidden_lore[:4], start=1):
        result.append({
            "id": f"reveal_{index:02d}",
            "reveal": _text(lore.get("truth"), "скрытая правда"),
            "status": "locked",
            "earliest_turn": max(3, index + 2),
            "latest_turn": 0,
            "prerequisites": ["до раскрытия должны появиться минимум два сценических основания"],
            "forbidden_before": "не раскрывать прямым объяснением в стартовых сценах",
            "related_character_ids": _string_list(lore.get("related_character_ids"), 8),
        })
    return result


def _default_conflicts(data: dict[str, Any]) -> list[dict[str, Any]]:
    story_plan = data.get("story_plan") if isinstance(data.get("story_plan"), dict) else {}
    return [{
        "id": "conflict_01",
        "description": _text(story_plan.get("central_conflict"), "цели героини сталкиваются с чужим давлением"),
        "status": "active",
        "sides": [],
        "pressure": "конфликт должен менять отношения, положение или цену бездействия",
        "next_escalation": "чужая цель создаёт новое неудобное последствие",
        "do_not_resolve_with": ["один спокойный разговор", "мгновенное признание ошибки", "удобное объяснение лора"],
    }]


def _default_events(data: dict[str, Any], hooks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    story_plan = data.get("story_plan") if isinstance(data.get("story_plan"), dict) else {}
    significant = _significant_character_ids(data)
    first_known = None
    characters = data.get("characters") if isinstance(data.get("characters"), dict) else {}
    for character_id in significant:
        card = characters.get(character_id, {}) if isinstance(characters.get(character_id), dict) else {}
        if card.get("cast_status") in {"known_core", "known_support"}:
            first_known = character_id
            break
    participant = [first_known] if first_known else []
    opening = _text(story_plan.get("opening_scene_intent"), "первое значимое давление стартовой ситуации")
    hook_1 = _text((hooks[0] if hooks else {}).get("hook"), "первый незакрытый крючок")
    hook_2 = _text((hooks[1] if len(hooks) > 1 else {}).get("hook"), "последствие чужой цели")
    return [
        {
            "id": "event_01",
            "title": "Стартовое давление",
            "status": "ready",
            "priority": 90,
            "earliest_turn": 1,
            "latest_turn": 2,
            "conditions": ["естественно продолжает текущий кадр"],
            "participants": participant,
            "purpose": opening,
            "scene_pressure": "дать реальный сдвиг, а не бытовую петлю",
            "next_if_ignored": "давление возвращается через действие NPC или внешнее последствие",
            "time_hint": "в текущей или ближайшей сцене",
            "skip_unit": "hours",
            "skip_amount": 1,
        },
        {
            "id": "event_02",
            "title": "Возврат незакрытого крючка",
            "status": "planned",
            "priority": 70,
            "earliest_turn": 2,
            "latest_turn": 5,
            "conditions": ["не повторять стартовую сцену теми же словами"],
            "participants": [],
            "purpose": hook_1,
            "scene_pressure": "дать новый след, ошибку или цену",
            "next_if_ignored": "крючок становится заметнее и менее удобным",
            "time_hint": "через несколько сцен или после естественной паузы",
            "skip_unit": "days",
            "skip_amount": 2,
        },
        {
            "id": "event_03",
            "title": "Самостоятельный шаг другого персонажа",
            "status": "planned",
            "priority": 60,
            "earliest_turn": 3,
            "latest_turn": 7,
            "conditions": ["NPC действует ради своей цели, а не выдаёт героине задание"],
            "participants": participant,
            "purpose": hook_2,
            "scene_pressure": "изменить отношения или положение без решения за героиню",
            "next_if_ignored": "NPC продолжает план без разрешения игрока",
            "time_hint": "когда текущая сцена достигнет естественной точки перехода",
            "skip_unit": "weeks",
            "skip_amount": 1,
        },
    ]


def _normalise_id_items(items: Any, prefix: str, normaliser) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    used: set[str] = set()
    for index, item in enumerate(_list(items), start=1):
        if not isinstance(item, dict):
            item = {"description": _text(item)}
        item_id = _safe_id(item.get("id"), f"{prefix}_{index:02d}")
        if item_id in used:
            item_id = f"{item_id}_{index:02d}"
        used.add(item_id)
        result.append(normaliser(item, item_id, index))
    return result


def _normalise_lore(item: dict[str, Any], item_id: str, _: int) -> dict[str, Any]:
    return {
        **item,
        "id": item_id,
        "truth": _text(item.get("truth") or item.get("description"), "скрытая причинная истина"),
        "status": _text(item.get("status"), "locked"),
        "reveal_policy": _text(item.get("reveal_policy"), "раскрывать через сценические основания"),
        "known_by": _string_list(item.get("known_by"), 12),
        "related_character_ids": _string_list(item.get("related_character_ids"), 12),
        "evidence_chain": _string_list(item.get("evidence_chain"), 12),
    }


def _normalise_hook(item: dict[str, Any], item_id: str, index: int) -> dict[str, Any]:
    status = _text(item.get("status"), "active")
    return {
        **item,
        "id": item_id,
        "hook": _text(item.get("hook") or item.get("description"), "незакрытый сюжетный крючок"),
        "status": status if status in HOOK_STATUSES else "active",
        "related_character_ids": _string_list(item.get("related_character_ids"), 12),
        "pressure": _text(item.get("pressure"), "возвращается через последствия или отношения"),
        "next_escalation": _text(item.get("next_escalation"), "дать новый видимый сдвиг"),
        "earliest_turn": _integer(item.get("earliest_turn"), max(1, index)),
    }


def _normalise_reveal(item: dict[str, Any], item_id: str, index: int) -> dict[str, Any]:
    status = _text(item.get("status"), "locked")
    return {
        **item,
        "id": item_id,
        "reveal": _text(item.get("reveal") or item.get("truth") or item.get("description"), "скрытая правда"),
        "status": status if status in REVEAL_STATUSES else "locked",
        "earliest_turn": _integer(item.get("earliest_turn"), max(3, index + 2)),
        "latest_turn": _integer(item.get("latest_turn"), 0),
        "prerequisites": _string_list(item.get("prerequisites"), 10),
        "forbidden_before": _text(item.get("forbidden_before"), "до сценических оснований"),
        "related_character_ids": _string_list(item.get("related_character_ids"), 12),
    }


def _normalise_conflict(item: dict[str, Any], item_id: str, _: int) -> dict[str, Any]:
    status = _text(item.get("status"), "active")
    return {
        **item,
        "id": item_id,
        "description": _text(item.get("description"), "активный конфликт"),
        "status": status if status in CONFLICT_STATUSES else "active",
        "sides": _string_list(item.get("sides"), 12),
        "pressure": _text(item.get("pressure"), "создаёт цену и столкновение целей"),
        "next_escalation": _text(item.get("next_escalation"), "обострить через действие или последствие"),
        "do_not_resolve_with": _string_list(item.get("do_not_resolve_with"), 10),
    }


def _normalise_event(item: dict[str, Any], item_id: str, index: int) -> dict[str, Any]:
    status = _text(item.get("status"), "planned")
    skip_unit = _text(item.get("skip_unit"), "days")
    if skip_unit not in TIME_SKIP_UNITS:
        skip_unit = "days"
    return {
        **item,
        "id": item_id,
        "title": _text(item.get("title"), f"Событие {index}"),
        "status": status if status in EVENT_STATUSES else "planned",
        "priority": _integer(item.get("priority"), max(10, 80 - index * 10), 0, 100),
        "earliest_turn": _integer(item.get("earliest_turn"), max(1, index)),
        "latest_turn": _integer(item.get("latest_turn"), 0),
        "conditions": _string_list(item.get("conditions"), 10),
        "participants": _string_list(item.get("participants"), 12),
        "purpose": _text(item.get("purpose"), "продвинуть историю значимым сдвигом"),
        "scene_pressure": _text(item.get("scene_pressure"), "изменить положение, риск или отношения"),
        "next_if_ignored": _text(item.get("next_if_ignored"), "событие возвращается изменённым последствием"),
        "time_hint": _text(item.get("time_hint"), "при первой естественной возможности"),
        "skip_unit": skip_unit,
        "skip_amount": _integer(item.get("skip_amount"), max(1, index), 0, 365),
    }


def normalise_director_bible(value: Any, data: dict[str, Any]) -> dict[str, Any]:
    source = deepcopy(value) if isinstance(value, dict) else {}
    story_plan = data.get("story_plan") if isinstance(data.get("story_plan"), dict) else {}

    world_truth = source.get("world_truth") if isinstance(source.get("world_truth"), dict) else {}
    world_truth = {
        **world_truth,
        "core_truth": _text(world_truth.get("core_truth") or story_plan.get("main_premise"), "история имеет конкретную причинную основу"),
        "world_rules": _string_list(world_truth.get("world_rules"), 12),
        "hidden_cause": _text(world_truth.get("hidden_cause") or story_plan.get("central_conflict"), "скрытая причина связана с центральным конфликтом"),
    }

    hidden_lore_source = source.get("hidden_lore")
    if not isinstance(hidden_lore_source, list) or not hidden_lore_source:
        hidden_lore_source = _default_hidden_lore(data)
    hidden_lore = _normalise_id_items(hidden_lore_source, "lore", _normalise_lore)

    hooks_source = source.get("story_hooks")
    if not isinstance(hooks_source, list) or not hooks_source:
        hooks_source = _default_hooks(data)
    hooks = _normalise_id_items(hooks_source, "hook", _normalise_hook)

    reveals_source = source.get("planned_reveals")
    if not isinstance(reveals_source, list) or not reveals_source:
        reveals_source = _default_reveals(data, hidden_lore)
    reveals = _normalise_id_items(reveals_source, "reveal", _normalise_reveal)

    conflicts_source = source.get("active_conflicts")
    if not isinstance(conflicts_source, list) or not conflicts_source:
        conflicts_source = _default_conflicts(data)
    conflicts = _normalise_id_items(conflicts_source, "conflict", _normalise_conflict)

    events_source = source.get("event_queue")
    existing_events = list(events_source) if isinstance(events_source, list) else []
    if len(existing_events) < 3:
        defaults = _default_events(data, hooks)
        existing_events += defaults[len(existing_events):]
    events_source = existing_events
    events = _normalise_id_items(events_source, "event", _normalise_event)

    functions_source = source.get("character_functions") if isinstance(source.get("character_functions"), dict) else {}
    default_functions = _default_character_functions(data)
    functions: dict[str, Any] = {}
    for character_id in _significant_character_ids(data):
        entry = functions_source.get(character_id) if isinstance(functions_source.get(character_id), dict) else {}
        fallback = default_functions.get(character_id, {})
        functions[character_id] = {
            **entry,
            "story_role": _text(entry.get("story_role") or fallback.get("story_role"), "значимый участник"),
            "pressure_source": _text(entry.get("pressure_source") or fallback.get("pressure_source"), "собственная проблема"),
            "conflict_function": _text(entry.get("conflict_function") or fallback.get("conflict_function"), "осложняет конфликт"),
            "private_goal": _text(entry.get("private_goal") or fallback.get("private_goal"), "добивается собственной цели"),
            "do_not_flatten_into": _text(entry.get("do_not_flatten_into") or fallback.get("do_not_flatten_into"), "не делать удобной функцией героини"),
        }

    pacing = source.get("pacing") if isinstance(source.get("pacing"), dict) else {}
    result = {
        **source,
        "version": 1,
        "world_truth": world_truth,
        "hidden_lore": hidden_lore,
        "character_functions": functions,
        "story_hooks": hooks,
        "planned_reveals": reveals,
        "active_conflicts": conflicts,
        "event_queue": events,
        "time_anchors": _list(source.get("time_anchors")),
        "time_flow": _normalise_time_flow(source.get("time_flow"), story_plan),
        "do_not_resolve_early": _string_list(source.get("do_not_resolve_early") or story_plan.get("forbidden_drift"), 16),
        "continuity_truths": _string_list(source.get("continuity_truths"), 20),
        "future_consequences": _string_list(source.get("future_consequences"), 20),
        "pacing": {
            **pacing,
            "current_phase": _text(pacing.get("current_phase") or story_plan.get("current_story_position"), "act_1_start"),
            "quiet_scene_budget": _integer(pacing.get("quiet_scene_budget"), 1, 0, 5),
            "major_reveal_spacing": _integer(pacing.get("major_reveal_spacing"), 2, 1, 12),
            "notes": _string_list(pacing.get("notes"), 10),
        },
        "history": [item for item in _list(source.get("history"))[-30:] if isinstance(item, dict)],
    }
    return result


def prepare_director_bible(data: dict[str, Any]) -> dict[str, Any]:
    bible = normalise_director_bible(data.get("director_bible"), data)
    data["director_bible"] = bible
    return bible


def validate_director_bible(data: dict[str, Any]) -> list[str]:
    bible = prepare_director_bible(data)
    errors: list[str] = []
    known_ids = set(_character_ids(data))

    for field, minimum in (("hidden_lore", 1), ("story_hooks", 1), ("planned_reveals", 1), ("active_conflicts", 1), ("event_queue", 3)):
        items = bible.get(field)
        if not isinstance(items, list) or len(items) < minimum:
            errors.append(f"director_bible.{field} must contain at least {minimum} item(s)")

    for collection in ("hidden_lore", "story_hooks", "planned_reveals", "active_conflicts", "event_queue"):
        ids = [item.get("id") for item in bible.get(collection, []) if isinstance(item, dict)]
        if len(ids) != len(set(ids)):
            errors.append(f"director_bible.{collection} contains duplicate ids")

    for event in bible.get("event_queue", []):
        if not isinstance(event, dict):
            continue
        unknown = [cid for cid in event.get("participants", []) if cid not in known_ids]
        if unknown:
            errors.append(f"director_bible.event_queue.{event.get('id')} has unknown participants: {unknown}")
        latest = int(event.get("latest_turn", 0) or 0)
        earliest = int(event.get("earliest_turn", 0) or 0)
        if latest and latest < earliest:
            errors.append(f"director_bible.event_queue.{event.get('id')} latest_turn is before earliest_turn")

    current_state = data.get("current_state") if isinstance(data.get("current_state"), dict) else {}
    hidden_ids = {
        character_id
        for character_id, card in (data.get("characters") or {}).items()
        if isinstance(card, dict) and card.get("cast_status") == "hidden_core"
    }
    visible_start = set(_string_list(current_state.get("active_character_ids")) + _string_list(current_state.get("nearby_character_ids")))
    leaked = sorted(hidden_ids & visible_start)
    if leaked:
        errors.append(f"hidden_core characters cannot be active/nearby at start: {leaked}")
    return errors


def _compact_item(item: dict[str, Any], allowed: tuple[str, ...]) -> dict[str, Any]:
    return {key: item.get(key) for key in allowed if key in item}


def build_director_guidance(bundle: dict[str, Any]) -> dict[str, Any]:
    bible = normalise_director_bible(bundle.get("director_bible"), bundle)
    current_state = bundle.get("current_state") if isinstance(bundle.get("current_state"), dict) else {}
    current_turn = _integer(current_state.get("turn_number"), 0)
    next_turn = current_turn + 1
    active_ids = set(_string_list(current_state.get("active_character_ids")) + _string_list(current_state.get("nearby_character_ids")))

    event_candidates = [
        item for item in bible.get("event_queue", [])
        if isinstance(item, dict)
        and item.get("status") in {"planned", "ready", "triggered", "deferred"}
        and int(item.get("earliest_turn", 0) or 0) <= next_turn
    ]
    if not event_candidates:
        event_candidates = [
            item for item in bible.get("event_queue", [])
            if isinstance(item, dict) and item.get("status") in {"planned", "ready", "deferred"}
        ]
    event_candidates.sort(key=lambda item: (-int(item.get("priority", 0) or 0), int(item.get("earliest_turn", 0) or 0)))
    due_events = [
        _compact_item(item, ("id", "title", "status", "priority", "earliest_turn", "latest_turn", "conditions", "participants", "purpose", "scene_pressure", "next_if_ignored", "time_hint", "skip_unit", "skip_amount"))
        for item in event_candidates[:4]
    ]

    relevant_ids = set(active_ids)
    for event in due_events:
        relevant_ids.update(_string_list(event.get("participants")))
    functions = {
        character_id: entry
        for character_id, entry in bible.get("character_functions", {}).items()
        if character_id in relevant_ids and isinstance(entry, dict)
    }

    reveals = [
        _compact_item(item, ("id", "reveal", "status", "earliest_turn", "latest_turn", "prerequisites", "forbidden_before", "related_character_ids"))
        for item in bible.get("planned_reveals", [])
        if isinstance(item, dict) and item.get("status") != "revealed"
    ][:5]

    return {
        "visibility": "author_only_never_render_or_quote",
        "rules": {
            "queue_is_not_railroad": "события — вероятные давления; адаптируй их к действиям игрока, не заставляя героиню принимать решение",
            "no_spoilers": "hidden_lore, planned_reveals и функции hidden_core нельзя выводить в видимый текст до выполненного раскрытия",
            "no_boring_loop": "если в текущем кадре нет meaningful beat, двигай ближайшее допустимое событие или последствие",
            "preserve_causality": "не создавай новый тайный ответ на ходу, если уже есть world_truth или hidden_lore",
            "patch_status_only": "после сцены обновляй статусы через director_bible_patches; не переписывай world_truth",
        },
        "current_turn": current_turn,
        "tone_control": {
            "dry_sarcasm_target_share": "примерно 5–7% видимого текста, не квота и не обязанность",
            "preferred_dose": "обычно одна короткая сухая реплика или наблюдение; иногда ноль",
            "source": "только подходящий голос персонажа или редкая авторская деталь, не одинаковая язвительность всех NPC",
            "avoid": "не ставить в каждый абзац, не перебивать горе, страх, интимность или серьёзное раскрытие",
        },
        "world_truth": bible.get("world_truth", {}),
        "hidden_lore": [
            _compact_item(item, ("id", "truth", "status", "reveal_policy", "known_by", "related_character_ids", "evidence_chain"))
            for item in bible.get("hidden_lore", [])[:6]
            if isinstance(item, dict)
        ],
        "character_functions": functions,
        "active_hooks": [
            _compact_item(item, ("id", "hook", "status", "related_character_ids", "pressure", "next_escalation", "earliest_turn"))
            for item in bible.get("story_hooks", [])
            if isinstance(item, dict) and item.get("status") in {"active", "advanced"}
        ][:6],
        "active_conflicts": [
            _compact_item(item, ("id", "description", "status", "sides", "pressure", "next_escalation", "do_not_resolve_with"))
            for item in bible.get("active_conflicts", [])
            if isinstance(item, dict) and item.get("status") not in {"resolved", "dormant"}
        ][:5],
        "planned_reveals": reveals,
        "due_or_next_events": due_events,
        "do_not_resolve_early": bible.get("do_not_resolve_early", [])[:10],
        "continuity_truths": bible.get("continuity_truths", [])[-10:],
        "future_consequences": bible.get("future_consequences", [])[-8:],
        "pacing": bible.get("pacing", {}),
        "time_flow": bible.get("time_flow", {}),
    }


def _find_by_id(items: list[dict[str, Any]], item_id: str) -> dict[str, Any] | None:
    for item in items:
        if isinstance(item, dict) and item.get("id") == item_id:
            return item
    return None


def _reject(result: dict[str, Any], patch_type: str, item_id: str, reason: str) -> None:
    rejected = result.setdefault("rejected", [])
    rejected.append({"type": patch_type, "id": item_id, "reason": reason})


def _valid_source(patch: dict[str, Any]) -> bool:
    return bool(_text(patch.get("reason")) and _text(patch.get("source_in_scene")))


def apply_director_bible_patches(
    storage: Any,
    session_id: str,
    scene_response: dict[str, Any],
    bundle: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    proposed = scene_response.get("proposed_updates") if isinstance(scene_response.get("proposed_updates"), dict) else {}
    patches = proposed.get("director_bible_patches")
    if not isinstance(patches, dict) or not patches:
        return result

    data_for_normalise = {**bundle, "director_bible": storage.read_json(session_id, "director_bible.json", default=bundle.get("director_bible", {}))}
    bible = normalise_director_bible(data_for_normalise.get("director_bible"), data_for_normalise)
    current_state = storage.read_json(session_id, "current_state.json", default=bundle.get("current_state", {}))
    current_turn = _integer((current_state or {}).get("turn_number"), 0)
    applied_count = 0
    history_entries: list[dict[str, Any]] = []

    groups = (
        ("event_updates", "event_queue", EVENT_STATUSES),
        ("hook_updates", "story_hooks", HOOK_STATUSES),
        ("reveal_updates", "planned_reveals", REVEAL_STATUSES),
        ("conflict_updates", "active_conflicts", CONFLICT_STATUSES),
    )
    for patch_key, collection_key, allowed_statuses in groups:
        for raw_patch in _list(patches.get(patch_key)):
            if not isinstance(raw_patch, dict):
                continue
            item_id = _safe_id(raw_patch.get("id"), "missing")
            target = _find_by_id(bible.get(collection_key, []), item_id)
            if target is None:
                _reject(result, patch_key, item_id, "unknown director item id")
                continue
            if not _valid_source(raw_patch):
                _reject(result, patch_key, item_id, "reason and source_in_scene are required")
                continue
            next_status = raw_patch.get("status")
            if next_status is not None:
                next_status = _text(next_status)
                if next_status not in allowed_statuses:
                    _reject(result, patch_key, item_id, f"invalid status: {next_status}")
                    continue
                if collection_key == "event_queue" and next_status not in _EVENT_TRANSITIONS.get(target.get("status"), {target.get("status")}):
                    _reject(result, patch_key, item_id, f"invalid event transition {target.get('status')} -> {next_status}")
                    continue
                if collection_key == "planned_reveals":
                    if next_status == "revealed" and current_turn < int(target.get("earliest_turn", 0) or 0):
                        _reject(result, patch_key, item_id, "reveal attempted before earliest_turn")
                        continue
                    if next_status not in _REVEAL_TRANSITIONS.get(target.get("status"), {target.get("status")}):
                        _reject(result, patch_key, item_id, f"invalid reveal transition {target.get('status')} -> {next_status}")
                        continue
                target["status"] = next_status

            for field in ("pressure", "next_escalation", "next_if_ignored", "time_hint"):
                if field in raw_patch and _text(raw_patch.get(field)):
                    target[field] = _text(raw_patch.get(field))
            if collection_key == "event_queue":
                if "earliest_turn" in raw_patch:
                    target["earliest_turn"] = _integer(raw_patch.get("earliest_turn"), target.get("earliest_turn", current_turn + 1))
                if "priority" in raw_patch:
                    target["priority"] = _integer(raw_patch.get("priority"), target.get("priority", 50), 0, 100)

            target["last_update_reason"] = _text(raw_patch.get("reason"))
            target["last_source_in_scene"] = _text(raw_patch.get("source_in_scene"))
            target["last_updated_turn"] = current_turn
            applied_count += 1
            history_entries.append({
                "turn": current_turn,
                "type": patch_key,
                "id": item_id,
                "status": target.get("status"),
                "reason": target["last_update_reason"],
                "source_in_scene": target["last_source_in_scene"],
            })

    for consequence in _string_list(patches.get("add_future_consequences"), 10):
        if consequence not in bible["future_consequences"]:
            bible["future_consequences"].append(consequence)
            applied_count += 1

    pacing_patch = patches.get("pacing_patch") if isinstance(patches.get("pacing_patch"), dict) else {}
    if pacing_patch:
        if _text(pacing_patch.get("current_phase")):
            bible["pacing"]["current_phase"] = _text(pacing_patch.get("current_phase"))
            applied_count += 1
        if "quiet_scene_budget" in pacing_patch:
            bible["pacing"]["quiet_scene_budget"] = _integer(pacing_patch.get("quiet_scene_budget"), bible["pacing"].get("quiet_scene_budget", 1), 0, 5)
            applied_count += 1
        notes = _string_list(pacing_patch.get("add_notes"), 6)
        for note in notes:
            if note not in bible["pacing"]["notes"]:
                bible["pacing"]["notes"].append(note)
                applied_count += 1

    if applied_count:
        bible["history"] = (bible.get("history", []) + history_entries)[-30:]
        storage.write_json(session_id, "director_bible.json", bible)
        result.setdefault("applied", {})["director_bible_patches"] = applied_count
        result.setdefault("next_builder_hints", {})["director_bible"] = {
            "active_hook_count": sum(1 for item in bible["story_hooks"] if item.get("status") in {"active", "advanced"}),
            "pending_event_count": sum(1 for item in bible["event_queue"] if item.get("status") not in {"completed", "blocked"}),
            "available_reveal_count": sum(1 for item in bible["planned_reveals"] if item.get("status") == "available"),
        }
    return result
