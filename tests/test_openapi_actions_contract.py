from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from app.novella_openapi_actions import build_openapi_actions


SCHEMAS_DIR = Path(__file__).resolve().parents[1] / "schemas"


def _load_schema(filename: str) -> dict:
    return json.loads((SCHEMAS_DIR / filename).read_text(encoding="utf-8"))


def test_backend_json_schemas_are_valid_draft_2020_12():
    for filename in ("bootstrap_output.schema.json", "scene_response.schema.json"):
        Draft202012Validator.check_schema(_load_schema(filename))


def test_bootstrap_contract_exposes_required_runtime_shape():
    schema = _load_schema("bootstrap_output.schema.json")
    assert set(schema["required"]) == {
        "protagonist",
        "characters",
        "relationships",
        "knowledge",
        "story_plan",
        "current_state",
        "npc_state",
        "future_locks",
        "continuity",
        "scene_history",
        "turns",
    }

    protagonist_required = set(schema["properties"]["protagonist"]["required"])
    assert protagonist_required == {"id", "name", "role"}

    character_required = set(
        schema["properties"]["characters"]["additionalProperties"]["required"]
    )
    assert {
        "id",
        "name",
        "role",
        "appearance",
        "personality",
        "goal",
        "past_short",
        "habits",
        "likes_in_people",
        "dislikes_in_people",
        "relationship_triggers",
    } <= character_required

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
