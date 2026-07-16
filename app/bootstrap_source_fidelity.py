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

_GENERIC_PLAYER_VALUES = {
    "оказаться бессильным, ненужным или использованным",
    "слишком быстро объясняет чужое поведение через собственный страх",
    "хочет близости, но защищается способом, который эту близость портит",
    "не отпускает важную для себя тему и защищает собственную версию происходящего",
    "помогает так, как умеет сам, а не обязательно так, как удобно героине",
    "проверяет близость действиями и реакцией на отказ",
    "физическая дистанция зависит от привычки, статуса отношений и текущего напряжения",
    "теряет часть самоконтроля и возвращается к привычной защите",
    "может спорить, закрыться, обидеться или сделать неверный вывод",
    "понимание ошибки не превращается в мгновенно новое поведение",
    "в критический момент выбирает знакомый способ защиты, даже если он уже вредил отношениям",
    "узнаваемая речь с собственным темпом, словарём и способом уходить от неудобного",
    "манера речи заметно меняется: темп, громкость или резкость выдают напряжение",
    "имеет собственные дела и сроки вне героини",
    "решает личную проблему, которую не обязан сразу раскрывать",
    "человек, место или дело из отдельной жизни",
}

_KNOWN_ROLE_EXPECTATIONS = (
    {
        "key": "older_brother",
        "source_markers": ("старший брат", "старшего брата"),
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


def _field_text(card: dict[str, Any], block: str, field: str) -> str:
    nested = card.get(block) if isinstance(card.get(block), dict) else {}
    return _normalise(nested.get(field))


def _generic_player_template_matches(card: dict[str, Any]) -> int:
    values = [
        _field_text(card, "inner_logic", "main_fear"),
        _field_text(card, "inner_logic", "blind_spot"),
        _field_text(card, "inner_logic", "contradiction"),
        _field_text(card, "behavior", "conflict_style"),
        _field_text(card, "behavior", "care_style"),
        _field_text(card, "behavior", "closeness_style"),
        _field_text(card, "behavior", "touch_style"),
        _field_text(card, "behavior", "stress_response"),
        _field_text(card, "behavior", "rejection_response"),
        _field_text(card, "behavior", "change_inertia"),
        _field_text(card, "behavior", "inconvenient_pattern"),
        _field_text(card, "speech_profile", "baseline"),
        _field_text(card, "speech_profile", "under_pressure"),
        _field_text(card, "life_outside_player", "current_obligation"),
        _field_text(card, "life_outside_player", "private_problem"),
        _field_text(card, "life_outside_player", "person_or_place_that_matters"),
    ]
    return sum(value in _GENERIC_PLAYER_VALUES for value in values)


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

    past_short = _normalise(card.get("past_short"))
    if "уже жил(а) с обязанностью" in past_short and "текущая проблема" in past_short:
        errors.append(
            "source_fidelity.protagonist.past_short: generic repair prose replaced the user's concrete biography."
        )

    generic_matches = _generic_player_template_matches(card)
    if generic_matches >= 4:
        errors.append(
            "source_fidelity.protagonist.profile: generic fallback template replaced the user's concrete character details "
            f"({generic_matches} template fields detected)."
        )

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
    if expected_hidden_count and len(hidden_cards) < expected_hidden_count:
        errors.append(
            "source_fidelity.characters.hidden_count: user explicitly described "
            f"{expected_hidden_count} future significant characters, but bootstrap contains {len(hidden_cards)} hidden_core cards."
        )


def _validate_story_plan(data: dict[str, Any], errors: list[str]) -> None:
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
    """Reject a structurally valid bootstrap that lost concrete user input.

    The normalizer and repair layer may invent safe defaults for small omissions.
    This guard prevents those defaults from masking missing cast, biography,
    appearance, age, or a generic story plan when the source request was explicit.
    """

    if not isinstance(data, dict):
        return ["source_fidelity.root: bootstrap must be an object."]

    source = _flatten_text(user_request or {})
    errors: list[str] = []
    _validate_protagonist(data, source, errors)
    _validate_cast(data, source, errors)
    _validate_story_plan(data, errors)
    return errors
