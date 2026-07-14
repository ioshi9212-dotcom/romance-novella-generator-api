from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def replace_once(path: str, old: str, new: str) -> None:
    file_path = ROOT / path
    text = file_path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Pattern not found in {path}: {old[:100]!r}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "app/director_bible.py",
    '''                if collection_key == "planned_reveals":
                    if next_status not in _REVEAL_TRANSITIONS.get(target.get("status"), {target.get("status")}):
                        _reject(result, patch_key, item_id, f"invalid reveal transition {target.get('status')} -> {next_status}")
                        continue
                    if next_status == "revealed" and current_turn < int(target.get("earliest_turn", 0) or 0):
                        _reject(result, patch_key, item_id, "reveal attempted before earliest_turn")
                        continue
''',
    '''                if collection_key == "planned_reveals":
                    if next_status == "revealed" and current_turn < int(target.get("earliest_turn", 0) or 0):
                        _reject(result, patch_key, item_id, "reveal attempted before earliest_turn")
                        continue
                    if next_status not in _REVEAL_TRANSITIONS.get(target.get("status"), {target.get("status")}):
                        _reject(result, patch_key, item_id, f"invalid reveal transition {target.get('status')} -> {next_status}")
                        continue
''',
)

replace_once(
    "schemas/bootstrap_output.schema.json",
    '"time_anchors": {"type": "array"}',
    '"time_anchors": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "object", "additionalProperties": true}]}}',
)

replace_once(
    "tests/test_openapi_actions_contract.py",
    '''        "story_plan",
        "current_state",
''',
    '''        "story_plan",
        "director_bible",
        "current_state",
''',
)
replace_once(
    "tests/test_openapi_actions_contract.py",
    '''    assert story_plan["properties"]["status_slots"]["maxItems"] == 2

    current_state = schema["properties"]["current_state"]
''',
    '''    assert story_plan["properties"]["status_slots"]["maxItems"] == 2

    director_bible = schema["properties"]["director_bible"]
    assert director_bible["properties"]["event_queue"]["minItems"] == 3
    assert "items" in director_bible["properties"]["time_anchors"]

    current_state = schema["properties"]["current_state"]
''',
)
