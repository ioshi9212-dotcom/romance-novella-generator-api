from __future__ import annotations
from typing import Any
import json
from app.scene_contract_builder import build_scene_contract

COMPACT_SCENE_WRITER_PROMPT = """
Ты внутри tool-flow. Это НЕ финальный ответ пользователю.

Порядок: если processTurn вернул prompt_chunk_count > 1, сначала прочитай все чанки через getTurnPromptChunk и склей scene_prompt по порядку. Затем создай scene_response JSON по SCENE_CONTRACT_JSON, НЕ показывай JSON и НЕ пиши комментарии перед вызовом API. Сразу вызови applyTurnResult, после успеха покажи response.message_to_user.

Качество сцены:
- rendered_text должен быть полноценной сценой, не кратким пересказом.
- Body: 900–1800 знаков, 8–20 коротких beat-абзацев. scene.body содержит тот же body, что виден между шапкой и вариантами.
- Пиши сцену короткими beat-абзацами: действие, реплика, реакция, пауза, движение, новая деталь, чужая реплика, последствие.
- Абзац обычно 1–3 коротких предложения. Не пиши 5–9 больших плотных абзацев.
- Не раздувай описание поверх описания: одна яркая деталь на beat, затем действие/реплика/реакция/последствие.
- Описание не должно занимать больше половины body, если в сцене есть живые персонажи.
- Если NPC присутствует, он не декорация: минимум 2–4 живых проявления NPC за сцену (реплика, действие, сообщение, звонок, отказ, ошибка, давление, уход, жест, ревность, злость, забота, обида, неверный вывод).
- Чуть иронии/сарказма можно, но редко: 1–2 коротких момента на сцену, не в каждой реплике.
- Сцена имеет начало, развитие, реакцию среды/NPC/сообщения и финальный крючок.
- Заканчивай точкой выбора после нового давления/детали/реплики/звука/действия.
- Варианты в конце meaningful: выбор реакции, границы, риска, вопроса или действия.
- В rendered_text ОБЯЗАТЕЛЬНО вставь body между шапкой и блоком выбора.
- В visible text используй кириллицу для имён, если есть display_name.

Агентность персонажей/NPC:
- Мир не крутится вокруг персонажа игрока и не ждёт его. У NPC есть свои дела, проблемы, сроки, страхи, желания, прошлое и цели.
- NPC не прицеп к героине: они могут уходить, звонить, писать, перебивать, злиться, ревновать, обижаться, ошибаться, давить, помогать неудобно или отказывать.
- NPC действуют по своему характеру, цели, чувствам, знаниям, отношениям и видимым фактам, а не чтобы быть удобными/неудобными для игрока.
- NPC не читают мысли игрока и не делают всегда правильные выводы. Они могут неверно понять жест, паузу, сарказм, молчание или действие.
- NPC не психологи и не философы по умолчанию. Не превращай реплики в терапию, лекцию или объяснение лора.
- Разные NPC должны отличаться речью, темпом, границами, ошибками, привычками и способом давить/помогать.
- Не делай всех одинаково мягкими, одинаково грубыми или одинаково понимающими.

Диалоги:
- Реплики всегда внутри body, отдельными строками между действиями и реакциями.
- Формат реплики строго: **Имя** — Реплика. *(короткая ремарка, если нужна)*
- Нельзя делать отдельный блок “Диалог:” и нельзя собирать все реплики списком в конце.
- Запрещены гибридные строки без реплики: “кто-то говорит — тихо”, “голос произносит — негромко”, “снаружи неизвестный говорит — через дождь”.
- Если нужно подготовить реплику, сначала отдельный beat описания: “Снаружи голос становится ровнее.” Потом строка реплики.
- Не переставляй порядок ввода игрока: если игрок сначала говорит, потом действует, не меняй на действие → реплика.

Статусы и нижняя панель:
- Нижняя панель НЕ декоративная. Не придумывай случайные числа/подписи. Бери status из SCENE_CONTRACT_JSON.current_frame.status и меняй только через proposed_updates.scene_state_patch.status, если в сцене реально случилось изменение.
- Если голод/усталость/травма/эмоция высокие (70+), это должно проявиться в body: движение, темп речи, пауза, боль, дрожь, раздражение, страх, срыв контроля. Не игнорируй 100/100.
- Травмы включают боль/штамп/ожог/рану/руку. Если рука болит, персонаж автоматически бережёт её или реагирует телом, даже без напоминания игрока.
- Эмоции должны соответствовать происходящему. Неприятная мистика не делает героиню спокойной стендап-машиной: страх, злость, отвращение, контроль, усталость выражаются телом и голосом.
- player_options.actions = только физические действия без речи. “Попросить/сказать/спросить/передать/предупредить” — это dialogue, не actions.
- dialogue options не начинай с лишнего тире: backend сам добавит “—”. Реплики должны отличаться по намерению: граница, вопрос, отказ/риск, а не три одинаковые шутки.
- relationships_panel — состояние отношений из state, не пересказ события. Пиши “низкое доверие”, “рабочее напряжение”, “осторожный интерес”, а не “избавилась от пакета”. Значения не должны резко прыгать без relationship_patches.

scene_response JSON: response_version, player_input, scene(header/body/player_options/status_panel/relationships_panel/rendered_text), summary, important_facts, witnesses, proposed_updates, safety_checks.
Типы: inventory строка; player_options object thoughts/dialogue/actions; relationships_panel label/value; knowledge_patches character_id/reason/source_in_scene/add_knows/add_observations/add_assumptions; relationship_patches pair_id/change_type/entry/reason/source_in_scene.

rendered_text начинается строго:
🎭 <Название истории> · <дата / день>
🕒 <время> · 📍 <локация>
🌦️ Погода: <погода / атмосфера>
⚙️ Состояние сцены: <физический контекст>

✦ <имя героини> · <видимое состояние>
🧥 <одежда>
◈ <предметы при себе / рядом>

━━━━━━━━━━━━━━━━━━━━

<body сцены: короткие beat-абзацы. Реплики идут внутри body между действиями и реакциями. Никакого отдельного блока “Диалог:”.>

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

Правила: не делай важный выбор за игрока; сохраняй порядок ввода; не раскрывай hidden future; сцена должна иметь meaningful beat; proposed_updates сохраняют только важное. Нижний блок — короткая dashboard-панель, не объяснение сюжета.
""".strip()

