from __future__ import annotations

import json
from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_action_schema_is_valid_and_has_expected_operations():
    document = yaml.safe_load((ROOT / "openapi-actions.yaml").read_text(encoding="utf-8"))
    assert document["openapi"] == "3.1.0"
    operation_ids = {
        operation["operationId"]
        for path in document["paths"].values()
        for method, operation in path.items()
        if method in {"get", "post", "put", "patch", "delete"}
    }
    assert operation_ids == {
        "getStartQuestionnaire",
        "createSession",
        "listSessions",
        "resumeSession",
        "getSessionStatus",
        "saveQuestionnaire",
        "saveBootstrapPart",
        "validateBootstrap",
        "confirmBootstrap",
        "prepareTurn",
        "getTurnChunk",
        "commitTurn",
        "abortTurn",
    }
def test_start_questionnaire_is_a_real_compatibility_action():
    document = yaml.safe_load((ROOT / "openapi-actions.yaml").read_text(encoding="utf-8"))
    operation = document["paths"]["/api/v1/start-questionnaire"]["get"]
    assert operation["operationId"] == "getStartQuestionnaire"
    assert "show" in operation["description"]

    create_operation = document["paths"]["/v1/sessions"]["post"]
    assert "same operation" in create_operation["description"]
    assert "never ask the user to repeat" in create_operation["description"]


def test_canonical_create_contract_requires_visible_questionnaire_answers():
    document = yaml.safe_load((ROOT / "openapi-actions.yaml").read_text(encoding="utf-8"))
    create_request = document["components"]["schemas"]["CreateSessionRequest"]
    assert "raw_answers" in create_request["required"]
    assert create_request["properties"]["raw_answers"]["maxLength"] == 100000
    assert "never summarize" in create_request["properties"]["raw_answers"]["description"]


def test_all_action_operation_descriptions_fit_chatgpt_limit():
    document = yaml.safe_load((ROOT / "openapi-actions.yaml").read_text(encoding="utf-8"))
    for path_item in document["paths"].values():
        for method, operation in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            description = operation.get("description", "")
            assert len(description) <= 300, (
                f'{operation["operationId"]} description has {len(description)} characters'
            )


def test_all_path_parameters_are_inline_and_named_for_gpt_actions():
    document = yaml.safe_load((ROOT / "openapi-actions.yaml").read_text(encoding="utf-8"))
    for path_template, path_item in document["paths"].items():
        placeholder_names = set(re.findall(r"{([^}]+)}", path_template))
        for method, operation in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            parameters = operation.get("parameters", [])
            assert all("$ref" not in parameter for parameter in parameters)
            parameters_by_name = {parameter.get("name"): parameter for parameter in parameters}
            for placeholder_name in placeholder_names:
                parameter = parameters_by_name[placeholder_name]
                assert isinstance(parameter["name"], str)
                assert parameter["in"] == "path"
                assert parameter["required"] is True


def test_bootstrap_content_is_exposed_as_json_text_for_gpt_actions():
    document = yaml.safe_load((ROOT / "openapi-actions.yaml").read_text(encoding="utf-8"))
    content_schema = document["components"]["schemas"]["BootstrapPartRequest"]["properties"]["content"]
    assert content_schema["type"] == "string"
    assert "JSON object" in content_schema["description"]


def test_questionnaire_contract_accepts_long_answers_and_recovery_shapes():
    document = yaml.safe_load((ROOT / "openapi-actions.yaml").read_text(encoding="utf-8"))
    questionnaire = document["components"]["schemas"]["QuestionnaireRequest"]["properties"]
    assert questionnaire["raw_answers"]["maxLength"] == 100000
    assert set(questionnaire["normalized"]["type"]) == {"object", "string"}
    assert set(questionnaire["unknown_fields"]["type"]) == {"array", "string"}
    assert "director" in questionnaire["unknown_fields"]["description"]


def test_bootstrap_contract_exposes_merge_and_director_repairs():
    document = yaml.safe_load((ROOT / "openapi-actions.yaml").read_text(encoding="utf-8"))
    bootstrap_part = document["components"]["schemas"]["BootstrapPartRequest"]
    assert bootstrap_part["properties"]["merge"]["type"] == "boolean"
    validation = document["components"]["schemas"]["BootstrapValidation"]
    assert "director_repairs" in validation["required"]
    assert "user_questions" in validation["required"]
    assert validation["properties"]["next_action"]["enum"] == [
        "show_review",
        "repair_bootstrap",
        "ask_user",
    ]


def test_turn_contract_exposes_complete_context_and_eight_chunks():
    document = yaml.safe_load((ROOT / "openapi-actions.yaml").read_text(encoding="utf-8"))
    prepared = document["components"]["schemas"]["PreparedTurn"]
    assert "context_complete" in prepared["required"]
    assert "included_sections" in prepared["required"]
    assert "audit_due" in prepared["required"]
    assert prepared["properties"]["total_chunks"]["maximum"] == 8
    chunk_parameter = document["paths"][
        "/v1/sessions/{session_id}/turns/{turn_id}/chunks/{chunk_index}"
    ]["get"]["parameters"][-1]
    assert chunk_parameter["schema"]["maximum"] == 7

    packet_schema = json.loads(
        (ROOT / "schemas" / "scene_packet.schema.json").read_text(encoding="utf-8")
    )
    assert packet_schema["properties"]["chunks"]["maxItems"] == 8


def test_custom_gpt_instruction_fits_limit_and_preserves_pov_presence_policy():
    instruction = (ROOT / "gpt" / "custom_gpt_instructions.md").read_text(encoding="utf-8")
    assert len(instruction) <= 8000
    assert "Do not make the POV passive furniture" in instruction
    assert "brief ordinary replies" in instruction
    assert "context_complete: true" in instruction
    assert "call\n`getStartQuestionnaire`" in instruction
    assert "Do not create\na session yet" in instruction
    assert "Never create an empty canonical session" in instruction
    assert "never ask the user to repeat them" in instruction
    assert "continuity_audit_required" not in instruction


def test_all_mutating_actions_disable_consequential_confirmation():
    document = yaml.safe_load((ROOT / "openapi-actions.yaml").read_text(encoding="utf-8"))
    for path in document["paths"].values():
        for method, operation in path.items():
            if method in {"post", "put", "patch", "delete"}:
                assert operation["x-openai-isConsequential"] is False
