from __future__ import annotations

import json
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"Expected patch anchor not found in {path}: {old[:100]!r}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


# app/main.py
replace_once(
    "app/main.py",
    "from app.config import get_settings\n",
    "from app.config import get_settings\nfrom app.directional_relationships import apply_directional_relationship_patches, prepare_directional_relationships, validate_directional_relationships\n",
)
replace_once(
    "app/main.py",
    "    errors = validate_bootstrap_result(normalized_bootstrap)\n    if errors:\n",
    "    errors = validate_bootstrap_result(normalized_bootstrap)\n    prepare_directional_relationships(normalized_bootstrap)\n    errors.extend(validate_directional_relationships(normalized_bootstrap))\n    if errors:\n",
)
replace_once(
    "app/main.py",
    "            result = apply_npc_state_patches(\n                manager.storage,\n                session_id,\n                normalized_scene_response,\n                bundle,\n                result,\n            )\n            _mark_pending_turn_applied(manager, session_id, pending)\n",
    "            result = apply_npc_state_patches(\n                manager.storage,\n                session_id,\n                normalized_scene_response,\n                bundle,\n                result,\n            )\n            result = apply_directional_relationship_patches(\n                manager.storage,\n                session_id,\n                normalized_scene_response,\n                bundle,\n                result,\n            )\n            _mark_pending_turn_applied(manager, session_id, pending)\n",
)

# app/session_manager.py
replace_once(
    "app/session_manager.py",
    "from app.config import get_settings\n",
    "from app.config import get_settings\nfrom app.directional_relationships import BOOTSTRAP_DIRECTION_RULES, append_directional_preview, prepare_directional_relationships\n",
)
replace_once(
    "app/session_manager.py",
    "        prompt = build_bootstrap_prompt(user_request)\n",
    "        prompt = build_bootstrap_prompt(user_request) + \"\\n\\n\" + BOOTSTRAP_DIRECTION_RULES\n",
)
replace_once(
    "app/session_manager.py",
    "        prepare_bootstrap_cast(bootstrap_json)\n        prepare_npc_runtime_map(bootstrap_json)\n",
    "        prepare_bootstrap_cast(bootstrap_json)\n        prepare_directional_relationships(bootstrap_json)\n        prepare_npc_runtime_map(bootstrap_json)\n",
)
# Same sequence occurs twice; patch the second occurrence too.
replace_once(
    "app/session_manager.py",
    "        prepare_bootstrap_cast(bootstrap_json)\n        prepare_npc_runtime_map(bootstrap_json)\n",
    "        prepare_bootstrap_cast(bootstrap_json)\n        prepare_directional_relationships(bootstrap_json)\n        prepare_npc_runtime_map(bootstrap_json)\n",
)
replace_once(
    "app/session_manager.py",
    "        preview = build_setup_preview(bootstrap_json)\n",
    "        preview = append_directional_preview(build_setup_preview(bootstrap_json), bootstrap_json)\n",
)
replace_once(
    "app/session_manager.py",
    "                \"npc_runtime_enabled\": True,\n",
    "                \"npc_runtime_enabled\": True,\n                \"directional_relationships_enabled\": True,\n",
)

# app/scene_contract_builder.py
replace_once(
    "app/scene_contract_builder.py",
    "from app.npc_runtime import compact_npc_runtime_entry\n",
    "from app.npc_runtime import compact_npc_runtime_entry\nfrom app.relationship_state import normalize_relationship_pair\n",
)
replace_once(
    "app/scene_contract_builder.py",
    "                content = relationships[relationship_id]\n",
    "                content = normalize_relationship_pair(relationships[relationship_id], characters, str(player_id))\n",
)
replace_once(
    "app/scene_contract_builder.py",
    "                content = _baseline_relationship_content(characters, character_a, character_b)\n",
    "                content = normalize_relationship_pair(_baseline_relationship_content(characters, character_a, character_b), characters, str(player_id))\n",
)
replace_once(
    "app/scene_contract_builder.py",
    "            \"state_update_mode\": \"propose_patch_only\",\n",
    "            \"state_update_mode\": \"propose_patch_only\",\n            \"directional_relationship_rule\": \"Update only the side whose perception/need/feeling changed. Use from_character_id, to_character_id and direction_patch; never mirror one person's change onto the other.\",\n",
)

# Compact Custom GPT instruction.
replace_once(
    "gpt/custom_gpt_instructions.md",
    "relationship_patch: pair_id,change_type,entry,reason,source_in_scene. knowledge_patch/npc_state_patch: character_id,reason,source_in_scene.\n",
    "relationship_patch: pair_id,change_type,entry,reason,source_in_scene. Для одной стороны: from_character_id,to_character_id,direction_patch; не зеркаль изменения на второго. knowledge_patch/npc_state_patch: character_id,reason,source_in_scene.\n",
)

# Bootstrap schema: expose optional canonical directional blocks while old payloads remain accepted.
bootstrap_path = Path("schemas/bootstrap_output.schema.json")
bootstrap = json.loads(bootstrap_path.read_text(encoding="utf-8"))
relationship_schema = bootstrap["properties"]["relationships"]["additionalProperties"]
relationship_properties = relationship_schema.setdefault("properties", {})
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
relationship_properties["shared"] = {
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
relationship_properties["a_to_b"] = direction_schema
relationship_properties["b_to_a"] = direction_schema
bootstrap_path.write_text(json.dumps(bootstrap, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# Scene response schema: expose directional patch fields.
scene_path = Path("schemas/scene_response.schema.json")
scene_schema = json.loads(scene_path.read_text(encoding="utf-8"))
patch_properties = scene_schema["properties"]["proposed_updates"]["properties"]["relationship_patches"]["items"]["properties"]
patch_properties["from_character_id"] = {"type": "string", "minLength": 1, "maxLength": 128, "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"}
patch_properties["to_character_id"] = {"type": "string", "minLength": 1, "maxLength": 128, "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"}
direction_patch_schema = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "scores": {"type": "object", "additionalProperties": {"type": "number", "minimum": 0, "maximum": 100}},
        **{key: {"type": "number", "minimum": 0, "maximum": 100} for key in score_properties},
        **{key: {"type": "string", "minLength": 1} for key in ["current_view", "current_need", "current_expectation", "access_boundary", "interpretation_bias", "unresolved_emotion", "care_risk"]},
        "add_unresolved_grievances": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "resolve_unresolved_grievances": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "add_wrong_beliefs": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "remove_wrong_beliefs": {"type": "array", "items": {"type": "string", "minLength": 1}},
    },
}
patch_properties["direction_patch"] = direction_patch_schema
patch_properties["a_to_b"] = direction_patch_schema
patch_properties["b_to_a"] = direction_patch_schema
patch_properties["shared_patch"] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "status": {"type": "string", "minLength": 1},
        "add_shared_history": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "object"}]}},
        "add_unresolved_threads": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "resolve_unresolved_threads": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "last_major_event": {"type": ["string", "object", "null"]},
    },
}
scene_path.write_text(json.dumps(scene_schema, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
