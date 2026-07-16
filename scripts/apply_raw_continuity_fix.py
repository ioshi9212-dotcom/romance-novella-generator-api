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


state_updater = ROOT / "app" / "state_updater.py"
replace_once(
    state_updater,
    '''        bundle = self.storage.read_session_bundle(session_id)\n        current_state = bundle.get("current_state", {})\n        relationships = bundle.get("relationships", {})\n        knowledge = bundle.get("knowledge", {})\n        characters = bundle.get("characters", {})\n        scene_history = bundle.get("scene_history", []) or []\n        turns = bundle.get("turns", []) or []\n        continuity = bundle.get("continuity", {}) or {}\n''',
    '''        bundle = self.storage.read_session_bundle(session_id)\n        current_state = self.storage.read_json(session_id, "current_state.json", default=bundle.get("current_state", {}))\n        relationships = bundle.get("relationships", {})\n        knowledge = bundle.get("knowledge", {})\n        characters = bundle.get("characters", {})\n        scene_history = self.storage.read_json(session_id, "scene_history.json", default=[]) or []\n        turns = self.storage.read_json(session_id, "turns.json", default=[]) or []\n        continuity = self.storage.read_json(session_id, "continuity.json", default={}) or {}\n''',
    "state updater reads raw mutable files",
)

persistence_audit = ROOT / "app" / "persistence_audit.py"
replace_once(
    persistence_audit,
    '''    bundle = storage.read_session_bundle(session_id)\n    current_state = bundle.get("current_state") if isinstance(bundle.get("current_state"), dict) else {}\n    scene_history = bundle.get("scene_history") if isinstance(bundle.get("scene_history"), list) else []\n    turns = bundle.get("turns") if isinstance(bundle.get("turns"), list) else []\n    continuity = bundle.get("continuity") if isinstance(bundle.get("continuity"), dict) else {}\n    memory_chunks = continuity.get("memory_chunks") if isinstance(continuity.get("memory_chunks"), list) else []\n''',
    '''    bundle = storage.read_session_bundle(session_id)\n    current_state = storage.read_json(session_id, "current_state.json", default={})\n    scene_history = storage.read_json(session_id, "scene_history.json", default=[])\n    turns = storage.read_json(session_id, "turns.json", default=[])\n    continuity = storage.read_json(session_id, "continuity.json", default={})\n    current_state = current_state if isinstance(current_state, dict) else {}\n    scene_history = scene_history if isinstance(scene_history, list) else []\n    turns = turns if isinstance(turns, list) else []\n    continuity = continuity if isinstance(continuity, dict) else {}\n    memory_chunks = continuity.get("memory_chunks") if isinstance(continuity.get("memory_chunks"), list) else []\n''',
    "persistence audit reads raw files",
)

storage = ROOT / "app" / "storage.py"
selector = '''\n\ndef _select_long_term_and_recent_chunks(chunks: Any, limit: int = 6) -> list[dict[str, Any]]:\n    values = [item for item in (chunks or []) if isinstance(item, dict)]\n    if len(values) <= limit:\n        return values\n    return [values[0], *values[-(limit - 1):]]\n'''
replace_once(
    storage,
    "\ndef _compact_continuity_for_actions(continuity: Any) -> dict[str, Any]:\n",
    selector + "\n\ndef _compact_continuity_for_actions(continuity: Any) -> dict[str, Any]:\n",
    "long-term continuity chunk selector",
)
replace_once(
    storage,
    '''    result["memory_chunks"] = [\n        _compact_memory_chunk(chunk)\n        for chunk in (continuity.get("memory_chunks", []) or [])[-6:]\n        if isinstance(chunk, dict)\n    ]\n    result["maintenance_events"] = _compact_list(continuity.get("maintenance_events", []), 6, 200)\n    result["gpt_memory_compacts"] = _compact_list(continuity.get("gpt_memory_compacts", []), 4, 200)\n''',
    '''    result["memory_chunks"] = [\n        _compact_memory_chunk(chunk)\n        for chunk in _select_long_term_and_recent_chunks(continuity.get("memory_chunks", []), 6)\n    ]\n    result["maintenance_events"] = _compact_list(continuity.get("maintenance_events", []), 6, 200)\n    result["persistence_audits"] = _compact_list(continuity.get("persistence_audits", [])[-2:], 2, 240)\n    result["gpt_memory_compacts"] = _compact_list(continuity.get("gpt_memory_compacts", []), 4, 200)\n''',
    "compact continuity exposes audits and long-term memory",
)
