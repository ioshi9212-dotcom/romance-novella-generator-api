from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from app.novella_openapi_actions import build_openapi_actions


ROOT_DIR = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = ROOT_DIR / "schemas"
INSTRUCTIONS_PATH = ROOT_DIR / "gpt" / "custom_gpt_instructions.md"



def _load_schema(filename: str) -> dict:
    return json.loads((SCHEMAS_DIR / filename).read_text(encoding="utf-8"))



def _array_paths_missing_items(node: Any, path: tuple[str, ...] = ()) -> list[str]:
    missing: list[str] = []
    if isinstance(node, dict):
        if node.get("type") == "array" and "items" not in node:
            missing.append("/".join(path) or "<root>")
        for key, value in node.items():
            missing.extend(_array_paths_missing_items(value, path + (str(key),)))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            missing.extend(_array_paths_missing_items(value, path + (str(index),)))
    return missing



def test_backend_json_schemas_are_valid_draft_2020_12():
    for filename in ("bootstrap_output.schema.json", "scene_response.schema.json"):
        Draft202012Validator.check_schema(_load_schema(filename))



def test_every_array_schema_defines_items_for_gpt_actions_import():
    contract = build_openapi_actions("https://example.invalid")
    assert _array_paths_missing_items(contract) == []



def test_bootstrap_contract_exposes_required_runtime_shape():
    schema = _load_schema("bootstrap_output.schema.json")
    assert set(schema["required"]) == {
        "protagonist",
        "characters",
        "relationships",
        "knowledge",
        "story_plan",
        "director_bible",
        "current_state",
        "npc_state",
        "future_locks",
        "continuity",
        "scene_history",
        "turns",
    }

    protagonist_required = set(schema["properties"]["protagonist"]["required"])
    assert protagonist_required == {"id", "name", "role"}

    character_schema = schema["properties"]["characters"]["additionalProperties"]
    character_required = set(character_schema["required"])
    assert {
        "id",
        "name",
        "role",
        "cast_status",
        "appearance",
        "personality",
        "goal",
        "past_short",
        "habits",
        "inner_logic",
        "behavior",
        "speech_profile",
        "life_outside_player",
        "social_triggers",
        "show_in_preview",
        "available_to_scene",
    } <= character_required
    assert character_schema["properties"]["cast_status"]["enum"] == [
        "player",
        "known_core",
        "known_support",
        "hidden_core",
        "background",
    ]
    assert set(character_schema["properties"]["behavior"]["required"]) == {
        "conflict_style",
        "care_style",
        "closeness_style",
        "touch_style",
        "stress_response",
        "rejection_response",
        "change_inertia",
        "inconvenient_pattern",
    }
    assert character_schema["properties"]["social_triggers"]["minItems"] == 2
    assert "likes_in_people" in character_schema["properties"]
    assert "relationship_triggers" in character_schema["properties"]

    story_plan = schema["properties"]["story_plan"]
    assert {
        "genre",
        "language",
        "tone",
        "setting_summary",
        "main_premise",
        "protagonist_start",
        "player_goal",
        "central_conflict",
        "central_question",
        "opening_scene_intent",
        "act_structure",
        "character_arcs",
        "relationship_focus",
        "open_threads",
        "forbidden_drift",
        "current_story_position",
        "status_slots",
    } <= set(story_plan["required"])
    assert story_plan["properties"]["status_slots"]["minItems"] == 2
    assert story_plan["properties"]["status_slots"]["maxItems"] == 2

    director_bible = schema["properties"]["director_bible"]
    assert director_bible["properties"]["event_queue"]["minItems"] == 3
    assert "items" in director_bible["properties"]["time_anchors"]

    current_state = schema["properties"]["current_state"]
    assert "status" in current_state["required"]
    assert current_state["properties"]["turn_number"]["const"] == 0
    assert current_state["properties"]["last_player_input"]["maxLength"] == 0



def test_scene_contract_requires_complete_visible_scene_and_safety():
    schema = _load_schema("scene_response.schema.json")
    assert {
        "response_version",
        "player_input",
        "scene",
        "proposed_updates",
        "safety_checks",
        "summary",
        "important_facts",
        "witnesses",
    } <= set(schema["required"])

    scene = schema["properties"]["scene"]
    assert set(scene["required"]) == {
        "header",
        "body",
        "player_options",
        "status_panel",
        "relationships_panel",
        "rendered_text",
    }
    assert scene["properties"]["body"]["minLength"] == 500
    assert scene["properties"]["rendered_text"]["minLength"] == 1000

    options = scene["properties"]["player_options"]["properties"]
    for key in ("actions", "dialogue", "thoughts"):
        assert options[key]["minItems"] == 3
        assert options[key]["maxItems"] == 3
        assert options[key]["items"]["minLength"] == 1

    safety = schema["properties"]["safety_checks"]
    required_safety = {
        "used_only_loaded_characters",
        "respected_knowledge_boundaries",
        "no_hidden_future_reveal",
        "no_major_player_character_choice",
        "respected_player_input_order",
        "showed_only_scene_relationships",
        "header_has_no_focus_or_active_list",
    }
    assert set(safety["required"]) == required_safety
    for key in required_safety:
        assert safety["properties"][key]["const"] is True



def test_openapi_actions_use_strict_components_and_api_key():
    contract = build_openapi_actions("https://example.invalid")
    schemas = contract["components"]["schemas"]

    assert contract["security"] == [{"ApiKeyAuth": []}]
    assert contract["components"]["securitySchemes"]["ApiKeyAuth"] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
    }
    assert contract["paths"]["/health"]["get"]["security"] == []

    assert "player_input" in schemas["SceneResponse"]["required"]
    apply_request = schemas["ApplyTurnResultRequest"]
    assert set(apply_request["required"]) == {"turn_id", "scene_response"}
    assert apply_request["properties"]["scene_response"] == {
        "$ref": "#/components/schemas/SceneResponse"
    }

    turn_response_ref = contract["paths"]["/api/v1/sessions/{session_id}/turn"][
        "post"
    ]["responses"]["200"]["content"]["application/json"]["schema"]
    assert turn_response_ref == {"$ref": "#/components/schemas/TurnResponse"}

    preview_request_ref = contract["paths"][
        "/api/v1/sessions/{session_id}/bootstrap-preview"
    ]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert preview_request_ref == {
        "$ref": "#/components/schemas/BootstrapPreviewRequest"
    }
    preview_request = schemas["BootstrapPreviewRequest"]
    assert set(preview_request["properties"]) == {"bootstrap_json"}
    assert preview_request["required"] == ["bootstrap_json"]
    assert preview_request["additionalProperties"] is False
    assert "mode" not in preview_request["properties"]



def test_custom_gpt_instructions_fit_editor_limit_and_keep_critical_flow():
    instructions = INSTRUCTIONS_PATH.read_text(encoding="utf-8")

    assert len(instructions) <= 8000
    for marker in (
        "processTurn",
        "getTurnPromptChunk",
        "applyTurnResult",
        "turn_id",
        "PREVIEW GATE",
        "SCENE_RESPONSE",
        "safety_checks",
        "no_major_player_character_choice",
        "new_or_updated_characters",
        "В POV не игрока",
        "mode разрешён только в createSession и processTurn",
        "createBootstrapPreview только с bootstrap_json, без mode",
        "hidden_core",
        "полной скрытой карточкой",
    ):
        assert marker in instructions
