from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.id_utils import pair_id
from app.relationship_state import apply_relationship_patch, build_starting_relationship, normalize_relationship_entry
from app.storage import JsonStorage


def _scene_character_ids(bundle: dict[str, Any], scene_response: dict[str, Any]) -> set[str]:
    current_state = bundle.get("current_state") if isinstance(bundle.get("current_state"), dict) else {}
    result = {
        str(item)
        for item in (current_state.get("active_character_ids") or [])
        if str(item)
    }
    player_id = current_state.get("player_character_id")
    if player_id:
        result.add(str(player_id))
    for witness in scene_response.get("witnesses") or []:
        if isinstance(witness, str) and witness:
            result.add(witness)
        elif isinstance(witness, dict):
            value = witness.get("character_id") or witness.get("id")
            if value:
                result.add(str(value))
    return result


def _pair_participants(entry: dict[str, Any], pair_id_value: str) -> tuple[str | None, str | None]:
    character_a = entry.get("character_a")
    character_b = entry.get("character_b")
    if character_a and character_b:
        return str(character_a), str(character_b)
    if "__" in pair_id_value:
        left, right = pair_id_value.split("__", 1)
        return left or None, right or None
    return None, None


def _player_input_evidence_is_valid(scene_response: dict[str, Any], patch: dict[str, Any]) -> bool:
    exact_input = str(scene_response.get("player_input") or "").strip()
    evidence = str(patch.get("player_input_evidence") or "").strip()
    if not exact_input or not evidence:
        return False
    return evidence in exact_input or exact_input in evidence


def _new_relationship_for_pair(
    characters: dict[str, Any],
    player_id: str,
    left: str,
    right: str,
) -> dict[str, Any]:
    if player_id in {left, right}:
        other_id = right if left == player_id else left
        return build_starting_relationship(characters, player_id, other_id)
    return normalize_relationship_entry(
        {
            "pair_id": pair_id(left, right),
            "character_a": left,
            "character_b": right,
            "type": "runtime_relationship",
            "status": "отношение возникло в сцене и развивается независимо с каждой стороны",
        },
        characters,
        player_id,
    )


