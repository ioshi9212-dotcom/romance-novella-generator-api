from __future__ import annotations

import json
import subprocess
from pathlib import Path


original = subprocess.check_output(
    ["git", "show", "origin/main:schemas/bootstrap_output.schema.json"],
    text=True,
    encoding="utf-8",
)

score_properties = {
    key: {"type": "number", "minimum": 0, "maximum": 100}
    for key in ["trust", "attachment", "attraction", "respect", "resentment", "fear", "jealousy", "dependency", "protectiveness"]
}
direction_schema = {
    "type": "object",
    "additionalProperties": True,
    "properties": {
        "scores": {"type": "object", "additionalProperties": False, "properties": score_properties},
        "current_view": {"type": "string", "minLength": 1},
        "current_need": {"type": "string", "minLength": 1},
        "current_expectation": {"type": "string", "minLength": 1},
        "access_boundary": {"type": "string", "minLength": 1},
        "interpretation_bias": {"type": "string", "minLength": 1},
        "unresolved_emotion": {"type": "string", "minLength": 1},
        "unresolved_grievances": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "wrong_beliefs": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "care_risk": {"type": "string", "minLength": 1},
    },
}
shared_schema = {
    "type": "object",
    "additionalProperties": True,
    "properties": {
        "type": {"type": "string", "minLength": 1},
        "status": {"type": "string", "minLength": 1},
        "shared_history": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "object"}]}},
        "unresolved_threads": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "recent_changes": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "object"}]}},
        "last_major_event": {"type": ["string", "object", "null"]},
    },
}

compact = lambda value: json.dumps(value, ensure_ascii=False, separators=(",", ":"))
anchor = '          "b_view_of_a": {"type": "object"},\n          "shared_history":'
insert = (
    '          "b_view_of_a": {"type": "object"},\n'
    f'          "shared": {compact(shared_schema)},\n'
    f'          "a_to_b": {compact(direction_schema)},\n'
    f'          "b_to_a": {compact(direction_schema)},\n'
    '          "shared_history":'
)
if anchor not in original:
    raise RuntimeError("relationship schema anchor not found in main")
updated = original.replace(anchor, insert, 1)
Path("schemas/bootstrap_output.schema.json").write_text(updated, encoding="utf-8")
