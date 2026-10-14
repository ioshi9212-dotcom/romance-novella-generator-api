"""Turn-time mechanics derived from the later Roman AI, with no speech ledger.

Relationship updates are optional causal deltas evaluated by the scene writer
and applied by the server to the saved baseline. Heard statements preserve the
*report* from a validated speech source, not its claimed objective truth.
"""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from fastapi import HTTPException


_SPEECH = re.compile(
    r"(?m)^\s*\*\*(?P<name>[^*\n]+)\*\*\s*[-—]\s*(?P<spoken>[^\n]*)"
)


def _spoken_outside_parentheses(value: str) -> str:
    """The player's parenthetical actions and thoughts are never public speech."""
    result: list[str] = []
    depth = 0
    for char in value:
        if char == "(":
            depth += 1
        elif char == ")" and depth > 0:
            depth -= 1
        elif depth == 0:
            result.append(char)
    return "".join(result)


def _spoken_in_scene(scene: str, speaker: str, registry: dict[str, dict[str, Any]]) -> str:
    aliases = {speaker.casefold()}
    row = registry[speaker]
    for field in ("имя", "полное_имя", "имя_и_фамилия", "name"):
        label = row.get(field)
        if isinstance(label, str) and label.strip():
            aliases.add(label.strip().casefold())
            aliases.add(label.strip().split()[0].casefold())
    return "\n".join(
        match.group("spoken")
        for match in _SPEECH.finditer(scene)
        if match.group("name").strip().casefold() in aliases
    )


def add_relationship_changes(patches: dict[str, list[dict[str, Any]]], changes: list[dict[str, Any]],
                             packet: dict[str, Any]) -> None:
    """Translate declared delta/new axis to *sparse* patches without discarding axes."""
    if not changes:
        return
    if "отношения.json" in patches:
        raise HTTPException(422, {
            "code": "RELATIONSHIP_UPDATE_CONFLICT",
            "hint": "Use either relationship_changes or updates['отношения.json'], never both."
        })
    saved = packet["режиссёр"]["отношения"].get("персонажи", {})
    participants = set(packet["персонажи_в_сцене"])
    registry = {c["id"] for c in packet["режиссёр"]["реестр"]["персонажи"]}
    seen: set[tuple[str, str]] = set()
    operations = []
    for row in changes:
        cid, label = row["owner_id"], row["parameter"].strip()
        if cid not in registry or cid not in participants or cid == packet["режиссёр"]["state"]["pov_id"]:
            raise HTTPException(409, {
                "code": "RELATIONSHIP_OWNER_NOT_PARTICIPATING", "character_id": cid,
            })
        if not label:
            raise HTTPException(422, "Relationship metric label cannot be blank")
        if (cid, label) in seen:
            raise HTTPException(422, "Duplicate relationship metric in same turn")
        seen.add((cid, label))
        previous = ((saved.get(cid) or {}).get("к_POV") or {}).get("параметры") or {}
        prior = previous.get(label)
        if row.get("delta") is not None:
            if prior is None:
                raise HTTPException(422, {
                    "code": "RELATIONSHIP_DELTA_NEEDS_EXISTING_AXIS", "character_id": cid, "parameter": label,
                    "hint": "Use initial_value to add a new metric, not a delta."
                })
            target = max(0, min(100, prior + row["delta"]))
        else:
            if prior is not None:
                raise HTTPException(422, {
                    "code": "RELATIONSHIP_NEW_AXIS_ALREADY_EXISTS", "character_id": cid, "parameter": label,
                })
            target = row["initial_value"]
        if prior == target:
            continue  # At a bound. Do not make up a change.
        operations.append({
            "op": "set", "path": f"/персонажи/{cid}/к_POV/параметры/{label}", "value": target
        })
    if operations:
        patches["отношения.json"] = operations


def add_heard_statements(patches: dict[str, list[dict[str, Any]]],
                         statements: list[dict[str, Any]], packet: dict[str, Any],
                         *, user_input: str, scene: str) -> None:
    """Append speaker-attributed *quotes* to each recipient's own knowledge.

    Verifies source is public POV speech (outside brackets) or an actual
    formatted line of dialogue by that speaker in the committed scene.
    The code NEVER evaluates the quoted sentence as a true world fact.
    """
    if not statements:
        return
    registry = {p["id"]: p for p in packet["режиссёр"]["реестр"]["персонажи"]}
    participants = set(packet["персонажи_в_сцене"])
    pov = packet["режиссёр"]["state"]["pov_id"]
    public_input = _spoken_outside_parentheses(user_input)
    date = packet["режиссёр"]["state"].get("дата")
    if not isinstance(date, str) or not date:
        raise HTTPException(409, "Missing game date for attributed knowledge")
    taken: set[tuple[str, str, str]] = set()
    for statement in statements:
        listener, speaker, quote = (
            statement["listener_id"], statement["speaker_id"], statement["quote"].strip()
        )
        if (listener not in registry or speaker not in registry
                or listener not in participants or speaker not in participants
                or speaker == listener):
            raise HTTPException(409, {
                "code": "HEARD_STATEMENT_PARTICIPANT_INVALID",
                "listener_id": listener, "speaker_id": speaker,
            })
        if not quote:
            raise HTTPException(422, "Heard quote must not be blank")
        if (listener, speaker, quote) in taken:
            continue
        taken.add((listener, speaker, quote))
        # No substring from POV's thought may count as proof, even when it is
        # visible to the director in the same input.
        source_from_user = speaker == pov and quote in public_input
        source_from_dialogue = quote in _spoken_in_scene(scene, speaker, registry)
        if not (source_from_user or source_from_dialogue):
            raise HTTPException(409, {
                "code": "HEARD_STATEMENT_SOURCE_MISSING",
                "listener_id": listener,
                "speaker_id": speaker,
                "hint": "Source must be actual spoken dialogue, not a parenthetical thought or director note."
            })
        speaker_name = registry[speaker].get("имя") or speaker
        memory_key = f"память/{listener}.json"
        patches.setdefault(memory_key, []).append({
            "op": "append", "path": f"/знания/{date}",
            "value": f"{speaker_name} сказал(а): «{quote}»",
        })
