from pathlib import Path

from app.bootstrap_preview_transport import BOOTSTRAP_PREVIEW_TRANSPORT_RULES
from app.novella_openapi_actions import build_openapi_actions


ROOT_DIR = Path(__file__).resolve().parents[1]
INSTRUCTIONS_PATH = ROOT_DIR / "gpt" / "custom_gpt_instructions.md"


def test_single_bootstrap_preview_is_the_only_setup_write_action():
    contract = build_openapi_actions("https://example.invalid")
    paths = contract["paths"]

    assert "BootstrapPreviewRequest" in contract["components"]["schemas"]
    assert "/api/v1/sessions/{session_id}/bootstrap-preview" in paths
    assert "/api/v1/sessions/{session_id}/bootstrap-part" not in paths
    assert "/api/v1/sessions/{session_id}/bootstrap-preview-finalize" not in paths


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


def test_bootstrap_transport_has_one_unambiguous_json_argument():
    contract = build_openapi_actions("https://example.invalid")
    schema = contract["components"]["schemas"]["BootstrapPreviewRequest"]

    assert schema["required"] == ["bootstrap_json"]
    assert set(schema["properties"]) == {"bootstrap_json"}
    assert schema["additionalProperties"] is False
    assert schema["properties"]["bootstrap_json"]["type"] == "object"

    rules = BOOTSTRAP_PREVIEW_TRANSPORT_RULES
    for marker in (
        "единственным полем bootstrap_json",
        "Не разворачивай protagonist, characters, story_plan",
        "scene_history и turns передай пустыми списками",
        "getBootstrapPreviewChunk",
    ):
        assert marker in rules


def test_custom_gpt_instructions_keep_single_preview_action_shape():
    instructions = INSTRUCTIONS_PATH.read_text(encoding="utf-8")

    for marker in (
        "createSession(raw_start_text=",
        "raw_start_text всегда непустая JSON-строка",
        "createBootstrapPreview: передай один bootstrap_json",
        "getBootstrapPreviewChunk",
        "future_locks.hidden_character_seeds",
    ):
        assert marker in instructions
    assert "saveBootstrapPart" not in instructions
    assert "finalizeBootstrapPreview" not in instructions
