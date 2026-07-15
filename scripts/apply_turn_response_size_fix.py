from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / "app" / "main.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"missing patch anchor: {label}")
    return text.replace(old, new, 1)


text = MAIN.read_text(encoding="utf-8")

text = replace_once(
    text,
    "TURN_PROMPT_CHUNK_SIZE = 12000",
    "TURN_PROMPT_CHUNK_SIZE = 4500",
    "safe prompt chunk size",
)

text = replace_once(
    text,
    '''        "status": pending.get("turn_status") or "pending",\n        "scene": None,\n        "scene_prompt": first_chunk,\n        "scene_prompt_chunk": first_chunk,\n''',
    '''        "status": pending.get("turn_status") or "pending",\n        "scene_prompt_chunk": first_chunk,\n''',
    "remove duplicated first prompt chunk",
)

repair_helper = '''\n\ndef _repair_pending_prompt_chunks(manager: SessionManager, session_id: str, pending: dict[str, Any]) -> dict[str, Any]:\n    chunks = pending.get("prompt_chunks")\n    if not isinstance(chunks, list) or not chunks or not all(isinstance(chunk, str) for chunk in chunks):\n        return pending\n    stored_size = int(pending.get("prompt_chunk_size") or 0)\n    needs_repair = stored_size != TURN_PROMPT_CHUNK_SIZE or any(len(chunk) > TURN_PROMPT_CHUNK_SIZE for chunk in chunks)\n    if not needs_repair:\n        return pending\n    full_prompt = "".join(chunks)\n    repaired_chunks = _split_prompt_chunks(full_prompt)\n    repaired = {\n        **pending,\n        "scene_prompt_sha256": _hash_text(full_prompt),\n        "prompt_chunk_count": len(repaired_chunks),\n        "prompt_chunk_size": TURN_PROMPT_CHUNK_SIZE,\n        "prompt_chunks": repaired_chunks,\n        "prompt_chunks_repaired_at": now_iso(),\n    }\n    manager.storage.write_json(session_id, "pending_turn.json", repaired)\n    return repaired\n'''

text = replace_once(
    text,
    '''def _load_pending_turn(manager: SessionManager, session_id: str) -> dict[str, Any]:\n    pending = manager.storage.read_json(session_id, "pending_turn.json", default={})\n    if isinstance(pending, dict):\n        pending.setdefault("session_id", session_id)\n        return pending\n    return {}\n''',
    repair_helper + '''\n\ndef _load_pending_turn(manager: SessionManager, session_id: str) -> dict[str, Any]:\n    pending = manager.storage.read_json(session_id, "pending_turn.json", default={})\n    if isinstance(pending, dict):\n        pending.setdefault("session_id", session_id)\n        return _repair_pending_prompt_chunks(manager, session_id, pending)\n    return {}\n''',
    "repair legacy pending prompt chunks",
)

text = replace_once(
    text,
    '''@app.post("/api/v1/sessions/{session_id}/turn", response_model=TurnResponse, dependencies=[Depends(require_api_key)], operation_id="processTurn")\n''',
    '''@app.post("/api/v1/sessions/{session_id}/turn", response_model=TurnResponse, response_model_exclude_none=True, dependencies=[Depends(require_api_key)], operation_id="processTurn")\n''',
    "exclude empty turn response compatibility fields",
)

text = replace_once(
    text,
    '''@app.post("/api/v1/sessions/{session_id}/advance-time", response_model=TurnResponse, dependencies=[Depends(require_api_key)], operation_id="advanceTime")\n''',
    '''@app.post("/api/v1/sessions/{session_id}/advance-time", response_model=TurnResponse, response_model_exclude_none=True, dependencies=[Depends(require_api_key)], operation_id="advanceTime")\n''',
    "exclude empty time-skip response compatibility fields",
)

MAIN.write_text(text, encoding="utf-8")
