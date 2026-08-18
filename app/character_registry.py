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


def character_registry_entry(character: dict[str, Any]) -> dict[str, Any]:
    card = character.get("card", {})
    identity = card.get("identity", {}) if isinstance(card, dict) else {}
    return {
        "character_id": character.get("character_id"),
        "name": character_display_name(card),
        "origin": card.get("origin"),
        "card_level": card.get("card_level"),
        "story_status": card.get("story_status"),
        "role": str(card.get("card_hint") or identity.get("role") or "").strip(),
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
        name = character_display_name(character.get("card", {}))
        normalized = normalize_character_name(name)
        if normalized:
            result[normalized] = str(character.get("character_id", ""))
    return result
