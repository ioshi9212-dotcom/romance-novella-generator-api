from __future__ import annotations

from typing import Any
import json

from app.scene_contract_builder import build_scene_contract


COMPACT_SCENE_WRITER_PROMPT = """
Ты пишешь сцену интерактивной визуальной новеллы по SCENE_CONTRACT_JSON.
Railway уже собрал только нужную память. Не используй старый чат как источник канона.

Верни СТРОГО JSON scene_response:
{
  "response_version": "novella.scene_response.v1",
  "player_input": "...",
  "scene": {
    "header": {
      "story_title": "...",
      "date": "...",
      "time": "...",
      "location": "...",
      "weather": "...",
      "scene_state": "...",
      "player_name": "...",
      "visible_state": "...",
      "outfit": "...",
      "inventory": "..."
    },
    "body": "...",
    "player_options": {
      "thoughts": ["...", "...", "..."],
      "dialogue": ["...", "...", "..."],
      "actions": ["...", "...", "..."]
    },
    "status_panel": {
      "hunger": "...",
      "fatigue": "...",
      "injuries": "...",
      "emotional_state": "...",
      "skills": "...",
      "custom": [
        {"id": "...", "label": "...", "value": "..."},
        {"id": "...", "label": "...", "value": "..."}
      ]
    },
    "relationships_panel": [],
    "rendered_text": "..."
  },
  "summary": "...",
  "important_facts": [],
  "witnesses": [],
  "proposed_updates": {
    "scene_state_patch": {},
    "relationship_patches": [],
    "knowledge_patches": [],
    "new_or_updated_characters": []
  },
  "safety_checks": {
    "used_only_loaded_characters": true,
    "respected_knowledge_boundaries": true,
    "no_hidden_future_reveal": true,
    "no_major_player_character_choice": true,
    "respected_player_input_order": true,
    "showed_only_scene_relationships": true,
    "header_has_no_focus_or_active_list": true,
    "notes": []
  }
}

Видимый rendered_text должен начинаться строго:
🎭 <Название истории> · <дата / день>
🕒 <время> · 📍 <локация>
🌦️ Погода: <погода / атмосфера>
⚙️ Состояние сцены: <физический контекст>

✦ <имя героини> · <видимое состояние>
🧥 <одежда>
◈ <предметы при себе / рядом>

━━━━━━━━━━━━━━━━━━━━

Диалог: **Имя** — Реплика. *(короткая ремарка)*

В конце rendered_text:
━━━━━━━━━━━━━━━━━━━━
✦ Что можно сделать
◈ ...
◈ ...
◈ ...

✦ Что можно сказать
— ...
— ...
— ...

✦ Мысли
— ...
— ...
— ...

✦ Состояние
Голод: ...
Усталость: ...
Травмы: ...
Эмоциональное состояние: ...
Навыки / ресурс: ...
<story slot 1>: ...
<story slot 2>: ...

✦ Отношения
<только персонажи текущей сцены или прямо затронутые текущим ходом>
━━━━━━━━━━━━━━━━━━━━

Правила:
- Не делай важный выбор за игрока.
- Текст игрока вне скобок = речь. Текст в скобках = действие/жест/мысль/пауза, NPC не читают мысли.
- Сохраняй порядок ввода игрока.
- NPC знают только то, что есть в knowledge, relationship, текущей сцене или видимых фактах.
- Опоздавший персонаж не знает прошлые события как свидетель.
- Не раскрывай hidden future.
- Не используй русские/славянские имена для новых персонажей.
- Не делай NPC терапевтами или философами по умолчанию.
- Сцена должна иметь meaningful beat: давление, последствие, выбор, улику, изменение отношений или новый факт.
- Не заканчивай микровыбором, если можно довести до реальной точки выбора.
- Proposed updates сохраняют только важное: current_state, знания с source_in_scene, отношения с reason/source_in_scene, новых важных NPC.
- Не сохраняй весь диалог. Не сохраняй мысли игрока как знания NPC.
- Если maintenance.continuity_check_required=true, перед сценой внутренне проверь: кто где, кто что знает, нет ли противоречий.
- Если maintenance.memory_review_required=true, дай компактные important_facts/summary без длинного пересказа.
""".strip()


