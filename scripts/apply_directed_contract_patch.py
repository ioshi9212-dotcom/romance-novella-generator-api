from pathlib import Path
import json


# Fix relationship defaults so the non-player role drives both starting directions.
state_path = Path("app/relationship_state.py")
state_text = state_path.read_text(encoding="utf-8")
replacements = [
    (
        "_direction_score_defaults(role_b, source_is_player=character_a == protagonist_id)",
        "_direction_score_defaults(role_b if character_a == protagonist_id else role_a, source_is_player=character_a == protagonist_id)",
    ),
    (
        "_direction_score_defaults(role_a or role_b, source_is_player=character_b == protagonist_id)",
        "_direction_score_defaults(role_a if character_b == protagonist_id else role_b, source_is_player=character_b == protagonist_id)",
    ),
]
for old, new in replacements:
    if old in state_text:
        state_text = state_text.replace(old, new, 1)
    elif new not in state_text:
        raise SystemExit(f"Expected relationship default expression not found: {old}")
state_path.write_text(state_text, encoding="utf-8")


# Expose directed starting relationship fields to BootstrapPayload.
bootstrap_path = Path("schemas/bootstrap_output.schema.json")
bootstrap = json.loads(bootstrap_path.read_text(encoding="utf-8"))
relation_schema = bootstrap["properties"]["relationships"]["additionalProperties"]
relation_props = relation_schema.setdefault("properties", {})
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
relation_props["relationship_version"] = {"type": "string", "enum": ["directed.v1"]}
relation_props["shared"] = {
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
relation_props["a_to_b"] = direction_schema
relation_props["b_to_a"] = direction_schema
bootstrap_path.write_text(json.dumps(bootstrap, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# Expose direction and player-agency evidence on scene relationship patches.
scene_path = Path("schemas/scene_response.schema.json")
scene = json.loads(scene_path.read_text(encoding="utf-8"))
patch_schema = scene["properties"]["proposed_updates"]["properties"]["relationship_patches"]["items"]
patch_props = patch_schema.setdefault("properties", {})
character_id_schema = {
    "type": "string",
    "minLength": 1,
    "maxLength": 128,
    "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$",
}
patch_props.update({
    "scope": {
        "type": "string",
        "enum": ["directed", "shared", "legacy_symmetric"],
        "description": "directed changes one person's stance; shared changes pair-level tension/history.",
    },
    "source_character_id": character_id_schema,
    "target_character_id": character_id_schema,
    "player_input_evidence": {
        "type": "string",
        "minLength": 1,
        "description": "Exact excerpt of player_input required when source_character_id is the player character.",
    },
    "attraction": {"type": "number", "minimum": 0, "maximum": 100},
    "resentment": {"type": "number", "minimum": 0, "maximum": 100},
    "jealousy": {"type": "number", "minimum": 0, "maximum": 100},
    "dependency": {"type": "number", "minimum": 0, "maximum": 100},
    "protectiveness": {"type": "number", "minimum": 0, "maximum": 100},
    "closeness": {"type": "number", "minimum": 0, "maximum": 100},
    "conflict_pressure": {"type": "number", "minimum": 0, "maximum": 100},
    "status": {"type": "string", "minLength": 1},
    "summary": {"type": "string", "minLength": 1},
    "current_assumption": {"type": "string", "minLength": 1},
    "current_need": {"type": "string", "minLength": 1},
    "access_expectation": {"type": "string", "minLength": 1},
    "unresolved_grievance": {"type": "string", "minLength": 1},
    "view": {"type": "object", "additionalProperties": True},
    "add_open_threads": {"type": "array", "items": {"type": "string", "minLength": 1}},
})
scene_path.write_text(json.dumps(scene, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
