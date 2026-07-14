from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.npc_runtime import apply_npc_runtime_patch, build_initial_npc_runtime
from app.relationship_updates import apply_directed_relationship_patches
from app.storage import JsonStorage


def apply_npc_state_patches(
    storage: JsonStorage,
    session_id: str,
    scene_response: dict[str, Any],
    source_bundle: dict[str, Any],
    apply_result: dict[str, Any],
) -> dict[str, Any]:
    """Apply NPC and directed relationship changes in the existing session transaction."""
    result = deepcopy(apply_result) if isinstance(apply_result, dict) else {}
    result.setdefault("applied", {})
    result["applied"].setdefault("npc_state", [])
    result.setdefault("rejected", [])
    result.setdefault("next_builder_hints", {})

    updates = scene_response.get("proposed_updates") if isinstance(scene_response, dict) else {}
    patches = updates.get("npc_state_patches") if isinstance(updates, dict) else []
    if not isinstance(patches, list):
        patches = []

    if patches:
        source_current = source_bundle.get("current_state") if isinstance(source_bundle.get("current_state"), dict) else {}
        characters = source_bundle.get("characters") if isinstance(source_bundle.get("characters"), dict) else {}
        player_id = str(source_current.get("player_character_id") or "")
        source_scene_ids = {
            str(item)
            for item in [
                *(source_current.get("active_character_ids") or []),
                *(source_current.get("nearby_character_ids") or []),
            ]
            if item
        }

        saved_current = storage.read_json(session_id, "current_state.json", default={})
        turn_number = int((saved_current or {}).get("turn_number", 0) or 0)
        npc_state = storage.read_json(session_id, "npc_state.json", default={})
        if not isinstance(npc_state, dict):
            npc_state = {}

        for patch in patches:
            if not isinstance(patch, dict):
                result["rejected"].append({"target": "npc_state", "reason": "patch must be an object", "severity": "error"})
                continue
            character_id = str(patch.get("character_id") or "").strip()
            if not character_id:
                result["rejected"].append({"target": "npc_state", "reason": "missing character_id", "severity": "error"})
                continue
            if not str(patch.get("reason") or "").strip() or not str(patch.get("source_in_scene") or "").strip():
                result["rejected"].append({
                    "target": f"npc_state.{character_id}",
                    "reason": "npc state patch requires reason and source_in_scene",
                    "severity": "error",
                })
                continue

            card = characters.get(character_id)
            if not isinstance(card, dict):
                result["rejected"].append({"target": f"npc_state.{character_id}", "reason": "unknown character_id", "severity": "error"})
                continue
            if character_id == player_id:
                result["rejected"].append({"target": f"npc_state.{character_id}", "reason": "player character does not use npc_state", "severity": "error"})
                continue
            if card.get("available_to_scene") is False or card.get("introduced") is False:
                result["rejected"].append({
                    "target": f"npc_state.{character_id}",
                    "reason": "hidden or unavailable character cannot receive a scene patch before reveal",
                    "severity": "error",
                })
                continue
            if character_id not in source_scene_ids:
                result["rejected"].append({
                    "target": f"npc_state.{character_id}",
                    "reason": "character was not active or nearby in this scene",
                    "severity": "error",
                })
                continue

            base = build_initial_npc_runtime(card, npc_state.get(character_id))
            merged, changed = apply_npc_runtime_patch(base, patch, turn_number=turn_number)
            if not changed:
                continue
            npc_state[character_id] = merged
            result["applied"]["npc_state"].append({
                "character_id": character_id,
                "operation": "merge_runtime",
                "fields": sorted(changed),
            })

        storage.write_json(session_id, "npc_state.json", npc_state)

    result = apply_directed_relationship_patches(
        storage,
        session_id,
        scene_response,
        source_bundle,
        result,
    )

    if result["rejected"]:
        result["status"] = "partially_applied"
        result["next_builder_hints"]["repair_required"] = True
    return result
