from pathlib import Path
import json
import subprocess


original = subprocess.check_output(
    ["git", "show", "origin/main:schemas/bootstrap_output.schema.json"],
    text=True,
    encoding="utf-8",
)

relationship_start = original.index('    "relationships": {')
needle = '          "open_threads": {"type": "array", "items": {"type": "string"}}'
position = original.index(needle, relationship_start)

score_properties = {
    key: {"type": "number", "minimum": 0, "maximum": 100}
    for key in [
        "trust", "attachment", "attraction", "resentment", "respect", "fear",
        "jealousy", "dependency", "curiosity", "protectiveness",
    ]
}
direction_schema = {
    "type": "object",
    "additionalProperties": True,
    "properties": {
        "source_character_id": {"type": "string", "minLength": 1},
        "target_character_id": {"type": "string", "minLength": 1},
        "scores": {"type": "object", "additionalProperties": False, "properties": score_properties},
        "summary": {"type": "string", "minLength": 1},
        "current_assumption": {"type": "string", "minLength": 1},
        "current_need": {"type": "string", "minLength": 1},
        "access_expectation": {"type": "string", "minLength": 1},
        "unresolved_grievance": {"type": "string", "minLength": 1},
        "history": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
    },
    "description": "Independent direction of the relationship. Never mirror automatically to the opposite direction.",
}
shared_schema = {
    "type": "object",
    "additionalProperties": True,
    "properties": {
        "status": {"type": "string", "minLength": 1},
        "scores": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "tension": {"type": "number", "minimum": 0, "maximum": 100},
                "closeness": {"type": "number", "minimum": 0, "maximum": 100},
                "conflict_pressure": {"type": "number", "minimum": 0, "maximum": 100},
            },
        },
        "shared_history": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "object"}]}},
        "recent_changes": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "object"}]}},
        "open_threads": {"type": "array", "items": {"type": "string", "minLength": 1}},
    },
    "description": "Only facts and pressure shared by the pair; feelings remain in a_to_b/b_to_a.",
}

replacement = "\n".join([
    needle + ",",
    '          "relationship_version": ' + json.dumps({"type": "string", "enum": ["directed.v1"]}, ensure_ascii=False, separators=(",", ":")) + ",",
    '          "shared": ' + json.dumps(shared_schema, ensure_ascii=False, separators=(",", ":")) + ",",
    '          "a_to_b": ' + json.dumps(direction_schema, ensure_ascii=False, separators=(",", ":")) + ",",
    '          "b_to_a": ' + json.dumps(direction_schema, ensure_ascii=False, separators=(",", ":")),
])

result = original[:position] + replacement + original[position + len(needle):]
Path("schemas/bootstrap_output.schema.json").write_text(result, encoding="utf-8")
