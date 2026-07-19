from __future__ import annotations

import re
from typing import Any


_MISSING_TEXT = {
    "",
    "—",
    "-",
    "не указано",
    "не задано",
    "unknown",
    "none",
    "null",
}

_KNOWN_ROLE_EXPECTATIONS = (
    {
        "key": "older_brother",
        "source_markers": ("старший брат", "старшего брата", "старшим брат"),
        "card_markers": ("brother", "старший брат", "брат героини", "брат"),
        "label": "старший брат",
    },
    {
        "key": "best_friend",
        "source_markers": ("лучшая подруга", "лучшей подруг"),
        "card_markers": ("best friend", "лучшая подруга", "подруга героини", "подруга"),
        "label": "лучшая подруга",
    },
    {
        "key": "childhood_friend",
        "source_markers": ("друг детства", "друга детства"),
        "card_markers": ("childhood friend", "друг детства"),
        "label": "друг детства",
    },
    {
        "key": "friends_mother",
        "source_markers": ("мать друга детства", "мать друга"),
        "card_markers": ("friend's mother", "mother of", "мать друга детства", "мать друга"),
        "label": "мать друга детства",
    },
)

_HIDDEN_SOURCE_MARKERS = (
    "красноволосый мужчина",
    "темноволосый мужчина",
    "девушка из их компании",
)


def _normalise(value: Any) -> str:
    return " ".join(str(value or "").lower().replace("ё", "е").split())


def _flatten_text(value: Any) -> str:
    parts: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, str):
            if item.strip():
                parts.append(item)
        elif isinstance(item, dict):
            for nested in item.values():
                visit(nested)
        elif isinstance(item, (list, tuple, set)):
            for nested in item:
                visit(nested)
        elif isinstance(item, (int, float)) and not isinstance(item, bool):
            parts.append(str(item))

    visit(value)
    return _normalise("\n".join(parts))


def _card_text(card: Any) -> str:
    return _flatten_text(card if isinstance(card, dict) else {})


def _is_missing(value: Any) -> bool:
    return _normalise(value) in _MISSING_TEXT


def _extract_requested_age(source: str) -> int | None:
    patterns = (
        r"(?:девушка|героин(?:я|е|и|ю))[\s,:—-]{0,24}(\d{1,2})\s*(?:год|года|лет)",
        r"возраст[\s:—-]{0,12}(\d{1,2})\s*(?:год|года|лет)?",
    )
    for pattern in patterns:
        match = re.search(pattern, source)
        if match:
            return int(match.group(1))
    return None


