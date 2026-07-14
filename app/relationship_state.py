from __future__ import annotations

from copy import deepcopy
from typing import Any


DIRECTION_SCORE_FIELDS = (
    "trust",
    "attachment",
    "attraction",
    "respect",
    "resentment",
    "fear",
    "jealousy",
    "dependency",
    "protectiveness",
)

DIRECTION_TEXT_FIELDS = (
    "current_view",
    "current_need",
    "current_expectation",
    "access_boundary",
    "interpretation_bias",
    "unresolved_emotion",
    "care_risk",
)


def _text(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def _list(value: Any, fallback: list[Any] | None = None) -> list[Any]:
    if isinstance(value, list):
        cleaned = [item for item in value if str(item).strip()]
        if cleaned:
            return cleaned
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return list(fallback or [])


def _score(value: Any, fallback: int) -> int:
    try:
        return max(0, min(100, int(float(value))))
    except Exception:
        return fallback


def _role_kind(card: dict[str, Any]) -> str:
    role = str(card.get("role") or "").lower()
    if any(word in role for word in ("friend", "best friend", "подруг", "друг")):
        return "friend"
    if any(word in role for word in ("brother", "sister", "mother", "father", "family", "брат", "сестр", "мать", "отец", "сем")):
        return "family"
    if any(word in role for word in ("boyfriend", "girlfriend", "husband", "wife", "romance", "lover", "crush", "парень", "муж", "влюб", "быв")):
        return "romance"
    if any(word in role for word in ("colleague", "coworker", "boss", "manager", "коллег", "началь", "сотруд")):
        return "colleague"
    return "default"


def _display_name(card: dict[str, Any], fallback: str) -> str:
    for key in ("display_name", "visible_name", "name_ru", "russian_name", "name"):
        value = card.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def _direction_defaults(source_card: dict[str, Any], target_card: dict[str, Any], *, source_is_player: bool) -> dict[str, Any]:
    source_name = _display_name(source_card, str(source_card.get("id") or "Персонаж"))
    target_name = _display_name(target_card, str(target_card.get("id") or "другой человек"))
    kind = _role_kind(source_card if not source_is_player else target_card)

    target_behavior = target_card.get("behavior") if isinstance(target_card.get("behavior"), dict) else {}
    source_behavior = source_card.get("behavior") if isinstance(source_card.get("behavior"), dict) else {}
    source_inner = source_card.get("inner_logic") if isinstance(source_card.get("inner_logic"), dict) else {}
    target_inner = target_card.get("inner_logic") if isinstance(target_card.get("inner_logic"), dict) else {}

    if source_is_player:
        score_templates = {
            "friend": {"trust": 56, "attachment": 58, "attraction": 0, "respect": 48, "resentment": 24, "fear": 5, "jealousy": 8, "dependency": 22, "protectiveness": 42},
            "family": {"trust": 48, "attachment": 72, "attraction": 0, "respect": 42, "resentment": 38, "fear": 8, "jealousy": 4, "dependency": 35, "protectiveness": 68},
            "romance": {"trust": 42, "attachment": 38, "attraction": 32, "respect": 38, "resentment": 26, "fear": 18, "jealousy": 14, "dependency": 18, "protectiveness": 28},
            "colleague": {"trust": 45, "attachment": 14, "attraction": 4, "respect": 50, "resentment": 18, "fear": 3, "jealousy": 2, "dependency": 12, "protectiveness": 12},
            "default": {"trust": 42, "attachment": 24, "attraction": 8, "respect": 38, "resentment": 18, "fear": 6, "jealousy": 4, "dependency": 10, "protectiveness": 18},
        }
        scores = score_templates[kind]
        current_view = f"{source_name} знает {target_name} не объективно: привычная близость смешана с накопившимися ожиданиями."
        current_need = "сохранить право самой определять дистанцию и не объяснять всё немедленно"
        current_expectation = "ожидает, что близкий человек заметит её границы без длинных объяснений"
        access_boundary = "считает личные решения и физическую дистанцию своей территорией, даже в близких отношениях"
        interpretation_bias = f"склонна заранее ждать, что {target_name} снова поступит привычным неудобным способом"
        unresolved_emotion = _text(target_inner.get("contradiction"), "смешанная привязанность и раздражение")
        grievance = _text(target_behavior.get("inconvenient_pattern"), "другой человек слишком легко решает, что знает, как будет лучше")
        wrong_belief = f"иногда считает, что мотивы {target_name} проще и очевиднее, чем они есть на самом деле"
        care_risk = f"может оттолкнуть {target_name} сухостью именно тогда, когда пытается защитить собственные границы"
    else:
        score_templates = {
            "friend": {"trust": 64, "attachment": 76, "attraction": 0, "respect": 46, "resentment": 22, "fear": 20, "jealousy": 14, "dependency": 34, "protectiveness": 72},
            "family": {"trust": 52, "attachment": 82, "attraction": 0, "respect": 40, "resentment": 34, "fear": 18, "jealousy": 6, "dependency": 48, "protectiveness": 78},
            "romance": {"trust": 48, "attachment": 78, "attraction": 82, "respect": 44, "resentment": 28, "fear": 42, "jealousy": 48, "dependency": 38, "protectiveness": 62},
            "colleague": {"trust": 46, "attachment": 18, "attraction": 6, "respect": 56, "resentment": 20, "fear": 8, "jealousy": 5, "dependency": 18, "protectiveness": 20},
            "default": {"trust": 44, "attachment": 38, "attraction": 16, "respect": 42, "resentment": 20, "fear": 16, "jealousy": 12, "dependency": 20, "protectiveness": 34},
        }
        scores = score_templates[kind]
        current_view = f"{source_name} воспринимает {target_name} через собственную потребность, страх и общую историю, а не нейтрально."
        current_need = _text(source_inner.get("core_need"), "получить подтверждение своей значимости в этих отношениях")
        current_expectation = _text(source_behavior.get("closeness_style"), "считает, что привычная близость даёт право не принимать первое уклончивое отстранение")
        access_boundary = _text(source_behavior.get("touch_style"), "считает некоторые вопросы и прикосновения естественными для их уровня близости")
        interpretation_bias = _text(source_inner.get("blind_spot"), f"слишком быстро объясняет поведение {target_name} через собственный страх")
        unresolved_emotion = _text(source_inner.get("main_fear"), "страх потерять место в жизни другого человека")
        grievance = f"{target_name} не даёт той ясности или близости, на которую {source_name} рассчитывает"
        wrong_belief = f"{source_name} временами уверен, что знает настоящую причину молчания или дистанции {target_name}"
        care_risk = _text(source_behavior.get("inconvenient_pattern"), "пытаясь помочь, усиливает давление и лишает другого пространства для ответа")

    return {
        "scores": scores,
        "current_view": current_view,
        "current_need": current_need,
        "current_expectation": current_expectation,
        "access_boundary": access_boundary,
        "interpretation_bias": interpretation_bias,
        "unresolved_emotion": unresolved_emotion,
        "unresolved_grievances": [grievance],
        "wrong_beliefs": [wrong_belief],
        "care_risk": care_risk,
    }


def normalize_direction(existing: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    source = deepcopy(existing) if isinstance(existing, dict) else {}
    legacy_scores = source.get("scores") if isinstance(source.get("scores"), dict) else {}
    scores: dict[str, int] = {}
    for field in DIRECTION_SCORE_FIELDS:
        value = legacy_scores.get(field, source.get(field))
        scores[field] = _score(value, int(fallback["scores"].get(field, 0)))

    result = {**source, "scores": scores}
    for field in DIRECTION_TEXT_FIELDS:
        result[field] = _text(source.get(field), str(fallback[field]))
    result["unresolved_grievances"] = _list(source.get("unresolved_grievances"), fallback["unresolved_grievances"])
    result["wrong_beliefs"] = _list(source.get("wrong_beliefs"), fallback["wrong_beliefs"])
    return result


def normalize_relationship_pair(
    relationship: Any,
    characters: dict[str, Any],
    protagonist_id: str | None = None,
) -> dict[str, Any]:
    rel = deepcopy(relationship) if isinstance(relationship, dict) else {}
    a = str(rel.get("character_a") or rel.get("a") or rel.get("from") or protagonist_id or "character_a")
    b = str(rel.get("character_b") or rel.get("b") or rel.get("to") or "character_b")
    if a == b:
        b = "character_b"

    a_card = characters.get(a) if isinstance(characters.get(a), dict) else {"id": a, "role": "npc"}
    b_card = characters.get(b) if isinstance(characters.get(b), dict) else {"id": b, "role": "npc"}
    a_is_player = a == protagonist_id or a_card.get("cast_status") == "player"
    b_is_player = b == protagonist_id or b_card.get("cast_status") == "player"

    legacy_scores = rel.get("scores") if isinstance(rel.get("scores"), dict) else {}
    legacy_a_view = rel.get("a_view_of_b") if isinstance(rel.get("a_view_of_b"), dict) else {}
    legacy_b_view = rel.get("b_view_of_a") if isinstance(rel.get("b_view_of_a"), dict) else {}

    a_source = rel.get("a_to_b") if isinstance(rel.get("a_to_b"), dict) else {
        "scores": legacy_scores,
        "current_view": legacy_a_view.get("summary"),
        "interpretation_bias": legacy_a_view.get("current_assumption"),
    }
    b_source = rel.get("b_to_a") if isinstance(rel.get("b_to_a"), dict) else {
        "scores": legacy_scores,
        "current_view": legacy_b_view.get("summary"),
        "interpretation_bias": legacy_b_view.get("current_assumption"),
    }

    a_to_b = normalize_direction(a_source, _direction_defaults(a_card, b_card, source_is_player=a_is_player and not b_is_player))
    b_to_a = normalize_direction(b_source, _direction_defaults(b_card, a_card, source_is_player=b_is_player and not a_is_player))

    shared_source = rel.get("shared") if isinstance(rel.get("shared"), dict) else {}
    shared_history = _list(shared_source.get("shared_history"), _list(rel.get("shared_history"), []))
    unresolved_threads = _list(shared_source.get("unresolved_threads"), _list(rel.get("open_threads"), []))
    recent_changes = _list(shared_source.get("recent_changes"), _list(rel.get("recent_changes"), []))[-10:]
    shared = {
        **shared_source,
        "type": _text(shared_source.get("type") or rel.get("type"), "relationship"),
        "status": _text(shared_source.get("status") or rel.get("status"), "отношения существуют и содержат разные ожидания с обеих сторон"),
        "shared_history": shared_history,
        "unresolved_threads": unresolved_threads,
        "recent_changes": recent_changes,
        "last_major_event": shared_source.get("last_major_event") or rel.get("last_major_event"),
    }

    pair_id = str(rel.get("pair_id") or "__".join(sorted((a, b))))
    return {
        **rel,
        "pair_id": pair_id,
        "character_a": a,
        "character_b": b,
        "shared": shared,
        "a_to_b": a_to_b,
        "b_to_a": b_to_a,
        # Legacy mirrors remain readable for old sessions and footer code.
        "type": shared["type"],
        "status": shared["status"],
        "scores": deepcopy(a_to_b["scores"]),
        "a_view_of_b": {"summary": a_to_b["current_view"], "current_assumption": a_to_b["interpretation_bias"]},
        "b_view_of_a": {"summary": b_to_a["current_view"], "current_assumption": b_to_a["interpretation_bias"]},
        "shared_history": shared["shared_history"],
        "recent_changes": shared["recent_changes"],
        "open_threads": shared["unresolved_threads"],
    }


def compact_relationship_pair(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result = {
        "pair_id": value.get("pair_id"),
        "character_a": value.get("character_a"),
        "character_b": value.get("character_b"),
        "shared": value.get("shared", {}),
        "a_to_b": value.get("a_to_b", {}),
        "b_to_a": value.get("b_to_a", {}),
    }
    return result


def _bounded_score(old_value: Any, new_value: Any, *, major_shift: bool) -> int | None:
    try:
        new_int = max(0, min(100, int(float(new_value))))
    except Exception:
        return None
    try:
        old_int = max(0, min(100, int(float(old_value))))
    except Exception:
        return new_int
    limit = 15 if major_shift else 8
    return max(old_int - limit, min(old_int + limit, new_int))


def _apply_direction_patch(direction: dict[str, Any], patch: dict[str, Any], *, major_shift: bool) -> dict[str, Any]:
    result = deepcopy(direction)
    score_patch = patch.get("scores") if isinstance(patch.get("scores"), dict) else {}
    for field in DIRECTION_SCORE_FIELDS:
        if field in patch:
            score_patch[field] = patch[field]
    result.setdefault("scores", {})
    for field, value in score_patch.items():
        if field not in DIRECTION_SCORE_FIELDS:
            continue
        bounded = _bounded_score(result["scores"].get(field), value, major_shift=major_shift)
        if bounded is not None:
            result["scores"][field] = bounded

    for field in DIRECTION_TEXT_FIELDS:
        if isinstance(patch.get(field), str) and patch[field].strip():
            result[field] = patch[field].strip()

    if patch.get("add_unresolved_grievances"):
        result["unresolved_grievances"] = list(dict.fromkeys([
            *result.get("unresolved_grievances", []),
            *_list(patch.get("add_unresolved_grievances")),
        ]))
    if patch.get("resolve_unresolved_grievances"):
        resolved = set(_list(patch.get("resolve_unresolved_grievances")))
        result["unresolved_grievances"] = [item for item in result.get("unresolved_grievances", []) if item not in resolved]
    if patch.get("add_wrong_beliefs"):
        result["wrong_beliefs"] = list(dict.fromkeys([*result.get("wrong_beliefs", []), *_list(patch.get("add_wrong_beliefs"))]))
    if patch.get("remove_wrong_beliefs"):
        removed = set(_list(patch.get("remove_wrong_beliefs")))
        result["wrong_beliefs"] = [item for item in result.get("wrong_beliefs", []) if item not in removed]
    return result


def apply_relationship_patch(existing: dict[str, Any], patch: dict[str, Any], *, turn_number: int) -> tuple[dict[str, Any], str | None]:
    pair = deepcopy(existing)
    a = str(pair.get("character_a") or "")
    b = str(pair.get("character_b") or "")
    from_id = str(patch.get("from_character_id") or "")
    to_id = str(patch.get("to_character_id") or "")

    direction_key: str | None = None
    if from_id and to_id:
        if (from_id, to_id) == (a, b):
            direction_key = "a_to_b"
        elif (from_id, to_id) == (b, a):
            direction_key = "b_to_a"
        else:
            return pair, "from_character_id/to_character_id do not match pair participants"

    major_shift = bool(patch.get("major_shift"))
    direction_patch = patch.get("direction_patch") if isinstance(patch.get("direction_patch"), dict) else {}
    if direction_key and direction_patch:
        pair[direction_key] = _apply_direction_patch(pair.get(direction_key, {}), direction_patch, major_shift=major_shift)
    elif direction_patch:
        return pair, "direction_patch requires from_character_id and to_character_id"

    for key in ("a_to_b", "b_to_a"):
        if isinstance(patch.get(key), dict):
            pair[key] = _apply_direction_patch(pair.get(key, {}), patch[key], major_shift=major_shift)

    shared_patch = patch.get("shared_patch") if isinstance(patch.get("shared_patch"), dict) else {}
    shared = pair.setdefault("shared", {})
    if isinstance(shared_patch.get("status"), str) and shared_patch["status"].strip():
        shared["status"] = shared_patch["status"].strip()
    if shared_patch.get("add_shared_history"):
        shared["shared_history"] = [*shared.get("shared_history", []), *_list(shared_patch.get("add_shared_history"))]
    if shared_patch.get("add_unresolved_threads"):
        shared["unresolved_threads"] = list(dict.fromkeys([*shared.get("unresolved_threads", []), *_list(shared_patch.get("add_unresolved_threads"))]))
    if shared_patch.get("resolve_unresolved_threads"):
        resolved = set(_list(shared_patch.get("resolve_unresolved_threads")))
        shared["unresolved_threads"] = [item for item in shared.get("unresolved_threads", []) if item not in resolved]
    if "last_major_event" in shared_patch:
        shared["last_major_event"] = shared_patch.get("last_major_event")

    change_entry = {
        "turn": turn_number,
        "entry": patch.get("entry"),
        "change_type": patch.get("change_type"),
        "reason": patch.get("reason"),
        "source_in_scene": patch.get("source_in_scene"),
        "from_character_id": from_id or None,
        "to_character_id": to_id or None,
    }
    shared.setdefault("recent_changes", []).append(change_entry)
    shared["recent_changes"] = shared["recent_changes"][-10:]
    pair.setdefault("history", []).append(change_entry)
    pair["history"] = pair["history"][-30:]

    # Keep legacy mirrors synchronized for old readers.
    pair["type"] = shared.get("type", pair.get("type", "relationship"))
    pair["status"] = shared.get("status", pair.get("status", "отношения меняются"))
    pair["shared_history"] = shared.get("shared_history", [])
    pair["recent_changes"] = shared.get("recent_changes", [])
    pair["open_threads"] = shared.get("unresolved_threads", [])
    pair["scores"] = deepcopy(pair.get("a_to_b", {}).get("scores", {}))
    pair["a_view_of_b"] = {
        "summary": pair.get("a_to_b", {}).get("current_view"),
        "current_assumption": pair.get("a_to_b", {}).get("interpretation_bias"),
    }
    pair["b_view_of_a"] = {
        "summary": pair.get("b_to_a", {}).get("current_view"),
        "current_assumption": pair.get("b_to_a", {}).get("interpretation_bias"),
    }
    return pair, None
