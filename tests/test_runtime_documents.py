import json

from app.runtime_documents import PROJECT_ROOT, read_runtime_rules, read_scene_builder


def test_rules_and_builder_keep_minimal_writer_contract() -> None:
    rules = read_runtime_rules()
    builder = read_scene_builder()

    assert "сценарист интерактивного романа" in rules
    assert "Railway хранит память" in rules
    assert "POV — полноценный участник" in rules
    assert "действуют как реальные люди" in rules
    assert "не тем, как «правильно» по психологии" in rules
    assert "третьем лице" in rules
    assert "Сарказм автора — около 5%" in rules
    assert "Отношение POV к другим система не назначает" in rules
    assert "getSceneCharacterBundle" in rules
    assert "commitTurn" in rules
    assert "plot_state.active_arcs" in rules
    assert "anchor_facts" in rules
    assert "Жёсткого лимита ходов нет" in rules
    assert "plot_state.resolved_arcs" in rules

    assert "Строго 1500–2500 символов" in builder
    assert "Третье лицо" in builder
    assert "POV всегда присутствует" in builder
    assert "около 5%" in builder
    assert "Всегда ровно 3 действия, 3 реплики и 3 мысли" in builder
    assert "В каждом разделе нумерация отдельно: 1, 2, 3" in builder
    assert "не нейтральные или бытовые действия ради заполнения блока" in builder
    assert "Райан - доверие 10/+1" in builder
    assert "Один показатель = одно слово" in builder
    assert "Отношение POV к другим не показывай" in builder
    assert "Ход {turn_number} · цикл {cycle_position}/15" in builder


def test_scene_builder_includes_selective_cinematic_coverage() -> None:
    builder = read_scene_builder()
    assert "# CINEMATIC COVERAGE CONTRACT" in builder
    assert "ROUTINE" in builder
    assert "STANDARD" in builder
    assert "CINEMATIC" in builder
    assert "до 3000 символов основной сцены" in builder
    assert "приоритет над более ранней общей границей 2500" in builder
    assert "Ощущения НЕ заменяют визуал" in builder
    assert "NO MISSING BEATS" in builder
    assert "Не делай ранний монтажный обрыв" in builder
    assert "НЕ ПЕРЕОПИСЫВАЙ РУТИНУ" in builder
    assert "ВАЖНЫЙ МОМЕНТ НУЖНО НЕ ТОЛЬКО ПОНЯТЬ, НО И УВИДЕТЬ" in builder


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
    assert "Сначала напиши полный ответ по `scene_builder`" in instructions
    assert "director_plan` обновляй только если" in instructions
    assert "Не показывай JSON" in instructions


def test_all_state_templates_are_valid_json() -> None:
    templates = sorted((PROJECT_ROOT / "state_templates").rglob("*.json"))
    assert templates
    for template in templates:
        json.loads(template.read_text(encoding="utf-8"))
