from __future__ import annotations

from copy import deepcopy
from typing import Any


def normalize_character_name(value: str) -> str:
    return " ".join(value.casefold().replace("ё", "е").split())


def character_display_name(card: dict[str, Any]) -> str:
    identity = card.get("identity", {}) if isinstance(card, dict) else {}
    for key in ("full_name", "name"):
        value = identity.get(key)
        if value:
            return " ".join(str(value).split())
    given = " ".join(str(identity.get("given_name", "")).split())
    family = " ".join(str(identity.get("family_name", "")).split())
    return " ".join(part for part in (given, family) if part)


def character_name_aliases(card: dict[str, Any]) -> set[str]:
    identity = card.get("identity", {}) if isinstance(card, dict) else {}
    values: set[str] = set()
    display = character_display_name(card)
    if display:
        values.add(display)
        values.add(display.split()[0])
    for key in ("name", "full_name", "given_name"):
        value = " ".join(str(identity.get(key, "")).split())
        if value:
            values.add(value)
    return {normalize_character_name(value) for value in values if value}


def _short_role(card: dict[str, Any]) -> str:
    identity = card.get("identity", {}) if isinstance(card, dict) else {}
    raw = str(card.get("card_hint") or identity.get("role") or "").strip()
    if not raw:
        return ""
    first_line = raw.splitlines()[0].strip()
    sentence_end = first_line.find(".")
    if sentence_end >= 0:
        first_line = first_line[: sentence_end + 1]
    return first_line[:220].rstrip()


def character_registry_entry(character: dict[str, Any]) -> dict[str, Any]:
    card = character.get("card", {})
    current_state = character.get("current_state", {})
    familiarity = current_state.get("pov_familiarity")
    return {
        "character_id": character.get("character_id"),
        "name": character_display_name(card),
        "origin": card.get("origin"),
        "card_level": card.get("card_level"),
        "story_status": card.get("story_status"),
        "role": _short_role(card),
        "pov_familiarity": deepcopy(familiarity) if isinstance(familiarity, dict) else None,
    }


def build_character_registry(characters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for character in characters:
        card = character.get("card", {})
        origin = card.get("origin")
        level = card.get("card_level")
        if origin == "player" or level in {"recurring", "important", "player_defined"}:
            result.append(character_registry_entry(character))
    return deepcopy(result)


def reserved_character_names(characters: list[dict[str, Any]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for character in characters:
        character_id = str(character.get("character_id", ""))
        for alias in character_name_aliases(character.get("card", {})):
            if alias:
                result[alias] = character_id
    return result
