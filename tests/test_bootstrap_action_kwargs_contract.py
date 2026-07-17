from pathlib import Path

from app.bootstrap_preview_transport import BOOTSTRAP_STAGING_TRANSPORT_RULES
from app.novella_openapi_actions import build_openapi_actions


ROOT_DIR = Path(__file__).resolve().parents[1]
INSTRUCTIONS_PATH = ROOT_DIR / "gpt" / "custom_gpt_instructions.md"


def test_legacy_full_bootstrap_preview_is_not_exposed_to_custom_gpt_actions():
    contract = build_openapi_actions("https://example.invalid")
    assert "BootstrapPreviewRequest" not in contract["components"]["schemas"]
    assert "/api/v1/sessions/{session_id}/bootstrap-preview" not in contract["paths"]
    assert "/api/v1/sessions/{session_id}/bootstrap-part" in contract["paths"]
    assert "/api/v1/sessions/{session_id}/bootstrap-preview-finalize" in contract["paths"]


def test_create_session_action_keeps_the_questionnaire_in_one_string_field():
    contract = build_openapi_actions("https://example.invalid")
    schema = contract["components"]["schemas"]["CreateSessionRequest"]

    assert schema["required"] == ["raw_start_text"]
    assert set(schema["properties"]) == {"raw_start_text", "mode"}
    assert schema["additionalProperties"] is False
    assert schema["properties"]["raw_start_text"]["type"] == "string"
    assert schema["properties"]["raw_start_text"]["minLength"] == 1

    operation = contract["paths"]["/api/v1/sessions"]["post"]
    assert "exactly raw_start_text" in operation["summary"]
    assert "Never split" in operation["summary"]


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
    assert "story_plan, current_state и придуманный GPT director_bible" in rules
    assert "Director_bible не пустой технический раздел" in rules


def test_custom_gpt_instructions_keep_strict_bootstrap_action_shapes():
    instructions = INSTRUCTIONS_PATH.read_text(encoding="utf-8")

    for marker in (
        "getBootstrapPreviewChunk",
        "saveBootstrapPart: только section, value",
        "finalizeBootstrapPreview: только session_id",
        "scene_history и turns не отправляй",
        "Корневые разделы не передавай как kwargs",
        "director_bible с лором/крючками",
    ):
        assert marker in instructions
