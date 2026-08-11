import json

from app.runtime_documents import PROJECT_ROOT, read_runtime_rules, read_scene_builder


def test_rules_and_builder_keep_writer_first_contract() -> None:
    rules = read_runtime_rules()
    builder = read_scene_builder()

    assert "сценарист интерактивного романа" in rules
    assert "Railway отвечает за память" in rules
    assert "POV — полноценный персонаж" in rules
    assert "не обязан отвечать репликой" in rules
    assert "Как именно этот человек" in rules
    assert "story_direction" in rules
    assert "story_memory" in rules
    assert "recent_scene_history" in rules
    assert "не обязан заметно двигать" in rules
    assert "не превращай роман в симулятор процедуры" in rules.lower()
    assert "Сначала напиши сцену" in rules
    assert "getSceneCharacterBundle" in rules

    assert "Ход {turn_number} · цикл {cycle_position}/15" in builder
    assert "Всегда 9 вариантов" in builder
    assert "900–2000" in builder
    assert "третьем лице" in builder
    assert "не обязан постоянно разговаривать" in builder
    assert "Сюжет должен двигаться в масштабе истории" in builder
    assert "произносимые слова" in builder
    assert "не выдумывай изменение" in builder.lower()
    assert "После текста" in builder
    assert "commitTurn" in builder
    assert "Перед следующим ходом: прочитать актуальный state" not in builder


def test_custom_gpt_instruction_stays_compact_and_has_preview_gate() -> None:
    instructions = (PROJECT_ROOT / "gpt" / "custom_gpt_instructions.md").read_text(
        encoding="utf-8"
    )
    assert len(instructions) < 8000
    assert "До явного «подтверждаю» не вызывай Railway" in instructions
    assert "getAuditPacket" in instructions
    assert "getSceneCharacterBundle" in instructions
    assert 'runtime_contract_version: "2.0"' in instructions
    assert "all_chunks_delivered" in instructions
    assert "revise_last" in instructions
    assert "Сначала именно сцену" in instructions
    assert "не переписывай его каждый ход" in instructions.lower()
    assert "Служебное напоминание" in instructions


def test_all_state_templates_are_valid_json() -> None:
    templates = sorted((PROJECT_ROOT / "state_templates").rglob("*.json"))
    assert templates
    for template in templates:
        json.loads(template.read_text(encoding="utf-8"))
