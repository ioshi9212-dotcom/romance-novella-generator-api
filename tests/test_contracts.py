from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_action_schema_is_valid_and_has_expected_operations():
    document = yaml.safe_load((ROOT / "openapi-actions.yaml").read_text(encoding="utf-8"))
    assert document["openapi"] == "3.0.3"
    operation_ids = {
        operation["operationId"]
        for path in document["paths"].values()
        for method, operation in path.items()
        if method in {"get", "post", "put", "patch", "delete"}
    }
    assert operation_ids == {
        "createSession",
        "listSessions",
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


def test_all_mutating_actions_disable_consequential_confirmation():
    document = yaml.safe_load((ROOT / "openapi-actions.yaml").read_text(encoding="utf-8"))
    for path in document["paths"].values():
        for method, operation in path.items():
            if method in {"post", "put", "patch", "delete"}:
                assert operation["x-openai-isConsequential"] is False
