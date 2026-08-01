from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.config import MAX_CONTEXT_CHUNK_CHARS, MAX_CONTEXT_CHUNKS, RULES_DIR
from app.storage import compact_json_text, parse_jsonl, read_json, read_text


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if item and item not in result:
            result.append(item)
    return result


def _character_scope(
    root: Path,
    user_input: str,
    profile: dict[str, Any],
    current: dict[str, Any],
    include_all: bool = False,
) -> list[str]:
    index = read_json(root / "state" / "characters" / "index.json", default={}) or {}
    characters = index.get("characters", {}) or {}
    selected = [
        str(profile.get("pov_id") or ""),
        *(current.get("present_character_ids", []) or []),
        *(current.get("nearby_character_ids", []) or []),
        *(current.get("scheduled_character_ids", []) or []),
    ]
    if include_all:
        selected.extend(str(character_id) for character_id in characters)
    lowered = user_input.lower().replace("ё", "е")
    for character_id, entry in characters.items():
        aliases = [character_id, entry.get("name"), *(entry.get("aliases", []) or [])]
        if any(str(alias or "").lower().replace("ё", "е") in lowered for alias in aliases if alias):
            selected.append(character_id)
    selected_ids = _unique(selected)
    unknown_ids = [item for item in selected_ids if item not in characters]
    if unknown_ids:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "scene_context_incomplete",
                "message": "Current state references characters missing from the character index",
                "missing_character_ids": unknown_ids,
            },
        )
    return selected_ids


def _active_plot(plot: dict[str, Any], character_ids: list[str]) -> dict[str, Any]:
    lines = plot.get("lines", {})
    selected: dict[str, Any] = {}
    if isinstance(lines, list):
        iterable = ((str(item.get("id") or ""), item) for item in lines if isinstance(item, dict))
    elif isinstance(lines, dict):
        iterable = ((str(key), value) for key, value in lines.items() if isinstance(value, dict))
    else:
        iterable = []
    character_set = set(character_ids)
    for line_id, line in iterable:
        if not line_id or line.get("status", "active") not in {"active", "open", "paused"}:
            continue
        participants = set(str(item) for item in line.get("participant_ids", []) or [])
        if line.get("always_include") or not participants or participants.intersection(character_set):
            selected[line_id] = line
    return {
        "lines": selected,
        "clocks": plot.get("clocks", {}),
        "npc_plans": [
            item
            for item in plot.get("npc_plans", []) or []
            if not isinstance(item, dict)
            or not item.get("character_id")
            or item.get("character_id") in character_set
        ],
    }


def _relationship_subset(relationships: dict[str, Any], character_ids: list[str]) -> dict[str, Any]:
    selected: dict[str, Any] = {}
    character_set = set(character_ids)
    for pair_id, value in (relationships.get("pairs", {}) or {}).items():
        pair_members = set(str(pair_id).split("__"))
        if len(pair_members) == 2 and pair_members.issubset(character_set):
            selected[str(pair_id)] = value
    return {"pairs": selected}


def _section(name: str, data: Any, priority: int) -> dict[str, Any]:
    return {"name": name, "priority": priority, "data": data}


def _split_oversized_section(section: dict[str, Any], max_chars: int) -> list[dict[str, Any]]:
    if len(compact_json_text(section)) <= max_chars:
        return [section]
    data = section.get("data")
    pieces: list[dict[str, Any]] = []
    if isinstance(data, dict):
        for key, value in data.items():
            pieces.extend(
                _split_oversized_section(
                    _section(
                        f"{section['name']}.{key}",
                        value,
                        section["priority"],
                    ),
                    max_chars,
                )
            )
    elif isinstance(data, list):
        current_list: list[Any] = []
        part = 1
        for item in data:
            candidate = _section(
                f"{section['name']}:{part}",
                [*current_list, item],
                section["priority"],
            )
            if current_list and len(compact_json_text(candidate)) > max_chars:
                pieces.append(
                    _section(f"{section['name']}:{part}", current_list, section["priority"])
                )
                current_list = [item]
                part += 1
            elif not current_list and len(compact_json_text(candidate)) > max_chars:
                pieces.extend(
                    _split_oversized_section(
                        _section(
                            f"{section['name']}:{part}",
                            item,
                            section["priority"],
                        ),
                        max_chars,
                    )
                )
                part += 1
            else:
                current_list.append(item)
        if current_list:
            pieces.append(_section(f"{section['name']}:{part}", current_list, section["priority"]))
    else:
        text = str(data)
        allowance = max(1000, max_chars - 500)
        for part, offset in enumerate(range(0, len(text), allowance), start=1):
            pieces.append(
                _section(
                    f"{section['name']}:{part}",
                    text[offset : offset + allowance],
                    section["priority"],
                )
            )
    return pieces


