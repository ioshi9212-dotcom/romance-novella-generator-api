from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "tests" / "test_openapi_actions_contract.py"
text = TARGET.read_text(encoding="utf-8")
old = '''    preview_request = schemas["BootstrapPreviewRequest"]
    assert set(preview_request["properties"]) == {
        "bootstrap_json",
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
    assert preview_request["required"] == ["bootstrap_json"]
    assert preview_request["additionalProperties"] is False
    assert "mode" not in preview_request["properties"]
'''
new = '''    preview_request = schemas["BootstrapPreviewRequest"]
    assert set(preview_request["properties"]) == {"bootstrap_json"}
    assert preview_request["required"] == ["bootstrap_json"]
    assert preview_request["additionalProperties"] is False
    assert "mode" not in preview_request["properties"]
    description = preview_request["properties"]["bootstrap_json"]["description"]
    assert "exactly one field" in description
    assert "never pass root fields" in description
'''
if text.count(old) != 1:
    raise RuntimeError("Expected exactly one legacy bootstrap preview contract block")
TARGET.write_text(text.replace(old, new, 1), encoding="utf-8")

for path in [
    ROOT / "scripts" / "update_bootstrap_preview_contract_test.py",
    ROOT / ".github" / "workflows" / "update-bootstrap-preview-contract-test.yml",
]:
    if path.exists():
        path.unlink()
