from __future__ import annotations

from typing import Any

from app.id_utils import pair_id
from app.relationship_state import build_starting_relationship, normalize_relationship_entry


VISIBLE_KNOWN_STATUSES = {"known_core", "known_support"}


def prepare_directed_relationships(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize every pair and create missing starting pairs for known cast."""
    if not isinstance(data, dict):
        return data

    characters = data.get("characters") if isinstance(data.get("characters"), dict) else {}
    protagonist = data.get("protagonist") if isinstance(data.get("protagonist"), dict) else {}
    current_state = data.get("current_state") if isinstance(data.get("current_state"), dict) else {}
    protagonist_id = str(
        protagonist.get("id")
        or current_state.get("player_character_id")
        or next((cid for cid, card in characters.items() if isinstance(card, dict) and card.get("cast_status") == "player"), "pc_01")
    )

    source = data.get("relationships") if isinstance(data.get("relationships"), dict) else {}
    normalized: dict[str, Any] = {}
    for key, entry in source.items():
        if not isinstance(entry, dict):
            continue
        fallback_a = entry.get("character_a") or entry.get("from") or entry.get("a") or protagonist_id
        fallback_b = entry.get("character_b") or entry.get("to") or entry.get("b")
        if not fallback_b and "__" in str(key):
            left, right = str(key).split("__", 1)
            fallback_a = fallback_a or left
            fallback_b = right if right != fallback_a else left
        relation = normalize_relationship_entry(
            entry,
            characters,
            protagonist_id,
            fallback_a=str(fallback_a) if fallback_a else None,
            fallback_b=str(fallback_b) if fallback_b else None,
        )
        relation_id = relation.get("pair_id")
        if relation_id:
            normalized[str(relation_id)] = relation

    for character_id, card in characters.items():
        if character_id == protagonist_id or not isinstance(card, dict):
            continue
        if card.get("cast_status") not in VISIBLE_KNOWN_STATUSES:
            continue
        relationship_id = pair_id(protagonist_id, str(character_id))
        normalized[relationship_id] = build_starting_relationship(
            characters,
            protagonist_id,
            str(character_id),
            normalized.get(relationship_id),
        )

    data["relationships"] = normalized
    return data
