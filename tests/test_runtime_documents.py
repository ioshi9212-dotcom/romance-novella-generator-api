import json

from app.runtime_documents import PROJECT_ROOT, read_runtime_rules, read_scene_builder


def test_rules_and_builder_contain_the_agreed_runtime_contract() -> None:
    rules = read_runtime_rules()
    builder = read_scene_builder()
    assert "Как именно этот человек" in rules
    assert "собственных knowledge-записей" in rules
    assert "забывать" in rules
    assert "неважный npc" in rules.lower()
    assert "Ход {turn_number} · цикл {cycle_position}/15" in builder
    assert "прочитать актуальный state" in builder
    assert "На 15/15" in builder
    assert "1500 до 2500" in builder


def test_custom_gpt_instruction_stays_compact_and_has_preview_gate() -> None:
    instructions = (PROJECT_ROOT / "gpt" / "custom_gpt_instructions.md").read_text(
        encoding="utf-8"
    )
    assert len(instructions) < 8000
    assert "До явного «подтверждаю» не вызывай Railway" in instructions
    assert "getAuditPacket" in instructions
    assert "revise_last" in instructions


def test_all_state_templates_are_valid_json() -> None:
    templates = sorted((PROJECT_ROOT / "state_templates").rglob("*.json"))
    assert templates
    for template in templates:
        json.loads(template.read_text(encoding="utf-8"))
