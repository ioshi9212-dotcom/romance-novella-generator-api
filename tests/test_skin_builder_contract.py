"""Safeguard compact scene rules and active-world/POV contracts."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_scene_rules_stay_compact_and_world_remains_causally_active():
    skin = (ROOT / "runtime/scene_builder.md").read_text(encoding="utf-8")
    assert "тестовая версия 1.4" in skin
    assert len(skin) < 13_000
    assert "Мир обязан проявляться в происходящем, а не только в декорациях" in skin
    assert "За несколько ходов внешняя жизнь должна ощутимо влиять" in skin
    assert "не выдумывай аварии, звонки, конфликты" in skin
    assert "NPC взаимодействуют друг с другом" in skin


def test_player_agency_voice_and_format_are_preserved():
    skin = (ROOT / "runtime/scene_builder.md").read_text(encoding="utf-8")
    required = (
        "игрок определяет значимые решения POV",
        "Если игрок явно выбрал молчание, сохраняй его",
        "Ввод игрока исполняется строго слева направо",
        "Мысли POV приватны",
        "1800–3000 символов без пробелов",
        "## ШАПКА",
        "## РЕПЛИКИ",
        "## ВАРИАНТЫ ВЫБОРА",
        "**Что я могу сделать:**",
        "**Что я могу сказать:**",
        "**Что я могу подумать:**",
        "## СОСТОЯНИЕ И ОТНОШЕНИЯ",
        "Значения от 0 до 100",
        "Изменение указывается относительно прошлого хода: +N, -N или 0",
        "Отсутствующих персонажей не выводи",
        "**Ход {номер} · цикл {позиция}/15**",
    )
    for rule in required:
        assert rule in skin, rule

    rules = (ROOT / "runtime/rules.md").read_text(encoding="utf-8")
    assert "Новый параметр по умолчанию начинается не выше 3" in rules
    assert "Не удаляй фактически заслуженный показатель" in rules
