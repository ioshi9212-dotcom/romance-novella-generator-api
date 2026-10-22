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


def test_all_nine_options_follow_current_pov_state_not_idealized_reactions():
    skin = (ROOT / "runtime/scene_builder.md").read_text(encoding="utf-8")
    choices = skin.split("## ВАРИАНТЫ ВЫБОРА", 1)[1].split(
        "## СОСТОЯНИЕ И ОТНОШЕНИЯ", 1
    )[0]
    assert "Все девять вариантов строго отражают текущее состояние именно этой POV" in choices
    assert "Не приукрашай и не исправляй персонажа" in choices
    assert "не придумывай противоположные чувства и поступки ради разнообразия" in choices
    assert "доступные знания" in choices
    assert "на которые POV сейчас действительно склонна и способна" in choices
    assert "которые POV сказала бы сейчас своим языком и тоном" in choices
    assert "её настоящим внутренним голосом" in choices
    for label in ("сделать", "сказать", "подумать"):
        section = choices.split(f"**Что я могу {label}:**", 1)[1]
        end = section.find("**Что я могу ")
        if end >= 0:
            section = section[:end]
        assert len([line for line in section.splitlines() if line.startswith(("1. ", "2. ", "3. "))]) == 3


def test_npc_schedules_do_not_auto_align_to_pov_availability():
    skin = (ROOT / "runtime/scene_builder.md").read_text(encoding="utf-8")
    world = skin.split("## 1. ЖИВОЙ МИР И САМОСТОЯТЕЛЬНЫЕ СОБЫТИЯ", 1)[1].split(
        "## 2. ХАРАКТЕР И ИНИЦИАТИВА ПЕРСОНАЖЕЙ", 1
    )[0]
    required = (
        "У NPC собственное расписание, не вычисленное по календарю POV",
        "планов, возможностей и знаний самого NPC",
        "не подбирает удобную дату по скрытому календарю POV",
        "Уже назначенные чужие дела не исчезают",
        "Совпадения возможны, накладки и несостоявшиеся встречи тоже",
        "это его выбор, а не обязанность мира",
    )
    for phrase in required:
        assert phrase in world, phrase
