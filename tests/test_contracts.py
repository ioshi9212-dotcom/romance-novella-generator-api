from __future__ import annotations

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
    assert "getStartQuestionnaire" not in operation_ids


def test_create_session_explains_that_questionnaire_is_instruction_owned():
    document = yaml.safe_load((ROOT / "openapi-actions.yaml").read_text(encoding="utf-8"))
    operation = document["paths"]["/v1/sessions"]["post"]
    assert "ask its questionnaire itself" in operation["description"]
    assert "getStartQuestionnaire" in operation["description"]


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


def test_all_mutating_actions_disable_consequential_confirmation():
    document = yaml.safe_load((ROOT / "openapi-actions.yaml").read_text(encoding="utf-8"))
    for path in document["paths"].values():
        for method, operation in path.items():
            if method in {"post", "put", "patch", "delete"}:
                assert operation["x-openai-isConsequential"] is False
