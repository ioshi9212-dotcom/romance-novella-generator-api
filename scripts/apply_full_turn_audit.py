from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"missing patch anchor: {label} in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


main = ROOT / "app" / "main.py"
replace_once(
    main,
    "from app.npc_state_updates import apply_npc_state_patches\n",
    "from app.npc_state_updates import apply_npc_state_patches\nfrom app.persistence_audit import run_persistence_audit\n",
    "main persistence audit import",
)
replace_once(
    main,
    '''            result = record_time_skip_result(\n                manager.storage,\n                session_id,\n                pending,\n                normalized_scene_response,\n                bundle,\n                result,\n            )\n            _mark_pending_turn_applied(manager, session_id, pending)\n''',
    '''            result = record_time_skip_result(\n                manager.storage,\n                session_id,\n                pending,\n                normalized_scene_response,\n                bundle,\n                result,\n            )\n            result = run_persistence_audit(\n                manager.storage,\n                session_id,\n                normalized_scene_response,\n                result,\n            )\n            _mark_pending_turn_applied(manager, session_id, pending)\n''',
    "run persistence audit after all patches",
)

state_updater = ROOT / "app" / "state_updater.py"
replace_once(
    state_updater,
    "MAX_MEMORY_CHUNKS = 12\n",
    "MAX_MEMORY_CHUNKS = 12\nMAX_ARCHIVED_SCENE_SUMMARIES = 120\nMAX_ARCHIVED_TURN_SUMMARIES = 160\n",
    "archive limits",
)
archive_helpers = '''\n\ndef _dedupe_summary_items(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:\n    result: list[dict[str, Any]] = []\n    seen: set[tuple[Any, str]] = set()\n    for item in items:\n        if not isinstance(item, dict):\n            continue\n        key = (item.get("turn"), str(item.get("summary") or item.get("player_input") or ""))\n        if key in seen:\n            continue\n        seen.add(key)\n        result.append(item)\n    return result[-limit:]\n\n\ndef _merge_memory_chunks(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:\n    scene_summaries = _dedupe_summary_items(\n        [*(left.get("scene_summaries") or []), *(right.get("scene_summaries") or [])],\n        MAX_ARCHIVED_SCENE_SUMMARIES,\n    )\n    turn_summaries = _dedupe_summary_items(\n        [*(left.get("turn_summaries") or []), *(right.get("turn_summaries") or [])],\n        MAX_ARCHIVED_TURN_SUMMARIES,\n    )\n    starts = [value for value in (left.get("turn_start"), right.get("turn_start")) if isinstance(value, int)]\n    ends = [value for value in (left.get("turn_end"), right.get("turn_end")) if isinstance(value, int)]\n    start = min(starts) if starts else None\n    end = max(ends) if ends else None\n    return {\n        "chunk_id": f"long_term_archive_{start or 'x'}_{end or 'x'}",\n        "type": "long_term_archive",\n        "turn_start": start,\n        "turn_end": end,\n        "created_at": now_iso(),\n        "scene_summaries": scene_summaries,\n        "turn_summaries": turn_summaries,\n        "merged_chunk_ids": [\n            item for item in [left.get("chunk_id"), right.get("chunk_id")] if item\n        ],\n    }\n'''
replace_once(
    state_updater,
    "\ndef _append_memory_chunk(continuity: dict[str, Any], chunk: dict[str, Any] | None) -> bool:\n",
    archive_helpers + "\n\ndef _append_memory_chunk(continuity: dict[str, Any], chunk: dict[str, Any] | None) -> bool:\n",
    "memory archive helpers",
)
replace_once(
    state_updater,
    '''    if chunk.get("chunk_id") not in existing_ids:\n        continuity["memory_chunks"].append(chunk)\n    continuity["memory_chunks"] = continuity.get("memory_chunks", [])[-MAX_MEMORY_CHUNKS:]\n    return True\n''',
    '''    if chunk.get("chunk_id") not in existing_ids:\n        continuity["memory_chunks"].append(chunk)\n    chunks = [item for item in continuity.get("memory_chunks", []) if isinstance(item, dict)]\n    while len(chunks) > MAX_MEMORY_CHUNKS:\n        chunks = [_merge_memory_chunks(chunks[0], chunks[1]), *chunks[2:]]\n    continuity["memory_chunks"] = chunks\n    return True\n''',
    "coalesce memory chunks instead of dropping oldest",
)
replace_once(
    state_updater,
    '''    continuity["maintenance_events"] = [\n        item for item in (continuity.get("maintenance_events", []) or []) if isinstance(item, dict)\n    ][-12:]\n    return continuity\n''',
    '''    continuity["maintenance_events"] = [\n        item for item in (continuity.get("maintenance_events", []) or []) if isinstance(item, dict)\n    ][-12:]\n    continuity["persistence_audits"] = [\n        item for item in (continuity.get("persistence_audits", []) or []) if isinstance(item, dict)\n    ][-12:]\n    return continuity\n''',
    "retain persistence audits",
)

