from typing import Any
from pathlib import Path
from app.scene_contract_builder import build_scene_contract


PROMPT_FILES = [
    "prompts/scene_writer.md",
    "prompts/scene_format_rules.md",
    "prompts/player_input_rules.md",
    "prompts/player_character_rules.md",
    "prompts/npc_rules.md",
    "prompts/knowledge_rules.md",
    "prompts/relationship_rules.md",
    "prompts/state_updater.md",
    "rules/player_agency.md",
    "rules/no_micro_choice.md",
    "rules/hidden_character_rules.md",
    "rules/npc_knowledge_boundary.md",
    "rules/scene_style.md",
    "rules/academy_style_header.md",
]


def _read_project_file(relative_path: str) -> str:
    root = Path(__file__).resolve().parent.parent
    path = root / relative_path
    return path.read_text(encoding="utf-8")


def build_scene_prompt(scene_contract: dict[str, Any]) -> str:
    rules = []
    for relative_path in PROMPT_FILES:
        rules.append(f"\n\n<!-- {relative_path} -->\n" + _read_project_file(relative_path))
    return "".join(rules) + f"\n\nSCENE_CONTRACT_JSON:\n{scene_contract}"


def _as_list_text(value: Any, fallback: str = "нет") -> str:
    if isinstance(value, list):
        return ", ".join(str(x) for x in value) if value else fallback
    if isinstance(value, str) and value.strip():
        return value
    return fallback


def _render_stub_scene(current_frame: dict[str, Any], player_input: str, status: dict[str, Any], story_title: str) -> str:
    name = current_frame.get("player_display_name") or "Героиня"
    date = current_frame.get("date") or "День 1"
    time = current_frame.get("time") or "время не задано"
    location = current_frame.get("location") or "место сцены"
    weather = current_frame.get("weather") or "атмосфера не задана"
    scene_state = current_frame.get("scene_state") or "тестовый режим, проверка сборки"
    visible_state = status.get("emotional_state", "нейтрально")
    outfit = current_frame.get("outfit") or "одежда не задана"
    inventory = _as_list_text(current_frame.get("inventory"), "ничего не указано")
    nearby_items = _as_list_text(current_frame.get("nearby_items"), "рядом ничего не указано")
    custom = status.get("custom", [])
    custom_1 = custom[0] if len(custom) > 0 else {"label": "Поле истории 1", "value": "не задано"}
    custom_2 = custom[1] if len(custom) > 1 else {"label": "Поле истории 2", "value": "не задано"}
    skills = status.get("skills") or []
    injuries = status.get("injuries") or []

    return f"""🎭 {story_title} · {date}
🕒 {time} · 📍 {location}
🌦️ Погода: {weather}
⚙️ Состояние сцены: {scene_state}

✦ {name} · {visible_state}
🧥 {outfit}
◈ При себе: {inventory}. Рядом: {nearby_items}

━━━━━━━━━━━━━━━━━━━━

*{name} остаётся в точке: {location}. Последний ввод игрока принят как якорь сцены: {player_input!r}. Воздух вокруг держит паузу, а история пока не делает важный выбор за персонажа игрока.*

━━━━━━━━━━━━━━━━━━━━

✦ Что можно сделать
◈ Осмотреться внимательнее.
◈ Проверить вещи при себе.
◈ Сделать шаг дальше.

✦ Что можно сказать
— Продолжим.
— Я хочу понять, что происходит.
— Не сейчас.

✦ Мысли
— Отметить, что именно изменилось вокруг.
— Сдержать первую реакцию.
— Подумать, кому можно доверять.

✦ Состояние
Голод: {status.get('hunger', 'норма')}
Усталость: {status.get('fatigue', 'низкая')}
Травмы: {', '.join(injuries) if injuries else 'нет'}
Эмоциональное состояние: {status.get('emotional_state', 'нейтрально')}
Навыки / ресурс: {', '.join(skills) if skills else 'без активного ресурса'}
{custom_1.get('label', 'Поле истории 1')}: {custom_1.get('value', 'не задано')}
{custom_2.get('label', 'Поле истории 2')}: {custom_2.get('value', 'не задано')}

✦ Отношения
Нет активных изменений.

━━━━━━━━━━━━━━━━━━━━"""


