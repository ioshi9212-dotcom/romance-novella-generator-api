"""One-pass, read-only context assembly for a novel turn.

The director sees the whole short index, but full personal files are loaded only
for scene participants and explicitly selected off-screen characters. There is
no memory slicing, arbitrary keyword matching, or persistent turn packet.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException


def _unique(ids: list[str]) -> list[str]:
    return list(dict.fromkeys(ids))


def _scene_ids(state: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for field in ("физически", "удалённо"):
        participants = state.get(field, [])
        if not isinstance(participants, list):
            raise HTTPException(409, f"State: {field} must be a list")
        for row in participants:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                raise HTTPException(409, f"State: invalid participant in {field}")
            character_id = row["id"]
            if character_id in ids:
                raise HTTPException(409, f"A character appears twice in scene participation: {character_id}")
            ids.append(character_id)
    return ids


def _preview_entries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The index is deliberately navigable, not a replacement for full lore."""
    index: list[dict[str, Any]] = []
    for number, entry in enumerate(rows):
        synopsis = str(entry.get("суть", ""))
        index.append({
            "индекс": number,
            "суть_кратко": synopsis[:300],
            "есть_продолжение": len(synopsis) > 300,
            "связанные_id": entry.get("связанные_id", []),
            "появилось": entry.get("появилось", ""),
        })
    return index


def _selected_entries(
    entries: list[dict[str, Any]], participants: set[str], selected: list[int], section: str
) -> list[dict[str, Any]]:
    for index in selected:
        if isinstance(index, bool) or not isinstance(index, int) or index < 0 or index >= len(entries):
            raise HTTPException(422, f"Unknown {section} index: {index}")
    chosen: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        linked = entry.get("связанные_id", [])
        if not isinstance(linked, list):
            raise HTTPException(409, f"Invalid linked IDs in {section}[{index}]")
        if index in selected or (linked and participants.intersection(linked)):
            chosen.append({"индекс": index, "запись": entry})
    return chosen


def _last_scenes(root: Path, count: int = 2) -> list[dict[str, Any]]:
    """Tail read, so preparing a turn does not reread thousands of archived scenes."""
    archive = root / "ходы.jsonl"
    if not archive.exists():
        return []
    with archive.open("rb") as handle:
        handle.seek(0, 2)
        pos = handle.tell()
        buffer = b""
        while pos > 0 and len([x for x in buffer.split(b"\n") if x.strip()]) <= count:
            step = min(pos, 8192)
            pos -= step
            handle.seek(pos)
            buffer = handle.read(step) + buffer
    rows = [row for row in buffer.split(b"\n") if row.strip()][-count:]
    try:
        history = [json.loads(row.decode("utf-8")) for row in rows]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(409, "Turn archive contains a damaged record") from exc
    if not all(isinstance(row, dict) for row in history):
        raise HTTPException(409, "Turn archive contains an invalid record")
    # Archive receipts also contain reversible JSON changes. Never feed those
    # large technical snapshots into the scene-writing context.
    return [
        {"номер": row.get("номер"), "turn_id": row.get("turn_id"),
         "ввод": row.get("ввод", ""), "сцена": row.get("сцена", "")}
        for row in history
    ]


