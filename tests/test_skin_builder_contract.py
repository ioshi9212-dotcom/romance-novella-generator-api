"""Safeguard the character-driven scene contract, emoji layout, and player agency."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "runtime" / "scene_builder.md"


def load_skin():
    return BUILDER.read_text(encoding="utf-8")


def test_scene_rules_keep_story_independent_and_causally_active():
    skin = load_skin()
    assert "рабочая версия 2" in skin
    assert len(skin) < 16_000
    for rule in (
        "Ты отвечаешь за самостоятельное создание и развитие сюжета",
        "Мир живёт непрерывно",
        "При наличии причины для вмешательства NPC вмешивается",
        "Отношения NPC↔NPC существуют и развиваются независимо от POV",
        "Не создавай искусственные события",
        "Завершай ход в интересной точке продолжения",
    ):
        assert rule in skin, rule


def test_player_agency_character_voice_and_privacy():
    skin = load_skin()
    for rule in (
        "Игрок управляет значимыми решениями POV",
        "Исполняй ввод игрока строго слева направо",
        "Если игрок явно выбрал молчание, сохраняй его",
        "Новые значимые решения",
        "Мысли POV полностью приватны",
        "Запрещено превращать мысли в психологический анализ",
        "Психологически исправлять NPC и POV",
        "1800–3000 символов без пробелов",
    ):
        assert rule in skin, rule

    rules = (ROOT / "runtime/rules.md").read_text(encoding="utf-8")
    assert "Новый параметр по умолчанию начинается не выше 3" in rules
    assert "Не удаляй фактически заслуженный показатель" in rules


def test_original_emoji_header_and_dialogue_format():
    skin = load_skin()
    header = skin.split("### ШАПКА", 1)[1].split("### РЕПЛИКИ", 1)[0]
    for symbol in ("🎭", "🕒", "📍", "🌦️", "⚙️", "✦", "🧥", "◈"):
        assert symbol in header
    for rule in ("{game_day}", "{ДД.ММ.ГГГГ}", "{ЧЧ:ММ}",
                 "{имя POV}", "{только то, что сейчас при POV}", "`game_clock`"):
        assert rule in header
    dialogue = skin.split("### РЕПЛИКИ", 1)[1].split("## 2. СЦЕНА", 1)[0]
    assert "**Сайлас** - Удобно." in dialogue
    assert "**Имя** (сообщение/звонок)" in dialogue


def test_all_nine_options_belong_to_current_pov():
    skin = load_skin()
    choices = skin.split("## 7. ВАРИАНТЫ ВЫБОРА", 1)[1].split(
        "## 8. СОСТОЯНИЕ И ОТНОШЕНИЯ", 1
    )[0]
    for rule in (
        "Все девять вариантов строго отражают текущее состояние именно этой POV",
        "Запрещено создавать альтернативную личность",
        "Каждое действие должно иметь значение",
        "Только готовые слова POV",
        "Настоящие мысли конкретного POV",
        "Варианты опираются только на конец уже показанной сцены",
    ):
        assert rule in choices, rule
    for label in ("сделать", "сказать", "подумать"):
        section = choices.split(f"**Что я могу {label}:**", 1)[1]
        end = section.find("**Что я могу ")
        if end >= 0:
            section = section[:end]
        assert len([line for line in section.splitlines()
                    if line.startswith(("1. ", "2. ", "3. "))]) == 3


def test_footer_separates_npcs_without_losing_relationship_metrics():
    skin = load_skin()
    section = skin.split("## 8. СОСТОЯНИЕ И ОТНОШЕНИЯ", 1)[1].split(
        "## 9. ТЕХНИЧЕСКИЙ КОНТРОЛЬ", 1
    )[0]
    for required in (
        "🫀 **Состояние:**",
        "🤝 **Отношения NPC → POV:**",
        "**{Имя первого NPC}**",
        "**{Имя второго NPC}**",
        "↳ {показатель}: {итог}/{дельта}",
        "включая неизменившиеся",
        "значение/0",
        "итог/+N",
        "итог/-N",
        "Отсутствующих offscreen NPC не выводи",
        "🔁 **Ход {turn_number} · цикл {cycle_position}/15**",
    ):
        assert required in section, required