def process_turn_manual(bundle: dict[str, Any], player_input: str) -> dict[str, Any]:
    contract = build_scene_contract(bundle, player_input=player_input)
    return {
        "status": "manual_prompt_ready",
        "scene_prompt": build_scene_prompt(contract),
        "diagnostics": {
            "loaded_character_count": len(contract.get("loaded_characters", [])),
            "loaded_relationship_count": len(contract.get("loaded_relationships", [])),
            "visible_relationship_pair_ids": contract.get("visible_relationship_pair_ids", []),
        },
    }


def process_turn_local_stub(bundle: dict[str, Any], player_input: str) -> dict[str, Any]:
    contract = build_scene_contract(bundle, player_input=player_input)
    current_frame = contract["current_frame"]
    story_title = bundle.get("session", {}).get("title") or bundle.get("story_plan", {}).get("genre") or "Новая новелла"
    status = current_frame.get("status", {})

    rendered = _render_stub_scene(current_frame, player_input, status, story_title)

    scene_response = {
        "response_version": "novella.scene_response.v1",
        "player_input": player_input,
        "scene": {
            "header": {
                "story_title": story_title,
                "date": current_frame.get("date") or "День 1",
                "time": current_frame.get("time") or "время не задано",
                "location": current_frame.get("location") or "место сцены",
                "weather": current_frame.get("weather") or "атмосфера не задана",
                "scene_state": current_frame.get("scene_state") or "тестовый режим",
                "player_name": current_frame.get("player_display_name") or "Героиня",
                "visible_state": status.get("emotional_state", "нейтрально"),
                "outfit": current_frame.get("outfit") or "одежда не задана",
                "inventory": _as_list_text(current_frame.get("inventory"), "ничего не указано"),
            },
            "body": f"*{current_frame.get('player_display_name') or 'Героиня'} остаётся в точке: {current_frame.get('location') or 'место сцены'}. Последний ввод игрока принят как якорь сцены: {player_input!r}.*",
            "player_options": {
                "thoughts": ["Отметить, что изменилось.", "Сдержать реакцию.", "Подумать, кому можно доверять."],
                "dialogue": ["Продолжим.", "Я хочу понять, что происходит.", "Не сейчас."],
                "actions": ["Осмотреться.", "Проверить вещи.", "Сделать шаг дальше."],
            },
            "status_panel": {
                "hunger": status.get("hunger", "норма"),
                "fatigue": status.get("fatigue", "низкая"),
                "injuries": ", ".join(status.get("injuries", [])) if status.get("injuries") else "нет",
                "emotional_state": status.get("emotional_state", "нейтрально"),
                "skills": ", ".join(status.get("skills", [])) if status.get("skills") else "без активного ресурса",
                "custom": status.get("custom", [])[:2],
            },
            "relationships_panel": [],
            "rendered_text": rendered,
        },
        "summary": "Тестовый ход local_stub без настоящей генерации сцены.",
        "important_facts": [],
        "witnesses": current_frame.get("active_character_ids", []),
        "proposed_updates": {
            "scene_state_patch": {
                "scene_goal": "Продолжить сцену после последнего действия игрока.",
                "status": status,
            },
            "relationship_patches": [],
            "knowledge_patches": [],
            "new_or_updated_characters": [],
        },
        "safety_checks": {
            "used_only_loaded_characters": True,
            "respected_knowledge_boundaries": True,
            "no_hidden_future_reveal": True,
            "no_major_player_character_choice": True,
            "respected_player_input_order": True,
            "showed_only_scene_relationships": True,
            "header_has_no_focus_or_active_list": True,
            "notes": ["local_stub не является полноценным писателем сцены"],
        },
    }

    return {
        "status": "scene_ready",
        "scene": rendered,
        "scene_response": scene_response,
        "diagnostics": {
            "loaded_character_count": len(contract.get("loaded_characters", [])),
            "loaded_relationship_count": len(contract.get("loaded_relationships", [])),
            "visible_relationship_pair_ids": contract.get("visible_relationship_pair_ids", []),
        },
    }