def _extract_card_age(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    match = re.search(r"\d{1,3}", str(value or ""))
    return int(match.group(0)) if match else None


def _source_detail_score(source: str) -> int:
    score = 1 if _extract_requested_age(source) is not None else 0
    appearance_groups = (
        ("невысок",),
        ("миниатюр", "женственн"),
        ("кудряв", "русые волос"),
        ("зелены", "янтар"),
        ("веснуш",),
        ("нежн", "удобн"),
    )
    score += sum(any(marker in source for marker in group) for group in appearance_groups)
    score += sum(
        any(marker in source for marker in expectation["source_markers"])
        for expectation in _KNOWN_ROLE_EXPECTATIONS
    )
    score += sum(marker in source for marker in _HIDDEN_SOURCE_MARKERS)
    if any(marker in source for marker in ("родител", "бабуш", "гиперзабот", "не умеет отказывать")):
        score += 2
    return score


def _validate_protagonist(
    data: dict[str, Any],
    source: str,
    errors: list[str],
) -> None:
    protagonist = data.get("protagonist") if isinstance(data.get("protagonist"), dict) else {}
    characters = data.get("characters") if isinstance(data.get("characters"), dict) else {}
    current_state = data.get("current_state") if isinstance(data.get("current_state"), dict) else {}
    protagonist_id = str(
        protagonist.get("id")
        or current_state.get("player_character_id")
        or next(iter(characters), "")
    )
    card = characters.get(protagonist_id) if isinstance(characters.get(protagonist_id), dict) else protagonist
    card = card if isinstance(card, dict) else {}

    requested_age = _extract_requested_age(source)
    if requested_age is not None:
        actual_age = _extract_card_age(card.get("age"))
        if actual_age != requested_age:
            errors.append(
                f"source_fidelity.protagonist.age: user specified {requested_age}, but bootstrap has {card.get('age')!r}."
            )

    # Generated biography and role templates are valid for fields the player
    # omitted. Only source facts that can be identified with high confidence are
    # checked here; generic prose alone is never treated as data loss.

    appearance = card.get("appearance") if isinstance(card.get("appearance"), dict) else {}
    appearance_checks = (
        (("невысок",), "height", "невысокий рост"),
        (("миниатюр", "женственн"), "build", "миниатюрное телосложение"),
        (("кудряв", "русые волос"), "hair", "кудрявые русые волосы"),
        (("зелены", "янтар"), "eyes", "зелёно-янтарные глаза"),
        (("веснуш",), "face", "веснушки"),
        (("нежн", "удобн"), "style", "нежный удобный стиль одежды"),
    )
    for markers, field, label in appearance_checks:
        if any(marker in source for marker in markers) and _is_missing(appearance.get(field)):
            errors.append(
                f"source_fidelity.protagonist.appearance.{field}: user specified {label}, but the field is missing."
            )


def _validate_cast(data: dict[str, Any], source: str, errors: list[str]) -> None:
    characters = data.get("characters") if isinstance(data.get("characters"), dict) else {}
    visible_cards = [
        card
        for card in characters.values()
        if isinstance(card, dict) and card.get("cast_status") in {"known_core", "known_support"}
    ]
    hidden_cards = [
        card
        for card in characters.values()
        if isinstance(card, dict) and card.get("cast_status") == "hidden_core"
    ]
    future_locks = data.get("future_locks") if isinstance(data.get("future_locks"), dict) else {}
    hidden_seeds = [
        seed
        for seed in (future_locks.get("hidden_character_seeds") or [])
        if isinstance(seed, dict)
    ]

    expected_known = [
        expectation
        for expectation in _KNOWN_ROLE_EXPECTATIONS
        if any(marker in source for marker in expectation["source_markers"])
    ]
    if expected_known and len(visible_cards) < len(expected_known):
        errors.append(
            "source_fidelity.characters.visible_count: user explicitly described "
            f"{len(expected_known)} known starting characters, but bootstrap contains {len(visible_cards)}."
        )

    visible_texts = [_card_text(card) for card in visible_cards]
    for expectation in expected_known:
        if not any(
            any(marker in card_text for marker in expectation["card_markers"])
            for card_text in visible_texts
        ):
            errors.append(
                "source_fidelity.characters.missing_known: add a complete known_core/known_support card for "
                f"{expectation['label']}."
            )

    expected_hidden_count = sum(marker in source for marker in _HIDDEN_SOURCE_MARKERS)
    hidden_future_count = len(hidden_cards) + len(hidden_seeds)
    if expected_hidden_count and hidden_future_count < expected_hidden_count:
        errors.append(
            "source_fidelity.characters.hidden_count: user explicitly described "
            f"{expected_hidden_count} future significant characters, but bootstrap contains {hidden_future_count} seeds/legacy hidden cards."
        )


def _validate_story_plan(data: dict[str, Any], errors: list[str], *, strict_source: bool) -> None:
    if not strict_source:
        return
    story_plan = data.get("story_plan") if isinstance(data.get("story_plan"), dict) else {}
    acts = story_plan.get("act_structure") if isinstance(story_plan.get("act_structure"), list) else []
    generic_values = {"старт", "развитие", "выбор", "развить конфликт"}
    generic_hits = 0
    must_happen_values: list[str] = []
    for act in acts:
        if not isinstance(act, dict):
            continue
        goal = _normalise(act.get("goal"))
        must_happen = _normalise(act.get("must_happen"))
        if goal in generic_values:
            generic_hits += 1
        if must_happen in generic_values:
            generic_hits += 1
        if must_happen:
            must_happen_values.append(must_happen)
    if generic_hits:
        errors.append(
            "source_fidelity.story_plan.act_structure: generic act placeholders were used instead of a story-specific open plan."
        )
    if len(must_happen_values) >= 3 and len(set(must_happen_values)) == 1:
        errors.append(
            "source_fidelity.story_plan.act_structure: every act repeats the same must_happen value."
        )


def validate_bootstrap_source_fidelity(
    data: dict[str, Any],
    user_request: dict[str, Any] | None,
) -> list[str]:
    """Report high-confidence signs that a bootstrap lost concrete user input.

    These heuristics are diagnostics, not a preview gate. They catch explicit
    age/appearance facts, named starting roles and generic story-plan fallbacks;
    they must not reject details that were absent and invented later.
    """

    if not isinstance(data, dict):
        return ["source_fidelity.root: bootstrap must be an object."]

    source = _flatten_text(user_request or {})
    if not source:
        return []
    strict_source = len(source) >= 1200 or _source_detail_score(source) >= 3
    errors: list[str] = []
    _validate_protagonist(data, source, errors)
    _validate_cast(data, source, errors)
    _validate_story_plan(data, errors, strict_source=strict_source)
    return errors
