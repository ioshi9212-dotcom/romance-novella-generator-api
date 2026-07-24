from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import MAX_CONTEXT_CHUNK_CHARS, MAX_CONTEXT_CHUNKS, RULES_DIR
from app.storage import compact_json_text, parse_jsonl, read_json, read_text


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if item and item not in result:
            result.append(item)
    return result


def _character_scope(root: Path, user_input: str, profile: dict[str, Any], current: dict[str, Any]) -> list[str]:
    index = read_json(root / "state" / "characters" / "index.json", default={}) or {}
    characters = index.get("characters", {}) or {}
    selected = [
        str(profile.get("pov_id") or ""),
        *(current.get("present_character_ids", []) or []),
        *(current.get("nearby_character_ids", []) or []),
        *(current.get("scheduled_character_ids", []) or []),
    ]
    lowered = user_input.lower().replace("ё", "е")
    for character_id, entry in characters.items():
        aliases = [character_id, entry.get("name"), *(entry.get("aliases", []) or [])]
        if any(str(alias or "").lower().replace("ё", "е") in lowered for alias in aliases if alias):
            selected.append(character_id)
    return [item for item in _unique(selected) if item in characters]


def _relevant_facts(
    source: dict[str, Any],
    character_ids: list[str],
    location_id: str | None,
    plotline_ids: list[str],
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key in ("summary", "premise", "world_rules", "core_truths", "supernatural_rules"):
        if key in source:
            output[key] = source[key]

    locations = source.get("locations")
    if isinstance(locations, dict) and location_id and location_id in locations:
        output["current_location"] = {location_id: locations[location_id]}
    elif isinstance(locations, list) and location_id:
        output["current_location"] = [
            item for item in locations if isinstance(item, dict) and item.get("id") == location_id
        ]

    relevant: list[Any] = []
    for fact in source.get("facts", []) or []:
        if not isinstance(fact, dict):
            continue
        fact_characters = set(str(item) for item in fact.get("character_ids", []) or [])
        fact_locations = set(str(item) for item in fact.get("location_ids", []) or [])
        fact_lines = set(str(item) for item in fact.get("plotline_ids", []) or [])
        if (
            fact.get("always_include")
            or fact_characters.intersection(character_ids)
            or (location_id and location_id in fact_locations)
            or fact_lines.intersection(plotline_ids)
        ):
            relevant.append(fact)
    if relevant:
        output["relevant_facts"] = relevant
    return output


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


def _pack_chunks(sections: list[dict[str, Any]]) -> tuple[list[list[dict[str, Any]]], list[str]]:
    warnings: list[str] = []
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
        kept = chunks[:MAX_CONTEXT_CHUNKS]
        dropped_names = [item["name"] for chunk in chunks[MAX_CONTEXT_CHUNKS:] for item in chunk]
        warnings.append("Context was capped; omitted sections: " + ", ".join(dropped_names))
        chunks = kept
    return chunks or [[]], warnings


def build_frozen_packet(
    root: Path,
    user_input: str,
    mode: str,
    base_state_version: int,
    turn_number: int,
) -> dict[str, Any]:
    profile = read_json(root / "state" / "profile.json", default={}) or {}
    current = read_json(root / "state" / "current.json", default={}) or {}
    lore = read_json(root / "state" / "lore.json", default={}) or {}
    hidden = read_json(root / "state" / "hidden_canon.json", default={}) or {}
    plot = read_json(root / "state" / "plot.json", default={}) or {}
    relationships = read_json(root / "state" / "relationships.json", default={}) or {}
    character_ids = _character_scope(root, user_input, profile, current)
    active_plot = _active_plot(plot, character_ids)
    plotline_ids = list((active_plot.get("lines") or {}).keys())
    location_id = str(current.get("location_id") or "") or None

    characters: dict[str, Any] = {}
    knowledge: dict[str, Any] = {}
    for character_id in character_ids:
        characters[character_id] = read_json(
            root / "state" / "characters" / f"{character_id}.json",
            default={},
        ) or {}
        knowledge[character_id] = read_json(
            root / "state" / "knowledge" / f"{character_id}.json",
            default={"character_id": character_id, "entries": []},
        ) or {}

    history = parse_jsonl(read_text(root / "state" / "scene_history.jsonl", default=""))
    history_limit = 10 if (turn_number + 1) % 10 == 0 else 4
    audit_due = mode == "audit" or (turn_number + 1) % 10 == 0

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
        _section("active_plot", active_plot, 2),
        _section("characters", characters, 2),
        _section("knowledge", knowledge, 2),
        _section("relationships", _relationship_subset(relationships, character_ids), 2),
        _section(
            "relevant_lore",
            _relevant_facts(lore, character_ids, location_id, plotline_ids),
            3,
        ),
        _section(
            "relevant_hidden_canon",
            _relevant_facts(hidden, character_ids, location_id, plotline_ids),
            3,
        ),
    ]
    chunks, warnings = _pack_chunks(sections)
    return {
        "base_state_version": base_state_version,
        "turn_number": turn_number,
        "mode": mode,
        "character_ids": character_ids,
        "location_id": location_id,
        "audit_due": audit_due,
        "chunks": chunks,
        "warnings": warnings,
    }
