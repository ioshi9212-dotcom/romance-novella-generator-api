from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.id_utils import pair_id


RELATIONSHIP_VERSION = "directed.v1"
DIRECTION_SCORE_FIELDS = (
    "trust",
    "attachment",
    "attraction",
    "resentment",
    "respect",
    "fear",
    "jealousy",
    "dependency",
    "curiosity",
    "protectiveness",
)
SHARED_SCORE_FIELDS = ("tension", "closeness", "conflict_pressure")
DIRECTION_TEXT_FIELDS = (
    "summary",
    "current_assumption",
    "current_need",
    "access_expectation",
    "unresolved_grievance",
)


def _score(value: Any, fallback: int = 0) -> int:
    try:
        return max(0, min(100, int(float(value))))
    except Exception:
        return fallback


def _text(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def _list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    if value is None:
        return []
    return [value]


def _role_kind(role: Any) -> str:
    text = str(role or "").lower()
    if any(word in text for word in ("friend", "best friend", "подруг", "друг")):
        return "friend"
    if any(word in text for word in ("brother", "sister", "mother", "father", "family", "брат", "сестр", "мать", "отец", "семь")):
        return "family"
    if any(word in text for word in ("love", "romance", "boyfriend", "girlfriend", "partner", "crush", "lover", "парень", "девуш", "быв", "влюб")):
        return "romance"
    if any(word in text for word in ("colleague", "coworker", "boss", "manager", "коллег", "началь", "сотруд")):
        return "colleague"
    return "default"


def _direction_score_defaults(role: Any, *, source_is_player: bool) -> dict[str, int]:
    kind = _role_kind(role)
    if kind == "friend":
        return {
            "trust": 58 if source_is_player else 66,
            "attachment": 52 if source_is_player else 68,
            "attraction": 0,
            "resentment": 12 if source_is_player else 18,
            "respect": 48,
            "fear": 0 if source_is_player else 8,
            "jealousy": 2 if source_is_player else 10,
            "dependency": 18 if source_is_player else 32,
            "curiosity": 18 if source_is_player else 28,
            "protectiveness": 30 if source_is_player else 62,
        }
    if kind == "family":
        return {
            "trust": 44,
            "attachment": 66,
            "attraction": 0,
            "resentment": 34 if source_is_player else 26,
            "respect": 38,
            "fear": 6,
            "jealousy": 4,
            "dependency": 42 if source_is_player else 48,
            "curiosity": 10,
            "protectiveness": 58 if source_is_player else 66,
        }
    if kind == "romance":
        return {
            "trust": 36 if source_is_player else 44,
            "attachment": 24 if source_is_player else 64,
            "attraction": 32 if source_is_player else 74,
            "resentment": 10 if source_is_player else 18,
            "respect": 38,
            "fear": 5 if source_is_player else 18,
            "jealousy": 8 if source_is_player else 34,
            "dependency": 10 if source_is_player else 28,
            "curiosity": 42 if source_is_player else 56,
            "protectiveness": 20 if source_is_player else 54,
        }
    if kind == "colleague":
        return {
            "trust": 44,
            "attachment": 10,
            "attraction": 4,
            "resentment": 12,
            "respect": 52,
            "fear": 0,
            "jealousy": 2,
            "dependency": 12,
            "curiosity": 20,
            "protectiveness": 14,
        }
    return {
        "trust": 42,
        "attachment": 18,
        "attraction": 8,
        "resentment": 10,
        "respect": 38,
        "fear": 0,
        "jealousy": 2,
        "dependency": 8,
        "curiosity": 28,
        "protectiveness": 16,
    }


def _view_defaults(
    source_id: str,
    target_id: str,
    source_card: dict[str, Any],
    target_card: dict[str, Any],
    *,
    source_is_player: bool,
) -> dict[str, str]:
    behavior = source_card.get("behavior") if isinstance(source_card.get("behavior"), dict) else {}
    inner = source_card.get("inner_logic") if isinstance(source_card.get("inner_logic"), dict) else {}
    target_name = str(target_card.get("display_name") or target_card.get("name") or target_id)
    if source_is_player:
        return {
            "summary": f"Стартовая позиция героини по отношению к {target_name}; чувства не должны усиливаться без явного ввода игрока.",
            "current_assumption": "опирается на общую историю и может быть неполной",
            "current_need": "сохранить право самой определять близость, доверие и дистанцию",
            "access_expectation": "не считать молчание героини согласием на вмешательство или прикосновение",
            "unresolved_grievance": "конкретная старая претензия должна следовать из общей истории, а не выдумываться сценой",
        }
    return {
        "summary": _text(
            source_card.get("relationship_stance"),
            f"{source_card.get('display_name') or source_card.get('name') or source_id} воспринимает {target_name} через свою цель, страх и историю близости.",
        ),
        "current_assumption": _text(inner.get("blind_spot"), "может неверно объяснять поведение другого человека"),
        "current_need": _text(inner.get("core_need"), _text(source_card.get("goal"), "добиться ясности или сохранить связь")),
        "access_expectation": _text(
            behavior.get("closeness_style"),
            "имеет собственное представление о допустимой близости и не всегда сверяет его с другим человеком",
        ),
        "unresolved_grievance": _text(
            behavior.get("inconvenient_pattern"),
            "незакрытая претензия проявляется через привычный неудобный паттерн",
        ),
    }


def _direction_block(
    raw: Any,
    legacy_view: Any,
    legacy_scores: dict[str, Any],
    defaults: dict[str, int],
    text_defaults: dict[str, str],
    source_id: str,
    target_id: str,
) -> dict[str, Any]:
    source = deepcopy(raw) if isinstance(raw, dict) else {}
    view = source.get("view") if isinstance(source.get("view"), dict) else {}
    if isinstance(legacy_view, dict):
        view = {**legacy_view, **view}
    source_scores = source.get("scores") if isinstance(source.get("scores"), dict) else {}
    scores: dict[str, int] = {}
    for key in DIRECTION_SCORE_FIELDS:
        value = source_scores.get(key)
        if value is None and key == "attraction":
            value = source_scores.get("romantic_interest", legacy_scores.get("romantic_interest"))
        if value is None and key in legacy_scores:
            value = legacy_scores.get(key)
        scores[key] = _score(value, defaults[key])

    result = {
        **source,
        "source_character_id": source_id,
        "target_character_id": target_id,
        "scores": scores,
        "history": [item for item in _list(source.get("history")) if isinstance(item, dict)][-12:],
    }
    for key in DIRECTION_TEXT_FIELDS:
        result[key] = _text(source.get(key) or view.get(key), text_defaults[key])
    result["view"] = {key: result[key] for key in DIRECTION_TEXT_FIELDS}
    return result


def normalize_relationship_entry(
    entry: Any,
    characters: dict[str, Any] | None = None,
    protagonist_id: str | None = None,
    *,
    fallback_a: str | None = None,
    fallback_b: str | None = None,
) -> dict[str, Any]:
    source = deepcopy(entry) if isinstance(entry, dict) else {}
    characters = characters if isinstance(characters, dict) else {}
    character_a = str(source.get("character_a") or source.get("a") or source.get("from") or fallback_a or "")
    character_b = str(source.get("character_b") or source.get("b") or source.get("to") or fallback_b or "")
    if not character_a or not character_b or character_a == character_b:
        return source

    pid = pair_id(character_a, character_b)
    card_a = characters.get(character_a) if isinstance(characters.get(character_a), dict) else {}
    card_b = characters.get(character_b) if isinstance(characters.get(character_b), dict) else {}
    role_a = card_a.get("role")
    role_b = card_b.get("role")
    legacy_scores = source.get("scores") if isinstance(source.get("scores"), dict) else {}

    shared_source = source.get("shared") if isinstance(source.get("shared"), dict) else {}
    shared_scores_source = shared_source.get("scores") if isinstance(shared_source.get("scores"), dict) else {}
    tension = _score(shared_scores_source.get("tension", legacy_scores.get("tension")), 25)
    closeness_fallback = _score(legacy_scores.get("attachment"), 20)
    shared = {
        **shared_source,
        "status": _text(shared_source.get("status") or source.get("status"), "отношения развиваются через поступки и незакрытые ожидания"),
        "scores": {
            "tension": tension,
            "closeness": _score(shared_scores_source.get("closeness"), closeness_fallback),
            "conflict_pressure": _score(shared_scores_source.get("conflict_pressure"), tension),
        },
        "shared_history": _list(shared_source.get("shared_history") or source.get("shared_history")),
        "recent_changes": _list(shared_source.get("recent_changes") or source.get("recent_changes"))[-10:],
        "open_threads": _list(shared_source.get("open_threads") or source.get("open_threads")),
    }

    a_to_b = _direction_block(
        source.get("a_to_b"),
        source.get("a_view_of_b"),
        legacy_scores,
        _direction_score_defaults(role_b, source_is_player=character_a == protagonist_id),
        _view_defaults(character_a, character_b, card_a, card_b, source_is_player=character_a == protagonist_id),
        character_a,
        character_b,
    )
    b_to_a = _direction_block(
        source.get("b_to_a"),
        source.get("b_view_of_a"),
        legacy_scores,
        _direction_score_defaults(role_a or role_b, source_is_player=character_b == protagonist_id),
        _view_defaults(character_b, character_a, card_b, card_a, source_is_player=character_b == protagonist_id),
        character_b,
        character_a,
    )

    compatibility_scores = {
        "trust": round((a_to_b["scores"]["trust"] + b_to_a["scores"]["trust"]) / 2),
        "tension": shared["scores"]["tension"],
        "attachment": round((a_to_b["scores"]["attachment"] + b_to_a["scores"]["attachment"]) / 2),
        "respect": round((a_to_b["scores"]["respect"] + b_to_a["scores"]["respect"]) / 2),
        "fear": round((a_to_b["scores"]["fear"] + b_to_a["scores"]["fear"]) / 2),
        "curiosity": round((a_to_b["scores"]["curiosity"] + b_to_a["scores"]["curiosity"]) / 2),
        "romantic_interest": round((a_to_b["scores"]["attraction"] + b_to_a["scores"]["attraction"]) / 2),
    }

    result = {
        **source,
        "relationship_version": RELATIONSHIP_VERSION,
        "pair_id": pid,
        "character_a": character_a,
        "character_b": character_b,
        "type": _text(source.get("type"), "relationship"),
        "status": shared["status"],
        "shared": shared,
        "a_to_b": a_to_b,
        "b_to_a": b_to_a,
        "scores": compatibility_scores,
        "a_view_of_b": dict(a_to_b["view"]),
        "b_view_of_a": dict(b_to_a["view"]),
        "shared_history": list(shared["shared_history"]),
        "recent_changes": list(shared["recent_changes"]),
        "open_threads": list(shared["open_threads"]),
        "history": [item for item in _list(source.get("history")) if isinstance(item, dict)][-20:],
    }
    return result


def build_starting_relationship(
    characters: dict[str, Any],
    protagonist_id: str,
    other_id: str,
    existing: Any = None,
) -> dict[str, Any]:
    source = deepcopy(existing) if isinstance(existing, dict) else {}
    source.setdefault("character_a", protagonist_id)
    source.setdefault("character_b", other_id)
    source.setdefault("pair_id", pair_id(protagonist_id, other_id))
    source.setdefault("type", "starting_relationship")
    source.setdefault("status", "отношения существуют до начала истории и не обязаны быть взаимными или одинаковыми")
    source.setdefault("shared_history", [])
    source.setdefault("recent_changes", [])
    source.setdefault("open_threads", [])
    return normalize_relationship_entry(source, characters, protagonist_id)


def direction_key(entry: dict[str, Any], source_id: str, target_id: str) -> str | None:
    character_a = str(entry.get("character_a") or "")
    character_b = str(entry.get("character_b") or "")
    if source_id == character_a and target_id == character_b:
        return "a_to_b"
    if source_id == character_b and target_id == character_a:
        return "b_to_a"
    return None


def _bounded_score(old_value: Any, new_value: Any, *, major_shift: bool = False) -> int | None:
    try:
        new_int = _score(new_value)
    except Exception:
        return None
    old_int = _score(old_value, new_int)
    max_delta = 15 if major_shift else 8
    if new_int > old_int + max_delta:
        return old_int + max_delta
    if new_int < old_int - max_delta:
        return old_int - max_delta
    return new_int


def apply_relationship_patch(
    existing: Any,
    patch: dict[str, Any],
    *,
    characters: dict[str, Any] | None,
    protagonist_id: str | None,
    turn_number: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    relationship = normalize_relationship_entry(existing, characters, protagonist_id)
    if not relationship:
        return relationship, {}

    scope = str(patch.get("scope") or "").strip().lower()
    source_id = str(patch.get("source_character_id") or "").strip()
    target_id = str(patch.get("target_character_id") or "").strip()
    if not scope:
        scope = "directed" if source_id and target_id else "legacy_symmetric"

    major_shift = bool(patch.get("major_shift"))
    changed: dict[str, Any] = {}
    change_entry = {
        "turn": turn_number,
        "scope": scope,
        "source_character_id": source_id or None,
        "target_character_id": target_id or None,
        "entry": patch.get("entry"),
        "change_type": patch.get("change_type"),
        "reason": patch.get("reason"),
        "source_in_scene": patch.get("source_in_scene"),
        "trigger_source": patch.get("trigger_source"),
    }

    if scope == "shared":
        shared = relationship["shared"]
        score_patch = patch.get("scores") if isinstance(patch.get("scores"), dict) else {}
        for field in SHARED_SCORE_FIELDS:
            value = score_patch.get(field, patch.get(field))
            if value is None:
                continue
            bounded = _bounded_score(shared["scores"].get(field), value, major_shift=major_shift)
            if bounded is not None and bounded != shared["scores"].get(field):
                shared["scores"][field] = bounded
                changed[field] = bounded
        if isinstance(patch.get("status"), str) and patch["status"].strip():
            shared["status"] = patch["status"].strip()
            changed["status"] = shared["status"]
    else:
        if scope == "legacy_symmetric":
            direction_keys = ["a_to_b", "b_to_a"]
        else:
            key = direction_key(relationship, source_id, target_id)
            if not key:
                return relationship, {}
            direction_keys = [key]

        score_patch = patch.get("scores") if isinstance(patch.get("scores"), dict) else {}
        for key in direction_keys:
            direction = relationship[key]
            local_changes: dict[str, Any] = {}
            for field in DIRECTION_SCORE_FIELDS:
                value = score_patch.get(field, patch.get(field))
                if value is None and field == "attraction":
                    value = score_patch.get("romantic_interest", patch.get("romantic_interest"))
                if value is None:
                    continue
                bounded = _bounded_score(direction["scores"].get(field), value, major_shift=major_shift)
                if bounded is not None and bounded != direction["scores"].get(field):
                    direction["scores"][field] = bounded
                    local_changes[field] = bounded
            view_patch = patch.get("view") if isinstance(patch.get("view"), dict) else {}
            for field in DIRECTION_TEXT_FIELDS:
                value = patch.get(field, view_patch.get(field))
                if isinstance(value, str) and value.strip() and value.strip() != direction.get(field):
                    direction[field] = value.strip()
                    direction["view"][field] = value.strip()
                    local_changes[field] = value.strip()
            if local_changes:
                direction["history"] = [*direction.get("history", []), {**change_entry, "changes": local_changes}][-12:]
                changed[key] = local_changes

    open_threads = patch.get("open_threads") or patch.get("add_open_threads")
    if isinstance(open_threads, list):
        for item in open_threads:
            if item not in relationship["shared"]["open_threads"]:
                relationship["shared"]["open_threads"].append(item)
                changed.setdefault("shared", {})["open_threads"] = list(relationship["shared"]["open_threads"])

    if not changed:
        return relationship, {}

    relationship["history"] = [*relationship.get("history", []), {**change_entry, "changes": changed}][-20:]
    relationship["shared"]["recent_changes"] = [*relationship["shared"].get("recent_changes", []), change_entry][-10:]
    relationship["recent_changes"] = list(relationship["shared"]["recent_changes"])
    relationship["open_threads"] = list(relationship["shared"]["open_threads"])
    relationship["shared_history"] = list(relationship["shared"]["shared_history"])
    relationship["status"] = relationship["shared"]["status"]
    return normalize_relationship_entry(relationship, characters, protagonist_id), changed


def direction_toward(entry: Any, target_id: str, characters: dict[str, Any] | None = None, protagonist_id: str | None = None) -> dict[str, Any]:
    relationship = normalize_relationship_entry(entry, characters, protagonist_id)
    if relationship.get("character_b") == target_id:
        return relationship.get("a_to_b", {})
    if relationship.get("character_a") == target_id:
        return relationship.get("b_to_a", {})
    return {}