def _pack_chunks(sections: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    expanded: list[dict[str, Any]] = []
    for section in sections:
        expanded.extend(_split_oversized_section(section, MAX_CONTEXT_CHUNK_CHARS))

    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for section in expanded:
        candidate = [*current, section]
        if current and len(compact_json_text(candidate)) > MAX_CONTEXT_CHUNK_CHARS:
            chunks.append(current)
            current = [section]
        else:
            current = candidate
    if current:
        chunks.append(current)

    if len(chunks) > MAX_CONTEXT_CHUNKS:
        overflow_names = [
            item["name"]
            for chunk in chunks[MAX_CONTEXT_CHUNKS:]
            for item in chunk
        ]
        raise HTTPException(
            status_code=413,
            detail={
                "code": "scene_context_too_large",
                "message": (
                    "The complete scene context does not fit the configured packet budget; "
                    "the scene was not prepared and no canon was changed"
                ),
                "required_chunks": len(chunks),
                "max_chunks": MAX_CONTEXT_CHUNKS,
                "overflow_sections": overflow_names,
            },
        )
    return chunks or [[]]


def _required_state_object(root: Path, relative_path: str, label: str) -> dict[str, Any]:
    value = read_json(root / relative_path, default=None)
    if not isinstance(value, dict) or not value:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "scene_context_incomplete",
                "message": f"Required scene state is missing or empty: {label}",
                "missing_sections": [label],
            },
        )
    return value


def build_frozen_packet(
    root: Path,
    user_input: str,
    mode: str,
    base_state_version: int,
    turn_number: int,
) -> dict[str, Any]:
    profile = _required_state_object(root, "state/profile.json", "profile")
    current = _required_state_object(root, "state/current.json", "current")
    lore = _required_state_object(root, "state/lore.json", "lore")
    hidden = _required_state_object(root, "state/hidden_canon.json", "hidden_canon")
    plot = _required_state_object(root, "state/plot.json", "plot")
    relationships = _required_state_object(
        root,
        "state/relationships.json",
        "relationships",
    )
    audit_due = mode == "audit" or (
        mode == "play" and (turn_number + 1) % 10 == 0
    )
    character_ids = _character_scope(
        root,
        user_input,
        profile,
        current,
        include_all=audit_due,
    )
    active_plot = _active_plot(plot, character_ids)
    location_id = str(current.get("location_id") or "") or None

    characters: dict[str, Any] = {}
    knowledge: dict[str, Any] = {}
    for character_id in character_ids:
        characters[character_id] = _required_state_object(
            root,
            f"state/characters/{character_id}.json",
            f"character.{character_id}",
        )
        knowledge_path = root / "state" / "knowledge" / f"{character_id}.json"
        knowledge_value = read_json(knowledge_path, default=None)
        if not isinstance(knowledge_value, dict):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "scene_context_incomplete",
                    "message": f"Knowledge state is missing for character {character_id}",
                    "missing_sections": [f"knowledge.{character_id}"],
                },
            )
        knowledge[character_id] = knowledge_value

    history = parse_jsonl(read_text(root / "state" / "scene_history.jsonl", default=""))
    chronology = parse_jsonl(read_text(root / "state" / "chronology.jsonl", default=""))
    history_limit = 10 if (turn_number + 1) % 10 == 0 else 4
    rules = {
        name: read_text(RULES_DIR / name, default="")
        for name in ("runtime_core.md", "scene.md", "state_update.md")
    }
    sections = [
        _section("turn_contract", {
            "mode": mode,
            "base_state_version": base_state_version,
            "next_turn_number": turn_number + (1 if mode == "play" else 0),
            "user_input": user_input,
            "audit_due": audit_due,
        }, 1),
        _section("rules", rules, 1),
        _section("profile", profile, 1),
        _section("current", current, 1),
        _section("recent_scene_summaries", history[-history_limit:], 1),
        _section("chronology", chronology, 1),
        _section("active_plot", active_plot, 2),
        *(
            _section(f"character.{character_id}", characters[character_id], 2)
            for character_id in character_ids
        ),
        *(
            _section(f"knowledge.{character_id}", knowledge[character_id], 2)
            for character_id in character_ids
        ),
        _section("relationships", _relationship_subset(relationships, character_ids), 2),
        _section("lore", lore, 3),
        _section("hidden_canon", hidden, 3),
    ]
    chunks = _pack_chunks(sections)
    included_sections = [item["name"] for chunk in chunks for item in chunk]
    return {
        "base_state_version": base_state_version,
        "turn_number": turn_number,
        "mode": mode,
        "character_ids": character_ids,
        "location_id": location_id,
        "audit_due": audit_due,
        "chunks": chunks,
        "context_complete": True,
        "included_sections": included_sections,
        "warnings": [],
    }