def build_packet(
    root: Path,
    meta: dict[str, Any],
    user_input: str,
    additional_character_ids: list[str],
    selected_hook_indices: list[int],
    selected_secret_indices: list[int],
    additional_location_ids: list[str],
    full_memory_character_ids: list[str] | None = None,
    full_chronology: bool = False,
) -> dict[str, Any]:
    """Read one consistent snapshot under the caller's session lock."""
    # Read only these public directorial files each time; no full RAW, all cards,
    # or historical scene archive scan.
    def document(path: str) -> dict[str, Any]:
        file = root / path
        if not file.is_file():
            raise HTTPException(409, f"Missing required context file: {path}")
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise HTTPException(409, f"Damaged context file: {path}") from exc
        if not isinstance(data, dict):
            raise HTTPException(409, f"Invalid context file: {path}")
        return data

    from .session_continuity import get_checkpoint, working_history, working_memory
    from .runtime_docs import read_runtime
    active_runtime = read_runtime()
    checkpoint = get_checkpoint(root, meta)
    full_memory = set(full_memory_character_ids or [])

    novel = document("анкета.json")
    state = document("state.json")
    history = document("хронология.json")
    roster = document("персонажи.json")
    relations = document("отношения.json")
    lore = document("скрытый_лор_и_крючки.json")
    locations = document("локации.json")

    cast = roster.get("персонажи")
    if not isinstance(cast, list):
        raise HTTPException(409, "Character registry is invalid")
    registry = {entry.get("id"): entry for entry in cast if isinstance(entry, dict)}
    if len(registry) != len(cast):
        raise HTTPException(409, "Character registry has duplicate or invalid IDs")

    present = _scene_ids(state)
    pov_id = state.get("pov_id")
    if not pov_id or pov_id not in present:
        raise HTTPException(409, "POV must be in the active scene")
    selected_ids = _unique(present + additional_character_ids)
    for character_id in full_memory:
        if character_id not in selected_ids:
            raise HTTPException(422, f"Full memory requested for unloaded character: {character_id}")
    for character_id in selected_ids:
        if character_id not in registry:
            raise HTTPException(422, f"Unknown character: {character_id}")

    character_data: dict[str, dict[str, Any]] = {}
    for character_id in selected_ids:
        card = document(f"карточки/{character_id}.json")
        memory = document(f"память/{character_id}.json")
        if card.get("id") != character_id or memory.get("персонаж_id") != character_id:
            raise HTTPException(409, f"Card or memory belongs to another character: {character_id}")
        if character_id not in full_memory:
            memory, memory_info = working_memory(memory, character_id, checkpoint)
        else:
            memory_info = {"режим_памяти": "полный_по_запросу"}
        character_data[character_id] = {"карточка": card, "память": memory, **memory_info}

    scene_location = state.get("локация") if isinstance(state.get("локация"), dict) else {}
    required_locations = _unique(([scene_location["id"]] if scene_location.get("id") else []) + additional_location_ids)
    places = locations.get("локации", [])
    if not isinstance(places, list):
        raise HTTPException(409, "Invalid location registry")
    by_location = {place.get("id"): place for place in places if isinstance(place, dict)}
    loaded_locations: dict[str, dict[str, Any]] = {}
    for location_id in required_locations:
        if location_id not in by_location:
            raise HTTPException(422, f"Unknown location: {location_id}")
        loaded_locations[location_id] = by_location[location_id]

    secrets, hooks = lore.get("скрытый_лор", []), lore.get("крючки", [])
    if not isinstance(secrets, list) or not all(isinstance(x, dict) for x in secrets):
        raise HTTPException(409, "Invalid secrets data")
    if not isinstance(hooks, list) or not all(isinstance(x, dict) for x in hooks):
        raise HTTPException(409, "Invalid hooks data")

    if checkpoint and not full_chronology:
        history, history_info = working_history(history, checkpoint)
    elif checkpoint:
        history_info = {"режим_хронологии": "полная_по_запросу"}
    else:
        history_info = {}
    active = set(selected_ids)
    # A presentation-ready view of ALL existing relation metrics for characters
    # participating in this scene. Do not confuse "changed this turn" with
    # "visible in the footer"; off-screen loaded NPCs are not displayed.
    owners = relations.get("персонажи", {})
    visible_relations: dict[str, dict[str, Any]] = {}
    if isinstance(owners, dict):
        for cid in present:
            if cid == pov_id:
                continue
            record = owners.get(cid, {})
            relation = record.get("к_POV", {}) if isinstance(record, dict) else {}
            metrics = relation.get("параметры", {}) if isinstance(relation, dict) else {}
            if isinstance(metrics, dict) and metrics:
                display_name = registry[cid].get("имя") or cid
                visible_relations[cid] = {"имя": display_name, "параметры": metrics}
    packet = {
        # The actual scene instruction text is sent on *every* prepare-turn.
        # A remembered GPT instruction from an older chat can never replace it.
        "актуальные_инструкции": {
            "skin_builder": active_runtime["skin_builder"],
            "skin_builder_sha256": active_runtime["skin_builder_sha256"],
            "rules_sha256": active_runtime["rules_sha256"],
            "runtime_sha256": active_runtime["sha256"],
            "применение": (
                "Используй именно этот полный Skin Builder для текущей сцены, "
                "даже если в чате ранее была другая версия. "
                "При изменении rules_sha256 обнови технические Rules через getRuntimeInstructions."
            ),
        },
        "session_id": meta["id"],
        "номер_хода": meta["последний_ход"] + 1,
        "turn_id": f"{meta['id']}:{meta['последний_ход'] + 1}",
        "ввод_игрока": user_input,
        "ввод_sha256": hashlib.sha256(user_input.encode("utf-8")).hexdigest(),
        "режиссёр": {
            "анкета": novel,
            "хронология": history,
            **history_info,
            "state": state,
            "реестр": roster,
            "отношения": relations,
            "крючки_обзор": _preview_entries(hooks),
            "тайны_обзор": _preview_entries(secrets),
            "релевантные_крючки": _selected_entries(hooks, active, selected_hook_indices, "крючки"),
            "релевантные_тайны": _selected_entries(secrets, active, selected_secret_indices, "тайны"),
            "локации_обзор": [{"id": p.get("id"), "название": p.get("название")} for p in places],
            "локации_подробно": loaded_locations,
        },
        "персонажи_подробно": character_data,
        "персонажи_в_сцене": present,
        "отношения_участников_для_футера": visible_relations,
        "дополнительно_выбранные_NPC": [cid for cid in selected_ids if cid not in present],
        "последние_сцены": _last_scenes(root),
        "последнее_сжатие": checkpoint["through_turn"] if checkpoint else 0,
        "граница_знаний": (
            "Режиссёрские карточки, чужая память, скрытый лор и хронология не являются "
            "знаниями POV или NPC. Используй только доступную персонажу часть его прошлого, "
            "его личную память, лично воспринятую сцену и сообщённое ему. "
            "Уточняй релевантные карточки до включения нового NPC в действие."
        ),
    }
    # Identifies the exact assembled context even if the same turn is prepared
    # again with additional selected NPCs. No read-side effects or pending files.
    snapshot = json.dumps(packet["актуальные_инструкции"], sort_keys=True, ensure_ascii=False)
    snapshot += json.dumps(packet["режиссёр"], sort_keys=True, ensure_ascii=False)
    snapshot += json.dumps(packet["персонажи_подробно"], sort_keys=True, ensure_ascii=False)
    snapshot += json.dumps(packet["последние_сцены"], sort_keys=True, ensure_ascii=False)
    packet["контекст_sha256"] = hashlib.sha256(snapshot.encode("utf-8")).hexdigest()
    return packet