def _clip_text(value: Any, limit: int = 700) -> str:
    text = "" if value is None else str(value)
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _clip_list(items: Any, limit_items: int = 6, text_limit: int = 300) -> list[Any]:
    if not isinstance(items, list):
        return []
    result = []
    for item in items[:limit_items]:
        if isinstance(item, dict):
            result.append(_compact_dict(item, text_limit=text_limit))
        else:
            result.append(_clip_text(item, text_limit))
    return result


def _compact_dict(data: dict[str, Any], text_limit: int = 500) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, str):
            result[key] = _clip_text(value, text_limit)
        elif isinstance(value, list):
            result[key] = _clip_list(value, limit_items=6, text_limit=max(160, text_limit // 2))
        elif isinstance(value, dict):
            result[key] = _compact_dict(value, text_limit=max(160, text_limit // 2))
        else:
            result[key] = value
    return result


def _compact_character_card(card: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": card.get("id"),
        "name": card.get("name"),
        "role": card.get("role"),
        "age": card.get("age"),
        "introduced": card.get("introduced"),
        "known_to_player": card.get("known_to_player"),
        "appearance": _compact_dict(card.get("appearance", {}) if isinstance(card.get("appearance"), dict) else {"summary": card.get("appearance")}, 350),
        "personality": _compact_dict(card.get("personality", {}) if isinstance(card.get("personality"), dict) else {"summary": card.get("personality")}, 350),
        "goal": _clip_text(card.get("goal"), 260),
        "past_short": _clip_text(card.get("past_short"), 350),
        "habits": _clip_list(card.get("habits"), 4, 160),
        "likes_in_people": _clip_list(card.get("likes_in_people"), 4, 160),
        "dislikes_in_people": _clip_list(card.get("dislikes_in_people"), 4, 160),
        "relationship_triggers": _compact_dict(card.get("relationship_triggers", {}) if isinstance(card.get("relationship_triggers"), dict) else {}, 220),
        "skills": _clip_list(card.get("skills"), 5, 120),
        "connections": _clip_list(card.get("connections"), 5, 200),
    }


def _compact_contract(contract: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {
        "contract_version": contract.get("contract_version"),
        "session_id": contract.get("session_id"),
        "current_frame": contract.get("current_frame", {}),
        "status_slots": contract.get("status_slots", [])[:2],
        "story_compass": _compact_dict(contract.get("story_compass", {}) if isinstance(contract.get("story_compass"), dict) else {}, 700),
        "visible_relationship_pair_ids": contract.get("visible_relationship_pair_ids", []),
        "player_input_rules": contract.get("player_input_rules", {}),
        "maintenance": contract.get("maintenance", {}),
        "future_locks": {
            "do_not_reveal_yet": _clip_list((contract.get("future_locks") or {}).get("do_not_reveal_yet", []), 5, 180),
            "hidden_character_seeds": _clip_list((contract.get("future_locks") or {}).get("hidden_character_seeds", []), 5, 180),
        },
        "continuity": _compact_dict(contract.get("continuity", {}) if isinstance(contract.get("continuity"), dict) else {}, 500),
    }

    loaded_characters = []
    for item in contract.get("loaded_characters", []) or []:
        if not isinstance(item, dict):
            continue
        card = item.get("card") if isinstance(item.get("card"), dict) else {}
        loaded_characters.append({
            "character_id": item.get("character_id"),
            "display_name": item.get("display_name"),
            "load_reason": item.get("load_reason", []),
            "card": _compact_character_card(card),
        })
    compact["loaded_characters"] = loaded_characters[:6]

    loaded_relationships = []
    for item in contract.get("loaded_relationships", []) or []:
        if not isinstance(item, dict):
            continue
        content = item.get("content") if isinstance(item.get("content"), dict) else {}
        loaded_relationships.append({
            "pair_id": item.get("pair_id"),
            "display_label": item.get("display_label"),
            "load_reason": item.get("load_reason", []),
            "visible_in_footer": item.get("visible_in_footer", False),
            "content": {
                "status": _clip_text(content.get("status"), 260),
                "type": content.get("type"),
                "scores": content.get("scores", {}),
                "a_view_of_b": _compact_dict(content.get("a_view_of_b", {}) if isinstance(content.get("a_view_of_b"), dict) else {}, 220),
                "b_view_of_a": _compact_dict(content.get("b_view_of_a", {}) if isinstance(content.get("b_view_of_a"), dict) else {}, 220),
                "recent_changes": _clip_list(content.get("recent_changes", []), 3, 180),
                "open_threads": _clip_list(content.get("open_threads", []), 4, 160),
            },
        })
    compact["loaded_relationships"] = loaded_relationships[:8]

    boundaries = []
    for item in contract.get("knowledge_boundaries", []) or []:
        if not isinstance(item, dict):
            continue
        boundaries.append({
            "character_id": item.get("character_id"),
            "known": _clip_list(item.get("known", []), 5, 160),
            "known_facts": _clip_list(item.get("known_facts", []), 6, 220),
            "observations": _clip_list(item.get("observations", []), 6, 220),
            "assumptions": _clip_list(item.get("assumptions", []), 6, 220),
            "wrong_beliefs": _clip_list(item.get("wrong_beliefs", []), 5, 220),
            "recent_memories": _clip_list(item.get("recent_memories", []), 5, 180),
            "open_questions": _clip_list(item.get("open_questions", []), 5, 160),
            "unknown": _clip_list(item.get("unknown", []), 5, 160),
            "must_not_assume": _clip_list(item.get("must_not_assume", []), 5, 160),
        })
    compact["knowledge_boundaries"] = boundaries[:6]

    history = []
    for item in contract.get("recent_scene_history", [])[-3:]:
        if not isinstance(item, dict):
            continue
        history.append({
            "turn": item.get("turn"),
            "summary": _clip_text(item.get("summary"), 350),
            "important_facts": _clip_list(item.get("important_facts", []), 5, 180),
            "witnesses": item.get("witnesses", []),
        })
    compact["recent_scene_history"] = history

    # Keep requirements compact. The detailed schema is already known by API validation.
    compact["output_requirements"] = {
        "response_schema": "schemas/scene_response.schema.json",
        "state_update_mode": "propose_patch_only",
        "visible_scene_header_required": True,
        "footer_required": True,
        "relationships_panel": "only current scene / directly affected pairs",
    }
    return compact


def build_scene_prompt(scene_contract: dict[str, Any]) -> str:
    compact_contract = _compact_contract(scene_contract)
    contract_json = json.dumps(compact_contract, ensure_ascii=False, separators=(",", ":"))
    return f"{COMPACT_SCENE_WRITER_PROMPT}\n\nSCENE_CONTRACT_JSON:\n{contract_json}"


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
    scene_state = current_frame.get("scene_state") or "debug режим, проверка сборки"
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


def process_turn_gpt_actions(bundle: dict[str, Any], player_input: str) -> dict[str, Any]:
    contract = build_scene_contract(bundle, player_input=player_input)
    prompt = build_scene_prompt(contract)
    return {
        "status": "gpt_actions_prompt_ready",
        "scene_prompt": prompt,
        "diagnostics": {
            "loaded_character_count": len(contract.get("loaded_characters", [])),
            "loaded_relationship_count": len(contract.get("loaded_relationships", [])),
            "visible_relationship_pair_ids": contract.get("visible_relationship_pair_ids", []),
            "compact_prompt_chars": len(prompt),
        },
    }


def process_turn_debug_stub(bundle: dict[str, Any], player_input: str) -> dict[str, Any]:
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
                "scene_state": current_frame.get("scene_state") or "debug режим",
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
        "summary": "Тестовый ход debug_stub без настоящей генерации сцены.",
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
            "notes": ["debug_stub не является полноценным писателем сцены"],
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