def apply_directed_relationship_patches(
    storage: JsonStorage,
    session_id: str,
    scene_response: dict[str, Any],
    bundle: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    updates = scene_response.get("proposed_updates") if isinstance(scene_response.get("proposed_updates"), dict) else {}
    patches = updates.get("relationship_patches") if isinstance(updates.get("relationship_patches"), list) else []
    if not patches:
        return result

    current_state = bundle.get("current_state") if isinstance(bundle.get("current_state"), dict) else {}
    player_id = str(current_state.get("player_character_id") or "pc_01")
    turn_number = int(current_state.get("turn_number", 0) or 0) + 1
    characters = bundle.get("characters") if isinstance(bundle.get("characters"), dict) else {}
    original_relationships = bundle.get("relationships") if isinstance(bundle.get("relationships"), dict) else {}
    scene_ids = _scene_character_ids(bundle, scene_response)

    applied = result.setdefault("applied", {})
    rejected = result.setdefault("rejected", [])
    applied.setdefault("relationships", [])

    working_relationships: dict[str, dict[str, Any]] = {
        str(pid): normalize_relationship_entry(entry, characters, player_id)
        for pid, entry in original_relationships.items()
        if isinstance(entry, dict)
    }
    touched_pair_ids: set[str] = set()
    directed_applied: list[dict[str, Any]] = []

    for raw_patch in patches:
        if not isinstance(raw_patch, dict):
            rejected.append({"target": "relationships", "reason": "patch must be an object", "severity": "error"})
            continue
        patch = deepcopy(raw_patch)
        pair_id_value = str(patch.get("pair_id") or "").strip()
        if not pair_id_value:
            rejected.append({"target": "relationships", "reason": "missing pair_id", "severity": "error"})
            continue
        if not patch.get("source_in_scene") or not patch.get("reason"):
            rejected.append({
                "target": f"relationships.{pair_id_value}",
                "reason": "relationship patch requires reason and source_in_scene",
                "severity": "error",
            })
            continue

        existing = working_relationships.get(pair_id_value)
        if not isinstance(existing, dict):
            if "__" not in pair_id_value:
                rejected.append({"target": f"relationships.{pair_id_value}", "reason": "invalid pair_id", "severity": "error"})
                continue
            left, right = pair_id_value.split("__", 1)
            if left not in characters or right not in characters:
                rejected.append({"target": f"relationships.{pair_id_value}", "reason": "unknown relationship participants", "severity": "error"})
                continue
            existing = _new_relationship_for_pair(characters, player_id, left, right)

        existing = normalize_relationship_entry(existing, characters, player_id)
        character_a, character_b = _pair_participants(existing, pair_id_value)
        if not character_a or not character_b:
            rejected.append({"target": f"relationships.{pair_id_value}", "reason": "relationship participants are missing", "severity": "error"})
            continue

        source_id = str(patch.get("source_character_id") or "").strip()
        target_id = str(patch.get("target_character_id") or "").strip()
        scope = str(patch.get("scope") or "").strip().lower()

        if not scope and not source_id and not target_id:
            if player_id in {character_a, character_b}:
                other_id = character_b if character_a == player_id else character_a
                patch["scope"] = "directed"
                patch["source_character_id"] = other_id
                patch["target_character_id"] = player_id
                source_id, target_id, scope = other_id, player_id, "directed"
            else:
                patch["scope"] = "legacy_symmetric"
                scope = "legacy_symmetric"

        if scope == "shared":
            if character_a not in scene_ids or character_b not in scene_ids:
                rejected.append({
                    "target": f"relationships.{pair_id_value}",
                    "reason": "shared relationship change requires both people to be involved in the played scene",
                    "severity": "error",
                })
                continue
        elif scope == "directed" or source_id or target_id:
            if not source_id or not target_id or {source_id, target_id} != {character_a, character_b}:
                rejected.append({
                    "target": f"relationships.{pair_id_value}",
                    "reason": "directed relationship patch must identify both pair participants",
                    "severity": "error",
                })
                continue
            if source_id not in scene_ids or target_id not in scene_ids:
                rejected.append({
                    "target": f"relationships.{pair_id_value}",
                    "reason": "directed relationship change requires both people to be involved in the played scene",
                    "severity": "error",
                })
                continue
            if source_id == player_id and not _player_input_evidence_is_valid(scene_response, patch):
                rejected.append({
                    "target": f"relationships.{pair_id_value}",
                    "reason": "player-side relationship change requires exact player_input_evidence; do not invent the heroine's feelings",
                    "severity": "error",
                })
                continue

        updated, changed = apply_relationship_patch(
            existing,
            patch,
            characters=characters,
            protagonist_id=player_id,
            turn_number=turn_number,
        )
        if not changed:
            continue

        canonical_pair_id = str(updated.get("pair_id") or pair_id(character_a, character_b))
        working_relationships[canonical_pair_id] = updated
        touched_pair_ids.add(canonical_pair_id)
        directed_applied.append({
            "pair_id": canonical_pair_id,
            "operation": "patch_directed_relationship",
            "scope": patch.get("scope") or scope,
            "source_character_id": patch.get("source_character_id"),
            "target_character_id": patch.get("target_character_id"),
            "changed": changed,
        })

    for relationship_id in sorted(touched_pair_ids):
        storage.write_relationship_pair(session_id, relationship_id, working_relationships[relationship_id])

    if touched_pair_ids:
        applied["relationships"] = [
            item
            for item in applied.get("relationships", [])
            if not isinstance(item, dict) or item.get("pair_id") not in touched_pair_ids
        ]
        applied["relationships"].extend(directed_applied)

    result["status"] = "partially_applied" if rejected else "applied"
    return result
