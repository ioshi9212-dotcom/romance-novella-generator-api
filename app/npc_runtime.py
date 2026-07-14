from __future__ import annotations

from copy import deepcopy
from typing import Any


NPC_RUNTIME_FIELDS = (
    "current_goal",
    "current_route",
    "current_pressure",
    "current_mood",
    "current_urge",
    "behavior_mode",
    "last_trigger",
    "unresolved_emotion",
    "next_self_action_if_ignored",
    "change_stage",
)

CLEARABLE_NPC_RUNTIME_FIELDS = {
    "current_mood",
    "current_urge",
    "last_trigger",
    "unresolved_emotion",
}

CHANGE_STAGES = {
    "baseline",
    "unaware",
    "defensive",
    "admitted_not_changed",
    "trying",
    "relapsed",
    "stable_change",
}


def _text(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def build_initial_npc_runtime(card: dict[str, Any], existing: Any = None) -> dict[str, Any]:
    """Create a complete runtime entry without replacing user-written values."""
    card = card if isinstance(card, dict) else {}
    state = deepcopy(existing) if isinstance(existing, dict) else {}
    life = card.get("life_outside_player") if isinstance(card.get("life_outside_player"), dict) else {}
    behavior = card.get("behavior") if isinstance(card.get("behavior"), dict) else {}
    inner = card.get("inner_logic") if isinstance(card.get("inner_logic"), dict) else {}

    state["character_id"] = str(state.get("character_id") or card.get("id") or "unknown_npc")
    state["current_goal"] = _text(state.get("current_goal"), _text(card.get("goal"), "добиться собственной цели"))
    state["current_route"] = _text(
        state.get("current_route"),
        _text(life.get("current_obligation"), "заниматься собственными делами вне героини"),
    )
    state["current_pressure"] = _text(
        state.get("current_pressure"),
        _text(life.get("private_problem"), _text(inner.get("main_fear"), "личное давление вне текущей сцены")),
    )
    state["current_mood"] = _text(
        state.get("current_mood"),
        "внутреннее напряжение из-за текущего давления",
    )
    state["current_urge"] = _text(
        state.get("current_urge"),
        _text(behavior.get("inconvenient_pattern"), "действовать привычным способом, даже если это неудобно другим"),
    )
    state["behavior_mode"] = _text(
        state.get("behavior_mode"),
        _text(behavior.get("conflict_style"), "прямо добиваться ответа или результата"),
    )
    state["last_trigger"] = _text(
        state.get("last_trigger"),
        "стартовая ситуация и собственные текущие обязательства",
    )
    state["unresolved_emotion"] = _text(
        state.get("unresolved_emotion"),
        _text(inner.get("main_fear"), "невыраженное напряжение, которое ещё не разрешено поступками"),
    )
    state["next_self_action_if_ignored"] = _text(
        state.get("next_self_action_if_ignored"),
        _text(behavior.get("inconvenient_pattern"), "продолжить собственный план без ожидания героини"),
    )
    stage = str(state.get("change_stage") or "baseline").strip()
    state["change_stage"] = stage if stage in CHANGE_STAGES else "baseline"
    state["last_updated_turn"] = int(state.get("last_updated_turn") or 0)
    state["history"] = [item for item in (state.get("history") or []) if isinstance(item, dict)][-12:]
    return state


def compact_npc_runtime_entry(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result = {
        "character_id": value.get("character_id"),
        **{field: value.get(field) for field in NPC_RUNTIME_FIELDS},
        "last_updated_turn": value.get("last_updated_turn", 0),
    }
    result["history"] = [
        {
            "turn": item.get("turn"),
            "changes": item.get("changes", {}),
            "reason": item.get("reason"),
            "source_in_scene": item.get("source_in_scene"),
        }
        for item in (value.get("history") or [])[-3:]
        if isinstance(item, dict)
    ]
    return result


def apply_npc_runtime_patch(
    existing: Any,
    patch: dict[str, Any],
    *,
    turn_number: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge one evidence-based scene patch and keep a short change history."""
    state = deepcopy(existing) if isinstance(existing, dict) else {}
    changed: dict[str, Any] = {}

    clear_fields = patch.get("clear_fields") if isinstance(patch.get("clear_fields"), list) else []
    for field in clear_fields:
        if field in CLEARABLE_NPC_RUNTIME_FIELDS and field in state:
            state.pop(field, None)
            changed[field] = None

    for field in NPC_RUNTIME_FIELDS:
        if field not in patch:
            continue
        value = patch.get(field)
        if value is None:
            if field in CLEARABLE_NPC_RUNTIME_FIELDS and field in state:
                state.pop(field, None)
                changed[field] = None
            continue
        if not isinstance(value, str) or not value.strip():
            continue
        normalized = value.strip()
        if field == "change_stage" and normalized not in CHANGE_STAGES:
            continue
        if state.get(field) != normalized:
            state[field] = normalized
            changed[field] = normalized

    if not changed:
        return state, {}

    state["character_id"] = str(patch.get("character_id") or state.get("character_id") or "unknown_npc")
    state["last_updated_turn"] = turn_number
    history = [item for item in (state.get("history") or []) if isinstance(item, dict)]
    history.append(
        {
            "turn": turn_number,
            "changes": changed,
            "reason": str(patch.get("reason") or "").strip(),
            "source_in_scene": str(patch.get("source_in_scene") or "").strip(),
        }
    )
    state["history"] = history[-12:]
    return state, changed