scene_builder = ROOT / "app" / "scene_contract_builder.py"
replace_once(
    scene_builder,
    '''def _compact_memory_chunk(chunk: Any) -> dict[str, Any]:\n    if not isinstance(chunk, dict):\n        return {}\n    return {\n        "type": chunk.get("type"),\n        "turn_start": chunk.get("turn_start"),\n        "turn_end": chunk.get("turn_end"),\n        "scene_summaries": _clip_list(chunk.get("scene_summaries", []), 4, 180),\n        "turn_summaries": _clip_list(chunk.get("turn_summaries", []), 4, 160),\n    }\n''',
    '''def _edge_sample(items: Any, limit: int = 4) -> list[Any]:\n    values = list(items or []) if isinstance(items, list) else []\n    if len(values) <= limit:\n        return values\n    edge = max(1, limit // 2)\n    sampled = [*values[:edge], *values[-edge:]]\n    result: list[Any] = []\n    for item in sampled:\n        if item not in result:\n            result.append(item)\n    return result[:limit]\n\n\ndef _compact_memory_chunk(chunk: Any) -> dict[str, Any]:\n    if not isinstance(chunk, dict):\n        return {}\n    return {\n        "type": chunk.get("type"),\n        "turn_start": chunk.get("turn_start"),\n        "turn_end": chunk.get("turn_end"),\n        "scene_summaries": _clip_list(_edge_sample(chunk.get("scene_summaries", []), 4), 4, 180),\n        "turn_summaries": _clip_list(_edge_sample(chunk.get("turn_summaries", []), 4), 4, 160),\n    }\n''',
    "sample both ends of long-term memory chunks",
)
replace_once(
    scene_builder,
    '''        "maintenance_events": _clip_list(continuity.get("maintenance_events", []), 4, 160),\n    }\n''',
    '''        "maintenance_events": _clip_list(continuity.get("maintenance_events", []), 4, 160),\n        "persistence_audits": _clip_list(continuity.get("persistence_audits", [])[-2:], 2, 220),\n    }\n''',
    "expose compact persistence audits",
)
replace_once(
    scene_builder,
    '''    memory_chunks = [\n        _compact_memory_chunk(chunk)\n        for chunk in (continuity.get("memory_chunks", []) or [])[-4:]\n        if isinstance(chunk, dict)\n    ]\n''',
    '''    all_memory_chunks = [\n        chunk for chunk in (continuity.get("memory_chunks", []) or []) if isinstance(chunk, dict)\n    ]\n    selected_memory_chunks = all_memory_chunks if len(all_memory_chunks) <= 4 else [all_memory_chunks[0], *all_memory_chunks[-3:]]\n    memory_chunks = [_compact_memory_chunk(chunk) for chunk in selected_memory_chunks]\n''',
    "load long-term and recent memory chunks",
)
replace_once(
    scene_builder,
    '''            "memory_chunk_count": len(memory_chunks),\n        },\n''',
    '''            "memory_chunk_count": len(all_memory_chunks),\n            "last_persistence_audit": ((continuity.get("persistence_audits") or [])[-1] if continuity.get("persistence_audits") else None),\n        },\n''',
    "maintenance audit summary in scene contract",
)

turn_processor = ROOT / "app" / "turn_processor.py"
replace_once(
    turn_processor,
    '''def _compact_contract(contract: dict[str, Any]) -> dict[str, Any]:\n    compact = {\n''',
    '''def _compact_contract(contract: dict[str, Any]) -> dict[str, Any]:\n    memory_source = [item for item in (contract.get("memory_chunks", []) or []) if isinstance(item, dict)]\n    selected_memory = memory_source if len(memory_source) <= 3 else [memory_source[0], *memory_source[-2:]]\n    compact = {\n''',
    "select long-term memory in compact prompt",
)
replace_once(
    turn_processor,
    '''        "memory_chunks": [_compact_dict(i, 220) for i in (contract.get("memory_chunks", []) or [])[-3:] if isinstance(i, dict)],\n''',
    '''        "memory_chunks": [_compact_dict(i, 220) for i in selected_memory],\n''',
    "keep selected memory chunks",
)

director = ROOT / "app" / "director_bible.py"
replace_once(
    director,
    '''        "current_turn": current_turn,\n        "world_truth": bible.get("world_truth", {}),\n''',
    '''        "current_turn": current_turn,\n        "tone_control": {\n            "dry_sarcasm_target_share": "примерно 5–7% видимого текста, не квота и не обязанность",\n            "preferred_dose": "обычно одна короткая сухая реплика или наблюдение; иногда ноль",\n            "source": "только подходящий голос персонажа или редкая авторская деталь, не одинаковая язвительность всех NPC",\n            "avoid": "не ставить в каждый абзац, не перебивать горе, страх, интимность или серьёзное раскрытие",\n        },\n        "world_truth": bible.get("world_truth", {}),\n''',
    "director sarcasm tone control",
)

scene_style = ROOT / "rules" / "scene_style.md"
replace_once(
    scene_style,
    "Лёгкая сухая ирония допустима 1–2 раза за сцену, если не ломает тяжёлый или интимный момент. Не делай всех одинаково язвительными.\n",
    "Сухая ирония или лёгкий сарказм занимают ориентировочно 5–7% видимого текста: обычно одна короткая реплика, реакция или авторская деталь, иногда ни одной. Это не квота. Не вставляй их в каждый абзац, не перебивай горе, страх, интимность и серьёзное раскрытие; не делай всех NPC одинаково язвительными.\n",
    "sarcasm budget in scene style",
)
