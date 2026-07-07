from __future__ import annotations
from typing import Any
import json
from app.scene_contract_builder import build_scene_contract

COMPACT_SCENE_WRITER_PROMPT = """
Ты внутри tool-flow. Это НЕ финальный ответ пользователю.

Порядок:
1. Создай scene_response JSON по SCENE_CONTRACT_JSON.
2. НЕ показывай JSON.
3. НЕ пиши комментарии перед API.
4. Сразу вызови applyTurnResult.
5. После успеха покажи только response.message_to_user/rendered_text.

Главное качество сцены:
- Пиши как живую сцену, а не атмосферное эссе.
- Body: 900–1800 знаков, 8–20 коротких beats/абзацев.
- Абзац обычно 1–3 коротких предложения.
- Не раздувай описание поверх описания: 1 яркая деталь на beat, потом действие/реплика/реакция/последствие.
- Описание не должно занимать больше половины body, если в сцене есть живые персонажи.
- Если NPC присутствует, он не декорация: минимум 2–4 живых проявления NPC за сцену.
- Живое проявление NPC = реплика, действие, сообщение, звонок, отказ, ошибка, давление, уход, ревность, злость, забота, обида, пауза, неверный вывод.
- Не делай сцену, где персонаж говорит один раз, а остальное — описание помещения.
- Чуть иронии/сарказма можно, но редко: 1–2 коротких момента на сцену, не в каждой реплике.
- Сцена должна иметь meaningful beat: давление, улика, ошибка, реакция, выбор, последствие или изменение отношения.
- В visible text используй кириллицу для имён, если есть display_name.

Агентность персонажей/NPC:
- Мир не крутится вокруг персонажа игрока и не ждёт его.
- У NPC есть свои дела, проблемы, сроки, страхи, желания, прошлое, привычки и цели.
- NPC не прицеп к героине. Они могут уходить, звонить, писать, перебивать, злиться, ревновать, обижаться, ошибаться, давить, помогать неудобно или отказывать.
- NPC действуют по своему характеру, цели, чувствам, знаниям, отношениям и видимым фактам, а не чтобы быть удобными или специально неудобными.
- NPC не читают мысли игрока и не делают всегда правильные выводы.
- NPC не психологи и не философы по умолчанию. Не превращай реплики в терапию, лекцию или объяснение лора.
- Разные NPC отличаются речью, темпом, границами, ошибками, привычками и способом давить/помогать.

Правила ввода игрока:
- Текст вне скобок = речь персонажа игрока.
- Текст в скобках = действие, жест, пауза, состояние, намерение или мысль.
- Сохраняй порядок ввода.
- Если игрок написал: реплика (действие) реплика — сначала реплика, потом действие/ремарка, потом следующая реплика.
- Не переставляй действие перед репликой, если игрок сначала сказал реплику.
- Не делай важный выбор за игрока.

Формат body:
- Диалоги идут ВНУТРИ body, между действиями и реакциями.
- НЕ делай отдельный блок “Диалог:” внутри body.
- Формат реплики строго:
  **Имя** — Реплика. *(короткая ремарка)*
- Имя всегда жирным.
- Реплика обычным текстом.
- Ремарка только курсивом в скобках.
- Если ремарка не нужна — просто:
  **Имя** — Реплика.
- Не пиши “Имя — Реплика” без жирного имени.
- Не собирай все реплики в конце сцены списком.
- После реплики должен быть живой beat: реакция, пауза, движение, чужая реплика или последствие.

scene_response JSON:
response_version, player_input, scene(header/body/player_options/status_panel/relationships_panel/rendered_text), summary, important_facts, witnesses, proposed_updates, safety_checks.

Типы:
- inventory строка;
- player_options object thoughts/dialogue/actions;
- relationships_panel label/value;
- knowledge_patches character_id/reason/source_in_scene/add_knows/add_observations/add_assumptions;
- relationship_patches pair_id/change_type/entry/reason/source_in_scene.

rendered_text начинается строго:
🎭 <Название истории> · <дата / день>
🕒 <время> · 📍 <локация>
🌦️ Погода: <погода / атмосфера>
⚙️ Состояние сцены: <физический контекст>

✦ <имя героини> · <видимое состояние>
🧥 <одежда>
◈ <предметы при себе / рядом>

━━━━━━━━━━━━━━━━━━━━

Далее body сцены: короткие beats, действия, реплики и реакции. Без отдельного блока “Диалог:”.

В конце:
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
Голод: <0-100>/100 — <1-4 слова>
Усталость: <0-100>/100 — <1-4 слова>
Травмы: <0-100>/100 — <1-4 слова>
Эмоциональное состояние: <0-100>/100 — <1-4 слова>
Навыки / ресурс: <0-100>/100 — <1-4 слова>
<story slot 1>: <0-100>/100 — <1-4 слова>
<story slot 2>: <0-100>/100 — <1-4 слова>

✦ Отношения
<только персонажи текущей сцены или прямо затронутые текущим ходом; формат: Имя: <0-100>/100 — <1-4 слова>. Без объяснений и спойлеров>
━━━━━━━━━━━━━━━━━━━━

Сохранение:
- proposed_updates сохраняют только важное.
- Не сохраняй весь диалог.
- Не сохраняй мысли игрока как знания NPC.
- safety_checks все true только если правила реально соблюдены.
- Нижний блок — короткая dashboard-панель, не объяснение сюжета.
""".strip()

