from pathlib import Path

from app.bootstrap_preview_transport import BOOTSTRAP_STAGING_TRANSPORT_RULES
from app.novella_openapi_actions import build_openapi_actions


ROOT_DIR = Path(__file__).resolve().parents[1]
INSTRUCTIONS_PATH = ROOT_DIR / "gpt" / "custom_gpt_instructions.md"


def test_create_bootstrap_preview_action_accepts_only_bootstrap_json_body_field():
    contract = build_openapi_actions("https://example.invalid")
    schema = contract["components"]["schemas"]["BootstrapPreviewRequest"]

    assert schema["required"] == ["bootstrap_json"]
    assert set(schema["properties"]) == {"bootstrap_json"}
    assert schema["additionalProperties"] is False

    description = schema["properties"]["bootstrap_json"]["description"]
    assert "exactly one" in description.lower()
    assert "root fields" in description.lower()

    operation = contract["paths"]["/api/v1/sessions/{session_id}/bootstrap-preview"]["post"]
    assert "exactly one body field" in operation["summary"]
    assert "separate Action kwargs" in operation["summary"]


def test_bootstrap_transport_rules_forbid_root_fields_as_action_kwargs():
    rules = BOOTSTRAP_STAGING_TRANSPORT_RULES

    for marker in (
        "ровно section, value",
        "finalizeBootstrapPreview передавай только session_id",
        "scene_history и turns не отправляй",
        "Не передавай protagonist, characters, relationships, knowledge",
        "bootstrap_json",
    ):
        assert marker in rules


def test_custom_gpt_instructions_keep_strict_bootstrap_action_shapes():
    instructions = INSTRUCTIONS_PATH.read_text(encoding="utf-8")

    for marker in (
        "getBootstrapPreviewChunk",
        "saveBootstrapPart: только section, value",
        "finalizeBootstrapPreview: только session_id",
        "scene_history и turns не отправляй",
        "createBootstrapPreview: только bootstrap_json",
        "Корневые разделы не передавай как kwargs",
    ):
        assert marker in instructions
