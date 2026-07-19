from __future__ import annotations

from typing import Any
import json

from app.scene_contract_builder import build_scene_contract
from app.scene_rules_compiler import compile_scene_rules, scene_rules_diagnostics
from app.time_skip import build_time_skip_contract


SCENE_WRITER_TOOL_FLOW = """
Ты внутри tool-flow. Это не финальный ответ пользователю.

Если processTurn вернул несколько чанков, сначала прочитай все через getTurnPromptChunk и склей их по порядку. RUNTIME_SCENE_RULES — канонический контракт; SCENE_CONTRACT_JSON — state текущего хода.

Создай поля scene_response без комментариев и markdown-обёртки. В applyTurnResult передай их ПЛОСКО рядом с turn_id: без обёртки scene_response и без rendered_text. Railway сам соберёт и сохранит видимый текст из scene.body/header/options/status. После успеха покажи только response.message_to_user. Если ответ Action потерялся, вызови getLastScene; новый processTurn не создавай.
""".strip()

# Backward-compatible public name. The value is compiled from repository rule files,
# never maintained as a second handwritten prompt.
COMPACT_SCENE_WRITER_PROMPT = compile_scene_rules()


def _clip_text(value: Any, limit: int = 520) -> str:
    text = "" if value is None else str(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _clip_list(items: Any, limit_items: int = 6, text_limit: int = 300) -> list[Any]:
    if not isinstance(items, list):
        return []
    return [_compact_dict(x, text_limit=text_limit) if isinstance(x, dict) else _clip_text(x, text_limit) for x in items[:limit_items]]


def _compact_dict(data: dict[str, Any], text_limit: int = 320) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, str):
            result[key] = _clip_text(value, text_limit)
        elif isinstance(value, list):
            result[key] = _clip_list(value, 6, max(160, text_limit // 2))
        elif isinstance(value, dict):
            result[key] = _compact_dict(value, max(160, text_limit // 2))
        else:
            result[key] = value
    return result


def _compact_character_card(card: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": card.get("id"),
        "name": card.get("name"),
        "display_name": card.get("display_name") or card.get("visible_name") or card.get("name_ru"),
        "role": card.get("role"),
        "cast_status": card.get("cast_status"),
        "introduced": card.get("introduced"),
        "known_to_player": card.get("known_to_player"),
        "available_to_scene": card.get("available_to_scene"),
        "appearance": _compact_dict(card.get("appearance", {}) if isinstance(card.get("appearance"), dict) else {"summary": card.get("appearance")}, 180),
        "personality": _compact_dict(card.get("personality", {}) if isinstance(card.get("personality"), dict) else {"summary": card.get("personality")}, 180),
        "goal": _clip_text(card.get("goal"), 180),
        "past_short": _clip_text(card.get("past_short"), 220),
        "habits": _clip_list(card.get("habits"), 3, 100),
        "inner_logic": _compact_dict(card.get("inner_logic", {}) if isinstance(card.get("inner_logic"), dict) else {}, 180),
        "behavior": _compact_dict(card.get("behavior", {}) if isinstance(card.get("behavior"), dict) else {}, 180),
        "speech_profile": _compact_dict(card.get("speech_profile", {}) if isinstance(card.get("speech_profile"), dict) else {}, 160),
        "life_outside_player": _compact_dict(card.get("life_outside_player", {}) if isinstance(card.get("life_outside_player"), dict) else {}, 180),
        "social_triggers": _clip_list(card.get("social_triggers"), 3, 140),
        "skills": _clip_list(card.get("skills"), 4, 100),
        "likes_in_people": _clip_list(card.get("likes_in_people"), 3, 100),
        "dislikes_in_people": _clip_list(card.get("dislikes_in_people"), 3, 100),
        "relationship_triggers": _compact_dict(card.get("relationship_triggers", {}) if isinstance(card.get("relationship_triggers"), dict) else {}, 160),
        "connections": _clip_list(card.get("connections"), 3, 120),
    }


def _compact_contract(contract: dict[str, Any]) -> dict[str, Any]:
    compact = {
        "contract_version": contract.get("contract_version"),
        "session_id": contract.get("session_id"),
        "current_frame": contract.get("current_frame", {}),
        "status_slots": contract.get("status_slots", [])[:2],
        "story_compass": _compact_dict(contract.get("story_compass", {}) if isinstance(contract.get("story_compass"), dict) else {}, 900),
        "director_guidance": _compact_dict(contract.get("director_guidance", {}) if isinstance(contract.get("director_guidance"), dict) else {}, 900),
        "time_skip_request": _compact_dict(contract.get("time_skip_request", {}) if isinstance(contract.get("time_skip_request"), dict) else {}, 900),
        "npc_runtime": _compact_dict(contract.get("npc_runtime", {}) if isinstance(contract.get("npc_runtime"), dict) else {}, 420),
        "scene_candidates": _compact_dict(contract.get("scene_candidates", {}) if isinstance(contract.get("scene_candidates"), dict) else {}, 420),
        "character_creation_request": _compact_dict(
            contract.get("character_creation_request", {})
            if isinstance(contract.get("character_creation_request"), dict)
            else {},
            520,
        ) or None,
        "visible_relationship_pair_ids": contract.get("visible_relationship_pair_ids", []),
        "player_input_rules": contract.get("player_input_rules", {}),
        "maintenance": contract.get("maintenance", {}),
        "future_locks": {
            "do_not_reveal_yet": _clip_list((contract.get("future_locks") or {}).get("do_not_reveal_yet", []), 5, 180),
            "pending_character_seed_count": len(
                (contract.get("future_locks") or {}).get("hidden_character_seeds", [])
                if isinstance((contract.get("future_locks") or {}).get("hidden_character_seeds"), list)
                else []
            ),
        },
        "continuity": _compact_dict(contract.get("continuity", {}) if isinstance(contract.get("continuity"), dict) else {}, 260),
        "memory_chunks": [_compact_dict(i, 220) for i in (contract.get("memory_chunks", []) or [])[-3:] if isinstance(i, dict)],
        "episode_summaries": [_compact_dict(i, 360) for i in (contract.get("episode_summaries", []) or [])[-8:] if isinstance(i, dict)],
    }
    compact["loaded_characters"] = [
        {
            "character_id": i.get("character_id"),
            "display_name": i.get("display_name"),
            "load_reason": i.get("load_reason", []),
            "scene_presence": i.get("scene_presence"),
            "candidate": i.get("candidate"),
            "card": _compact_character_card(i.get("card") if isinstance(i.get("card"), dict) else {}),
        }
        for i in (contract.get("loaded_characters", []) or [])
        if isinstance(i, dict)
    ]
    compact["loaded_relationships"] = [
        {
            "pair_id": i.get("pair_id"),
            "display_label": i.get("display_label"),
            "visible_in_footer": i.get("visible_in_footer", False),
            "may_become_visible_if_candidate_enters": i.get("may_become_visible_if_candidate_enters", False),
            "content": _compact_dict(i.get("content") if isinstance(i.get("content"), dict) else {}, 260),
        }
        for i in (contract.get("loaded_relationships", []) or [])
        if isinstance(i, dict)
    ]
    compact["knowledge_boundaries"] = [
        _compact_dict(i, 220)
        for i in (contract.get("knowledge_boundaries", []) or [])
        if isinstance(i, dict)
    ]
    compact["recent_scene_history"] = [
        {
            "turn": i.get("turn"),
            "summary": _clip_text(i.get("summary"), 350),
            "important_facts": _clip_list(i.get("important_facts", []), 5, 180),
            "witnesses": i.get("witnesses", []),
        }
        for i in (contract.get("recent_scene_history", []) or [])[-2:]
        if isinstance(i, dict)
    ]
    compact["output_requirements"] = {
        "tool_flow": "send turn_id plus flat scene fields to applyTurnResult; omit rendered_text; show response.message_to_user"
    }
    return compact


def build_scene_prompt(scene_contract: dict[str, Any]) -> str:
    contract_json = json.dumps(_compact_contract(scene_contract), ensure_ascii=False, separators=(",", ":"))
    return (
        f"{SCENE_WRITER_TOOL_FLOW}\n\n"
        f"RUNTIME_SCENE_RULES:\n{COMPACT_SCENE_WRITER_PROMPT}\n\n"
        f"SCENE_CONTRACT_JSON:\n{contract_json}"
    )


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
    scene_state = current_frame.get("scene_state") or "debug режим"
    visible_state = status.get("emotional_state", "нейтрально") if isinstance(status, dict) else "нейтрально"
    outfit = current_frame.get("outfit") or "одежда не задана"
    inventory = _as_list_text(current_frame.get("inventory"), "ничего не указано")
    return f"""🎭 {story_title} · {date}
🕒 {time} · 📍 {location}
🌦️ Погода: {weather}
⚙️ Состояние сцены: {scene_state}

✦ {name} · {visible_state}
🧥 {outfit}
◈ При себе: {inventory}

━━━━━━━━━━━━━━━━━━━━

*{name} остаётся в точке: {location}. Последний ввод игрока принят как якорь сцены: {player_input!r}.*

━━━━━━━━━━━━━━━━━━━━

✦ Что можно сделать
Варианты ниже не считаются действием, пока игрок не выбрал.

◈ Остановиться в текущей точке и проверить, кто физически рядом.
◈ Убрать руку от вещей и дать ближайшему NPC сделать следующий шаг.
◈ Сместиться к видимому выходу, не начиная разговор первой.

✦ Что можно сказать

— Продолжим, только без загадок и служебных инструкций.
— Кто сейчас реально рядом, а кто просто делает вид?
— Я не подписывалась быть центром вашего странного собрания.

✦ Мысли

— Если это проверка, она плохо замаскирована под жизнь.
— Кто-то здесь явно знает больше, чем говорит. Ненавижу удобных молчунов.
— Нужно смотреть на людей, а не на красивые подсказки системы.

✦ Состояние
Голод: {status.get('hunger', 'норма') if isinstance(status, dict) else 'норма'}
Усталость: {status.get('fatigue', 'низкая') if isinstance(status, dict) else 'низкая'}
Травмы: {_as_list_text(status.get('injuries'), 'нет') if isinstance(status, dict) else 'нет'}
Эмоциональное состояние: {status.get('emotional_state', 'нейтрально') if isinstance(status, dict) else 'нейтрально'}
Навыки / ресурс: {_as_list_text(status.get('skills'), 'без активного ресурса') if isinstance(status, dict) else 'без активного ресурса'}
Сюжетное давление: не задано
Мистический отклик: не задано

✦ Отношения
Нет активных изменений.

━━━━━━━━━━━━━━━━━━━━"""


def process_turn_gpt_actions(bundle: dict[str, Any], player_input: str) -> dict[str, Any]:
    contract = build_scene_contract(bundle, player_input=player_input)
    prompt = build_scene_prompt(contract)
    rules_diagnostics = scene_rules_diagnostics()
    return {
        "status": "gpt_actions_prompt_ready",
        "scene": None,
        "scene_prompt": prompt,
        "diagnostics": {
            "loaded_character_count": len(contract.get("loaded_characters", [])),
            "loaded_relationship_count": len(contract.get("loaded_relationships", [])),
            "visible_relationship_pair_ids": contract.get("visible_relationship_pair_ids", []),
            "compact_prompt_chars": len(prompt),
            "scene_rules": rules_diagnostics,
            "next_required_action": "call flat applyTurnResult without rendered_text, then show response.message_to_user",
        },
    }


def process_time_skip_gpt_actions(
    bundle: dict[str, Any],
    player_input: str,
    *,
    skip_mode: str,
    unit: str | None = None,
    amount: int | None = None,
) -> dict[str, Any]:
    contract, assessment = build_time_skip_contract(
        bundle,
        player_input=player_input,
        mode=skip_mode,
        unit=unit,
        amount=amount,
    )
    prompt = build_scene_prompt(contract)
    return {
        "status": "time_skip_prompt_ready",
        "scene": None,
        "scene_prompt": prompt,
        "time_skip_request": {
            "mode": skip_mode,
            "unit": assessment.get("unit"),
            "amount": assessment.get("amount"),
            "target_event": assessment.get("target_event"),
            "target_frame_hint": assessment.get("target_frame_hint"),
            "from_frame": {
                "date": (bundle.get("current_state") or {}).get("date"),
                "time": (bundle.get("current_state") or {}).get("time"),
                "location": (bundle.get("current_state") or {}).get("location"),
            },
        },
        "diagnostics": {
            "turn_kind": "time_skip",
            "target_event_id": (assessment.get("target_event") or {}).get("id"),
            "compact_prompt_chars": len(prompt),
            "scene_rules": scene_rules_diagnostics(),
            "next_required_action": "call flat applyTurnResult without rendered_text, then show response.message_to_user",
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
                "visible_state": status.get("emotional_state", "нейтрально") if isinstance(status, dict) else "нейтрально",
                "outfit": current_frame.get("outfit") or "одежда не задана",
                "inventory": _as_list_text(current_frame.get("inventory"), "ничего не указано"),
            },
            "body": "debug_stub",
            "player_options": {
                "thoughts": [
                    "Если это проверка, она плохо замаскирована под жизнь.",
                    "Кто-то здесь явно знает больше, чем говорит.",
                    "Нужно смотреть на людей, а не на подсказки системы.",
                ],
                "dialogue": [
                    "Продолжим, только без загадок и служебных инструкций.",
                    "Кто сейчас реально рядом, а кто просто делает вид?",
                    "Я не подписывалась быть центром вашего странного собрания.",
                ],
                "actions": [
                    "Остановиться в текущей точке и проверить, кто физически рядом.",
                    "Убрать руку от вещей и дать ближайшему NPC сделать следующий шаг.",
                    "Сместиться к видимому выходу, не начиная разговор первой.",
                ],
            },
            "status_panel": {
                "hunger": status.get("hunger", "норма") if isinstance(status, dict) else "норма",
                "fatigue": status.get("fatigue", "низкая") if isinstance(status, dict) else "низкая",
                "injuries": _as_list_text(status.get("injuries"), "нет") if isinstance(status, dict) else "нет",
                "emotional_state": status.get("emotional_state", "нейтрально") if isinstance(status, dict) else "нейтрально",
                "skills": _as_list_text(status.get("skills"), "без активного ресурса") if isinstance(status, dict) else "без активного ресурса",
                "custom": (status.get("custom", []) if isinstance(status, dict) else [])[:2],
            },
            "relationships_panel": [],
            "rendered_text": rendered,
        },
        "summary": "Тестовый ход debug_stub.",
        "important_facts": [],
        "witnesses": current_frame.get("active_character_ids", []),
        "proposed_updates": {
            "scene_state_patch": {"scene_goal": "Продолжить сцену после последнего действия игрока."},
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
            "notes": ["debug_stub"],
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