def _clip_text(value: Any, limit: int = 520) -> str:
    text = "" if value is None else str(value); text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit-1].rstrip() + "…"

def _clip_list(items: Any, limit_items: int = 6, text_limit: int = 300) -> list[Any]:
    if not isinstance(items, list): return []
    return [_compact_dict(x, text_limit=text_limit) if isinstance(x, dict) else _clip_text(x, text_limit) for x in items[:limit_items]]

def _compact_dict(data: dict[str, Any], text_limit: int = 320) -> dict[str, Any]:
    result = {}
    for key, value in data.items():
        if isinstance(value, str): result[key] = _clip_text(value, text_limit)
        elif isinstance(value, list): result[key] = _clip_list(value, 6, max(160, text_limit//2))
        elif isinstance(value, dict): result[key] = _compact_dict(value, max(160, text_limit//2))
        else: result[key] = value
    return result

def _compact_character_card(card: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": card.get("id"),
        "name": card.get("name"),
        "display_name": card.get("display_name") or card.get("visible_name") or card.get("name_ru"),
        "role": card.get("role"),
        "introduced": card.get("introduced"),
        "appearance": _compact_dict(card.get("appearance", {}) if isinstance(card.get("appearance"), dict) else {"summary": card.get("appearance")}, 180),
        "personality": _compact_dict(card.get("personality", {}) if isinstance(card.get("personality"), dict) else {"summary": card.get("personality")}, 180),
        "goal": _clip_text(card.get("goal"), 180),
        "habits": _clip_list(card.get("habits"), 3, 100),
        "connections": _clip_list(card.get("connections"), 3, 120),
    }

def _compact_contract(contract: dict[str, Any]) -> dict[str, Any]:
    compact = {"contract_version":contract.get("contract_version"), "session_id":contract.get("session_id"), "current_frame":contract.get("current_frame", {}), "status_slots":contract.get("status_slots", [])[:2], "story_compass":_compact_dict(contract.get("story_compass", {}) if isinstance(contract.get("story_compass"), dict) else {},700), "visible_relationship_pair_ids":contract.get("visible_relationship_pair_ids", []), "player_input_rules":contract.get("player_input_rules", {}), "maintenance":contract.get("maintenance", {}), "future_locks":{"do_not_reveal_yet":_clip_list((contract.get("future_locks") or {}).get("do_not_reveal_yet", []),5,180), "hidden_character_seeds":_clip_list((contract.get("future_locks") or {}).get("hidden_character_seeds", []),5,180)}, "continuity":_compact_dict(contract.get("continuity", {}) if isinstance(contract.get("continuity"), dict) else {},260), "memory_chunks":[_compact_dict(i,220) for i in (contract.get("memory_chunks", []) or [])[-3:] if isinstance(i, dict)]}
    compact["loaded_characters"] = [{"character_id":i.get("character_id"), "display_name":i.get("display_name"), "load_reason":i.get("load_reason", []), "card":_compact_character_card(i.get("card") if isinstance(i.get("card"), dict) else {})} for i in (contract.get("loaded_characters", []) or []) if isinstance(i, dict)][:4]
    compact["loaded_relationships"] = [{"pair_id":i.get("pair_id"), "display_label":i.get("display_label"), "visible_in_footer":i.get("visible_in_footer", False), "content":_compact_dict(i.get("content") if isinstance(i.get("content"), dict) else {},260)} for i in (contract.get("loaded_relationships", []) or []) if isinstance(i, dict)][:5]
    compact["knowledge_boundaries"] = [_compact_dict(i, 220) for i in (contract.get("knowledge_boundaries", []) or []) if isinstance(i, dict)][:4]
    compact["recent_scene_history"] = [{"turn":i.get("turn"), "summary":_clip_text(i.get("summary"),350), "important_facts":_clip_list(i.get("important_facts", []),5,180), "witnesses":i.get("witnesses", [])} for i in (contract.get("recent_scene_history", []) or [])[-2:] if isinstance(i, dict)]
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