def _clip_text(value: Any, limit: int = 700) -> str:
    text = "" if value is None else str(value); text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit-1].rstrip() + "…"

def _clip_list(items: Any, limit_items: int = 6, text_limit: int = 300) -> list[Any]:
    if not isinstance(items, list): return []
    return [_compact_dict(x, text_limit=text_limit) if isinstance(x, dict) else _clip_text(x, text_limit) for x in items[:limit_items]]

def _compact_dict(data: dict[str, Any], text_limit: int = 500) -> dict[str, Any]:
    result = {}
    for key, value in data.items():
        if isinstance(value, str): result[key] = _clip_text(value, text_limit)
        elif isinstance(value, list): result[key] = _clip_list(value, 6, max(160, text_limit//2))
        elif isinstance(value, dict): result[key] = _compact_dict(value, max(160, text_limit//2))
        else: result[key] = value
    return result

def _compact_character_card(card: dict[str, Any]) -> dict[str, Any]:
    return {"id":card.get("id"), "name":card.get("name"), "display_name":card.get("display_name") or card.get("visible_name") or card.get("name_ru"), "role":card.get("role"), "age":card.get("age"), "introduced":card.get("introduced"), "known_to_player":card.get("known_to_player"), "appearance":_compact_dict(card.get("appearance", {}) if isinstance(card.get("appearance"), dict) else {"summary":card.get("appearance")},350), "personality":_compact_dict(card.get("personality", {}) if isinstance(card.get("personality"), dict) else {"summary":card.get("personality")},350), "goal":_clip_text(card.get("goal"),260), "past_short":_clip_text(card.get("past_short"),350), "habits":_clip_list(card.get("habits"),4,160), "likes_in_people":_clip_list(card.get("likes_in_people"),4,160), "dislikes_in_people":_clip_list(card.get("dislikes_in_people"),4,160), "relationship_triggers":_compact_dict(card.get("relationship_triggers", {}) if isinstance(card.get("relationship_triggers"), dict) else {},220), "skills":_clip_list(card.get("skills"),5,120), "connections":_clip_list(card.get("connections"),5,200)}

def _compact_contract(contract: dict[str, Any]) -> dict[str, Any]:
    compact = {"contract_version":contract.get("contract_version"), "session_id":contract.get("session_id"), "current_frame":contract.get("current_frame", {}), "status_slots":contract.get("status_slots", [])[:2], "story_compass":_compact_dict(contract.get("story_compass", {}) if isinstance(contract.get("story_compass"), dict) else {},700), "visible_relationship_pair_ids":contract.get("visible_relationship_pair_ids", []), "player_input_rules":contract.get("player_input_rules", {}), "maintenance":contract.get("maintenance", {}), "future_locks":{"do_not_reveal_yet":_clip_list((contract.get("future_locks") or {}).get("do_not_reveal_yet", []),5,180), "hidden_character_seeds":_clip_list((contract.get("future_locks") or {}).get("hidden_character_seeds", []),5,180)}, "continuity":_compact_dict(contract.get("continuity", {}) if isinstance(contract.get("continuity"), dict) else {},500)}
    compact["loaded_characters"] = [{"character_id":i.get("character_id"), "display_name":i.get("display_name"), "load_reason":i.get("load_reason", []), "card":_compact_character_card(i.get("card") if isinstance(i.get("card"), dict) else {})} for i in (contract.get("loaded_characters", []) or []) if isinstance(i, dict)][:6]
    compact["loaded_relationships"] = [{"pair_id":i.get("pair_id"), "display_label":i.get("display_label"), "visible_in_footer":i.get("visible_in_footer", False), "content":_compact_dict(i.get("content") if isinstance(i.get("content"), dict) else {},260)} for i in (contract.get("loaded_relationships", []) or []) if isinstance(i, dict)][:8]
    compact["knowledge_boundaries"] = [_compact_dict(i, 220) for i in (contract.get("knowledge_boundaries", []) or []) if isinstance(i, dict)][:6]
    compact["recent_scene_history"] = [{"turn":i.get("turn"), "summary":_clip_text(i.get("summary"),350), "important_facts":_clip_list(i.get("important_facts", []),5,180), "witnesses":i.get("witnesses", [])} for i in (contract.get("recent_scene_history", []) or [])[-3:] if isinstance(i, dict)]
    compact["output_requirements"] = {"tool_flow":"generate scene_response, call applyTurnResult, then show response.message_to_user"}
    return compact

def build_scene_prompt(scene_contract: dict[str, Any]) -> str:
    return f"{COMPACT_SCENE_WRITER_PROMPT}\n\nSCENE_CONTRACT_JSON:\n{json.dumps(_compact_contract(scene_contract), ensure_ascii=False, separators=(',', ':'))}"

def _as_list_text(value: Any, fallback: str = "нет") -> str:
    if isinstance(value, list): return ", ".join(str(x) for x in value) if value else fallback
    if isinstance(value, str) and value.strip(): return value
    return fallback

def _render_stub_scene(current_frame: dict[str, Any], player_input: str, status: dict[str, Any], story_title: str) -> str:
    name = current_frame.get("player_display_name") or "Героиня"; date=current_frame.get("date") or "День 1"; time=current_frame.get("time") or "время не задано"; location=current_frame.get("location") or "место сцены"; weather=current_frame.get("weather") or "атмосфера не задана"; scene_state=current_frame.get("scene_state") or "debug режим"; visible_state=status.get("emotional_state", "нейтрально"); outfit=current_frame.get("outfit") or "одежда не задана"; inventory=_as_list_text(current_frame.get("inventory"), "ничего не указано")
    return f"""🎭 {story_title} · {date}
🕒 {time} · 📍 {location}
🌦️ Погода: {weather}
⚙️ Состояние сцены: {scene_state}

✦ {name} · {visible_state}
🧥 {outfit}
◈ При себе: {inventory}

━━━━━━━━━━━━━━━━━━━━

*{name} остаётся в точке: {location}. Последний ввод игрока принят как якорь сцены: {player_input!r}.*

Диалог:
*Вслух пока ничего не сказано.*

━━━━━━━━━━━━━━━━━━━━

✦ Что можно сделать
◈ Осмотреться внимательнее.
◈ Проверить вещи при себе.
◈ Сделать следующий шаг.

✦ Что можно сказать
— Продолжим.
— Что происходит?
— Не сейчас.

✦ Мысли
— Отметить, что изменилось.
— Сдержать реакцию.
— Подумать, кому можно доверять.

✦ Состояние
Голод: {status.get('hunger', 'норма')}
Усталость: {status.get('fatigue', 'низкая')}
Травмы: {_as_list_text(status.get('injuries'), 'нет')}
Эмоциональное состояние: {status.get('emotional_state', 'нейтрально')}
Навыки / ресурс: {_as_list_text(status.get('skills'), 'без активного ресурса')}
Поле истории 1: не задано
Поле истории 2: не задано

✦ Отношения
Нет активных изменений.

━━━━━━━━━━━━━━━━━━━━"""

def process_turn_gpt_actions(bundle: dict[str, Any], player_input: str) -> dict[str, Any]:
    contract = build_scene_contract(bundle, player_input=player_input); prompt = build_scene_prompt(contract)
    return {"status":"gpt_actions_prompt_ready", "scene":None, "scene_prompt":prompt, "diagnostics":{"loaded_character_count":len(contract.get("loaded_characters", [])), "loaded_relationship_count":len(contract.get("loaded_relationships", [])), "visible_relationship_pair_ids":contract.get("visible_relationship_pair_ids", []), "compact_prompt_chars":len(prompt), "next_required_action":"generate scene_response internally, call applyTurnResult, then show response.message_to_user"}}

def process_turn_debug_stub(bundle: dict[str, Any], player_input: str) -> dict[str, Any]:
    contract = build_scene_contract(bundle, player_input=player_input); current_frame = contract["current_frame"]; story_title = bundle.get("session", {}).get("title") or bundle.get("story_plan", {}).get("genre") or "Новая новелла"; status = current_frame.get("status", {}); rendered = _render_stub_scene(current_frame, player_input, status, story_title)
    scene_response = {"response_version":"novella.scene_response.v1", "player_input":player_input, "scene":{"header":{"story_title":story_title, "date":current_frame.get("date") or "День 1", "time":current_frame.get("time") or "время не задано", "location":current_frame.get("location") or "место сцены", "weather":current_frame.get("weather") or "атмосфера не задана", "scene_state":current_frame.get("scene_state") or "debug режим", "player_name":current_frame.get("player_display_name") or "Героиня", "visible_state":status.get("emotional_state", "нейтрально"), "outfit":current_frame.get("outfit") or "одежда не задана", "inventory":_as_list_text(current_frame.get("inventory"), "ничего не указано")}, "body":"debug_stub", "player_options":{"thoughts":["Отметить, что изменилось.","Сдержать реакцию.","Подумать, кому можно доверять."], "dialogue":["Продолжим.","Что происходит?","Не сейчас."], "actions":["Осмотреться.","Проверить вещи.","Сделать шаг дальше."]}, "status_panel":{"hunger":status.get("hunger", "норма"), "fatigue":status.get("fatigue", "низкая"), "injuries":_as_list_text(status.get("injuries"), "нет"), "emotional_state":status.get("emotional_state", "нейтрально"), "skills":_as_list_text(status.get("skills"), "без активного ресурса"), "custom":status.get("custom", [])[:2]}, "relationships_panel":[], "rendered_text":rendered}, "summary":"Тестовый ход debug_stub.", "important_facts":[], "witnesses":current_frame.get("active_character_ids", []), "proposed_updates":{"scene_state_patch":{"scene_goal":"Продолжить сцену после последнего действия игрока."}, "relationship_patches":[], "knowledge_patches":[], "new_or_updated_characters":[]}, "safety_checks":{"used_only_loaded_characters":True, "respected_knowledge_boundaries":True, "no_hidden_future_reveal":True, "no_major_player_character_choice":True, "respected_player_input_order":True, "showed_only_scene_relationships":True, "header_has_no_focus_or_active_list":True, "notes":["debug_stub"]}}
    return {"status":"scene_ready", "scene":rendered, "scene_response":scene_response, "diagnostics":{"loaded_character_count":len(contract.get("loaded_characters", [])), "loaded_relationship_count":len(contract.get("loaded_relationships", [])), "visible_relationship_pair_ids":contract.get("visible_relationship_pair_ids", [])}}
