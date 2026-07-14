from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def replace_once(path: str, old: str, new: str) -> None:
    file_path = ROOT / path
    text = file_path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"anchor missing in {path}: {old[:120]!r}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "app/time_skip.py",
    '''def _pending_events(bible: dict[str, Any]) -> list[dict[str, Any]]:
    result = [
        item
        for item in bible.get("event_queue", [])
        if isinstance(item, dict) and item.get("status") in _EVENT_STATUSES
    ]
''',
    '''def _pending_events(bible: dict[str, Any], current_turn: int) -> list[dict[str, Any]]:
    next_turn = current_turn + 1
    result = [
        item
        for item in bible.get("event_queue", [])
        if isinstance(item, dict)
        and item.get("status") in _EVENT_STATUSES
        and _integer(item.get("earliest_turn"), 0) <= next_turn
    ]
''',
)
replace_once(
    "app/time_skip.py",
    "    pending_events = _pending_events(bible)\n",
    "    pending_events = _pending_events(bible, turn_number)\n",
)
replace_once(
    "app/time_skip.py",
    '''    elapsed = result.get("elapsed") if isinstance(result.get("elapsed"), dict) else {}
    if request.get("mode") == "duration":
        if elapsed.get("unit") != request.get("unit") or _integer(elapsed.get("amount"), 0) != _integer(request.get("amount"), 0):
            errors.append("time_skip_result.elapsed must match the requested duration")
''',
    '''    elapsed = result.get("elapsed") if isinstance(result.get("elapsed"), dict) else {}
    expected_unit = request.get("unit")
    expected_amount = _integer(request.get("amount"), 0)
    if expected_unit and expected_amount > 0:
        if elapsed.get("unit") != expected_unit or _integer(elapsed.get("amount"), 0) != expected_amount:
            errors.append("time_skip_result.elapsed must match the selected skip duration")
''',
)
replace_once(
    "app/time_skip.py",
    '''    control = state_patch.get("time_skip_control") if isinstance(state_patch.get("time_skip_control"), dict) else None
    if control is None or not isinstance(control.get("allowed"), bool):
        errors.append("time skip scene_state_patch.time_skip_control.allowed is required")
''',
    '''    control = state_patch.get("time_skip_control") if isinstance(state_patch.get("time_skip_control"), dict) else None
    if control is None or not isinstance(control.get("allowed"), bool):
        errors.append("time skip scene_state_patch.time_skip_control.allowed is required")
    elif control.get("allowed") is not False:
        errors.append("time skip must close time_skip_control until the new scene reaches another natural pause")
''',
)
replace_once(
    "app/main.py",
    '''    if existing_pending.get("status") == "pending":
        same_input = existing_pending.get("player_input_sha256") == _hash_text(player_input)
''',
    '''    if existing_pending.get("status") == "pending":
        if existing_pending.get("turn_kind", "normal") != "normal":
            raise HTTPException(status_code=409, detail="A time-skip turn is pending. Apply it before sending a normal turn.")
        same_input = existing_pending.get("player_input_sha256") == _hash_text(player_input)
''',
)
replace_once(
    "app/main.py",
    '''        if same_request and same_turn and existing_pending.get("turn_kind") == "time_skip":
            if isinstance(existing_pending.get("prompt_chunks"), list) and existing_pending.get("prompt_chunks"):
                return _pending_turn_response(existing_pending, session_id)
        raise HTTPException(status_code=409, detail="Another turn is still pending. Apply it before advancing time.")
''',
    '''        if same_request and same_turn and existing_pending.get("turn_kind") == "time_skip":
            if isinstance(existing_pending.get("prompt_chunks"), list) and existing_pending.get("prompt_chunks"):
                return _pending_turn_response(existing_pending, session_id)
            repaired = process_time_skip_gpt_actions(
                bundle,
                player_input,
                skip_mode=request.skip_mode,
                unit=request.unit,
                amount=request.amount,
            )
            repaired_pending = _store_prompt_chunks(
                manager,
                session_id,
                existing_pending,
                repaired["scene_prompt"],
                turn_status=repaired["status"],
                turn_diagnostics=repaired["diagnostics"],
            )
            return _pending_turn_response(repaired_pending, session_id)
        raise HTTPException(status_code=409, detail="Another turn is still pending. Apply it before advancing time.")
''',
)
replace_once(
    "app/main.py",
    'raise HTTPException(status_code=409, detail="Missing or mismatched pending turn_id. Call processTurn again.")',
    'raise HTTPException(status_code=409, detail="Missing or mismatched pending turn_id. Call processTurn or advanceTime again.")',
)
