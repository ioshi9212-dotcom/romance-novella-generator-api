from pathlib import Path


def test_custom_gpt_instructions_keep_safe_editor_margin():
    text = (Path(__file__).resolve().parent.parent / "gpt" / "custom_gpt_instructions.md").read_text(encoding="utf-8")
    assert len(text) <= 7500
