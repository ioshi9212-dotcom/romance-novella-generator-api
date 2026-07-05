from __future__ import annotations

from typing import Any
import re

CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def _latinize(value: str, fallback: str) -> str:
    text = (value or "").strip()
    if not text:
        return fallback
    out: list[str] = []
    for ch in text:
        low = ch.lower()
        if low in TRANSLIT:
            part = TRANSLIT[low]
            out.append(part.capitalize() if ch.isupper() else part)
        elif ch.isascii():
            out.append(ch)
        elif ch in {" ", "-", "_", "'"}:
            out.append(ch)
    result = "".join(out)
    result = re.sub(r"[^A-Za-z0-9 _'\-]", "", result).strip()
    return result or fallback


def _as_list(value: Any, fallback: list[Any] | None = None) -> list[Any]:
    if value is None:
        return fallback or []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else (fallback or [])
    if isinstance(value, dict):
        return [value]
    return [value]


def _as_str(value: Any, fallback: str = "—") -> str:
    if value is None:
        return fallback
    if isinstance(value, str):
        return value.strip() or fallback
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts = [str(x).strip() for x in value if str(x).strip()]
        return ", ".join(parts) or fallback
    if isinstance(value, dict):
        parts = [f"{k}: {v}" for k, v in value.items() if str(v).strip()]
        return "; ".join(parts) or fallback
    return str(value).strip() or fallback


def _safe_id(value: Any, fallback: str) -> str:
    text = _latinize(_as_str(value, fallback), fallback).lower().strip()
    allowed: list[str] = []
    for ch in text:
        if ch.isalnum() or ch == "_":
            allowed.append(ch)
        elif ch in {" ", "-", "."}:
            allowed.append("_")
    result = "".join(allowed).strip("_")
    return result or fallback


def _pair_id(a: str, b: str) -> str:
    left, right = sorted([a, b])
    return f"{left}__{right}"


def _normalize_name(card: dict[str, Any], character_id: str) -> tuple[str, str | None]:
    raw = _as_str(card.get("name"), f"Generated {character_id.replace('_', ' ').title()}")
    visible = None
    if CYRILLIC_RE.search(raw):
        visible = raw
        raw = _latinize(raw, f"Generated {character_id.replace('_', ' ').title()}")
    for key in ["display_name", "visible_name", "name_ru", "russian_name"]:
        value = card.get(key)
        if isinstance(value, str) and value.strip():
            visible = value.strip()
            break
    if len(raw.split()) < 2:
        raw = f"{raw} Vale" if raw else f"Generated {character_id.replace('_', ' ').title()}"
    return raw, visible


def _normalize_appearance(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return {
            "height": _as_str(value.get("height"), "не указано"),
            "build": _as_str(value.get("build"), "не указано"),
            "hair": _as_str(value.get("hair"), "не указано"),
            "eyes": _as_str(value.get("eyes"), "не указано"),
            "face": _as_str(value.get("face"), "не указано"),
            "style": _as_str(value.get("style"), "не указано"),
        }
    text = _as_str(value, "не указано")
    return {"height": "не указано", "build": "не указано", "hair": text, "eyes": text, "face": "не указано", "style": "не указано"}


def _normalize_personality(card: dict[str, Any]) -> dict[str, Any]:
    personality = card.get("personality")
    traits = _as_list(card.get("traits"))
    if isinstance(personality, dict):
        return {
            "core": _as_list(personality.get("core"), traits or ["закрытый характер"]),
            "flaws": _as_list(personality.get("flaws"), ["не показывает слабость"]),
            "speech": _as_str(personality.get("speech"), "живая, узнаваемая речь"),
        }
    if isinstance(personality, list):
        traits = personality + traits
    elif isinstance(personality, str):
        traits = [personality] + traits
    return {"core": traits or ["закрытый характер"], "flaws": ["не показывает слабость"], "speech": "живая, узнаваемая речь"}


def _normalize_character(card: Any, character_id: str, role_fallback: str = "npc") -> dict[str, Any]:
    if not isinstance(card, dict):
        card = {"name": f"Generated {character_id.replace('_', ' ').title()}"}
    technical_name, visible_name = _normalize_name(card, character_id)
    role = _as_str(card.get("role"), role_fallback)
    normalized = {
        **card,
        "id": character_id,
        "character_id": character_id,
        "name": technical_name,
        "role": role,
        "age": card.get("age", "не указано"),
        "introduced": bool(card.get("introduced", True)),
        "known_to_player": bool(card.get("known_to_player", role == "player_character")),
        "locked": bool(card.get("locked", True)),
        "appearance": _normalize_appearance(card.get("appearance")),
        "personality": _normalize_personality(card),
        "goal": _as_str(card.get("goal"), "личная цель будет уточняться сценами"),
        "past_short": _as_str(card.get("past_short"), _as_str(card.get("background"), "прошлое будет уточняться сценами")),
        "habits": _as_list(card.get("habits"), ["заметная привычка будет уточняться сценами"]),
        "likes_in_people": _as_list(card.get("likes_in_people"), ["честность в действиях"]),
        "dislikes_in_people": _as_list(card.get("dislikes_in_people"), ["давление и ложь"]),
        "relationship_triggers": card.get("relationship_triggers") if isinstance(card.get("relationship_triggers"), dict) else {
            "improves_when": ["видит последовательные поступки"],
            "worsens_when": ["видит давление, ложь или манипуляцию"],
        },
        "skills": _as_list(card.get("skills"), []),
        "connections": _as_list(card.get("connections"), []),
    }
    if visible_name:
        normalized["display_name"] = visible_name
    normalized.pop("traits", None)
    normalized.pop("background", None)
    return normalized


def _normalize_story_plan(story_plan: Any, data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(story_plan, dict):
        story_plan = {}
    act_structure = story_plan.get("act_structure")
    if not isinstance(act_structure, list) or not act_structure:
        act_structure = ["старт", "развитие", "выбор"]
    normalized_acts = []
    for index, act in enumerate(act_structure[:4], start=1):
        if isinstance(act, dict):
            normalized_acts.append({
                "act": act.get("act", index),
                "goal": _as_str(act.get("goal"), _as_str(act.get("title"), f"Акт {index}")),
                "must_happen": _as_list(act.get("must_happen"), ["развить конфликт"]),
                "must_not_resolve_yet": _as_list(act.get("must_not_resolve_yet"), ["главный конфликт"]),
            })
        else:
            normalized_acts.append({"act": index, "goal": _as_str(act, f"Акт {index}"), "must_happen": ["развить конфликт"], "must_not_resolve_yet": ["главный конфликт"]})
    character_arcs = story_plan.get("character_arcs")
    if isinstance(character_arcs, list):
        character_arcs = {f"arc_{i + 1}": {"start_point": _as_str(item), "pressure": "будет уточняться", "possible_direction": "без финального закрытия"} for i, item in enumerate(character_arcs)}
    elif not isinstance(character_arcs, dict):
        protagonist_id = data.get("protagonist_id") or (data.get("protagonist") or {}).get("id") or "pc_01"
        character_arcs = {protagonist_id: {"start_point": "входит в историю под давлением", "pressure": "внешнее давление и внутреннее выгорание", "possible_direction": "выстроить границы без мгновенного исцеления"}}
    relationship_focus = story_plan.get("relationship_focus")
    if isinstance(relationship_focus, str):
        relationship_focus = [{"pair_id": "primary_pair", "starting_dynamic": relationship_focus, "slow_burn_rule": "не решать отношения сразу"}]
    elif isinstance(relationship_focus, dict):
        relationship_focus = [relationship_focus]
    elif not isinstance(relationship_focus, list):
        relationship_focus = []
    slots_list = _as_list(story_plan.get("status_slots"))
    defaults = [("story_slot_1", "Напряжение", "внутреннее/внешнее давление", "старт"), ("story_slot_2", "Скрытый слой", "приближение мистического/сюжетного слоя", "старт")]
    normalized_slots = []
    for index in range(2):
        fallback_id, fallback_label, fallback_desc, fallback_value = defaults[index]
        slot = slots_list[index] if index < len(slots_list) else {}
        if isinstance(slot, dict):
            normalized_slots.append({
                "id": _safe_id(slot.get("id") or slot.get("label"), fallback_id),
                "label": _as_str(slot.get("label") or slot.get("id"), fallback_label),
                "description": _as_str(slot.get("description"), fallback_desc),
                "initial_value": _as_str(slot.get("initial_value") or slot.get("value"), fallback_value),
            })
        else:
            text = _as_str(slot, fallback_label)
            normalized_slots.append({"id": _safe_id(text, fallback_id), "label": text, "description": fallback_desc, "initial_value": fallback_value})
    return {
        **story_plan,
        "genre": _as_str(story_plan.get("genre") or data.get("genre"), "романс/драма"),
        "language": _as_str(story_plan.get("language") or data.get("language"), "ru"),
        "tone": _as_str(story_plan.get("tone") or data.get("tone"), "взрослый, живой"),
        "setting_summary": _as_str(story_plan.get("setting_summary") or (data.get("setting") or {}).get("description"), "сеттинг будет уточняться"),
        "main_premise": _as_str(story_plan.get("main_premise"), "героиня входит в конфликт, который меняет привычную жизнь"),
        "protagonist_start": _as_str(story_plan.get("protagonist_start"), "персонаж игрока на старте под давлением"),
        "player_goal": _as_str(story_plan.get("player_goal"), "сохранить себя и разобраться в происходящем"),
        "central_conflict": _as_str(story_plan.get("central_conflict"), "внутренний выбор против внешнего давления"),
        "central_question": _as_str(story_plan.get("central_question"), "что героиня выберет, когда привычный контроль перестанет работать"),
        "opening_scene_intent": _as_str(story_plan.get("opening_scene_intent"), "открыть первую сцену и дать первый meaningful beat"),
        "act_structure": normalized_acts,
        "character_arcs": character_arcs,
        "relationship_focus": relationship_focus,
        "status_slots": normalized_slots,
        "open_threads": _as_list(story_plan.get("open_threads"), []),
        "forbidden_drift": _as_list(story_plan.get("forbidden_drift"), []),
        "current_story_position": _as_str(story_plan.get("current_story_position"), "act_1_start"),
    }


def _normalize_relationships(relationships: Any, characters: dict[str, Any], protagonist_id: str) -> dict[str, Any]:
    if not isinstance(relationships, dict):
        return {}
    result: dict[str, Any] = {}
    for _, rel in relationships.items():
        if not isinstance(rel, dict):
            continue
        a = rel.get("character_a") or rel.get("from") or rel.get("a") or protagonist_id
        b = rel.get("character_b") or rel.get("to") or rel.get("b")
        if not b:
            for cid in characters:
                if cid != a:
                    b = cid
                    break
        if not a or not b or a == b:
            continue
        pid = _pair_id(str(a), str(b))
        result[pid] = {
            **rel,
            "pair_id": pid,
            "character_a": str(a),
            "character_b": str(b),
            "type": _as_str(rel.get("type"), "relationship"),
            "status": _as_str(rel.get("status") or rel.get("dynamics"), "отношения будут уточняться сценами"),
            "scores": rel.get("scores") if isinstance(rel.get("scores"), dict) else {"trust": 30, "tension": 40, "attachment": 20, "respect": 30, "fear": 0, "curiosity": 25},
            "a_view_of_b": rel.get("a_view_of_b") if isinstance(rel.get("a_view_of_b"), dict) else {"summary": "восприятие будет уточняться", "current_assumption": "может ошибаться"},
            "b_view_of_a": rel.get("b_view_of_a") if isinstance(rel.get("b_view_of_a"), dict) else {"summary": "восприятие будет уточняться", "current_assumption": "может ошибаться"},
            "shared_history": _as_list(rel.get("shared_history"), []),
            "recent_changes": _as_list(rel.get("recent_changes"), []),
            "open_threads": _as_list(rel.get("open_threads"), []),
        }
    return result


def _normalize_knowledge(knowledge: Any, characters: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    source = knowledge if isinstance(knowledge, dict) else {}
    for cid in characters:
        entry = source.get(cid) if isinstance(source.get(cid), dict) else {}
        result[cid] = {
            "character_id": cid,
            "known_facts": _as_list(entry.get("known_facts"), []),
            "observations": _as_list(entry.get("observations"), []),
            "assumptions": _as_list(entry.get("assumptions"), []),
            "wrong_beliefs": _as_list(entry.get("wrong_beliefs"), []),
            "does_not_know": _as_list(entry.get("does_not_know"), []),
            "must_not_assume": _as_list(entry.get("must_not_assume"), []),
            "recent_memories": _as_list(entry.get("recent_memories"), []),
            "open_questions": _as_list(entry.get("open_questions"), []),
            "knows": _as_list(entry.get("knows"), []),
        }
    if isinstance(source.get("global"), dict):
        result["_global_notes"] = source["global"]
    return result


def _normalize_current_state(current_state: Any, story_plan: dict[str, Any], protagonist_id: str) -> dict[str, Any]:
    if not isinstance(current_state, dict):
        current_state = {}
    status = current_state.get("status") if isinstance(current_state.get("status"), dict) else {}
    slots = story_plan.get("status_slots", [])
    custom_source = _as_list(status.get("custom"), [])
    custom = []
    for index in range(2):
        slot = slots[index] if index < len(slots) else {}
        source = custom_source[index] if index < len(custom_source) else {}
        if not isinstance(source, dict):
            source = {"value": source}
        custom.append({
            "id": _safe_id(source.get("id") or slot.get("id"), f"story_slot_{index + 1}"),
            "label": _as_str(source.get("label") or slot.get("label"), f"Поле истории {index + 1}"),
            "value": _as_str(source.get("value") or source.get("stress") or source.get("detachment") or slot.get("initial_value"), "старт"),
        })
    return {
        **current_state,
        "turn_number": int(current_state.get("turn_number", 0) or 0),
        "date": _as_str(current_state.get("date"), "День 1"),
        "time": _as_str(current_state.get("time"), "время не задано"),
        "location": _as_str(current_state.get("location"), "стартовая локация"),
        "weather": _as_str(current_state.get("weather"), "атмосфера не задана"),
        "scene_state": _as_str(current_state.get("scene_state"), "начало истории"),
        "player_character_id": _as_str(current_state.get("player_character_id") or current_state.get("protagonist_id"), protagonist_id),
        "active_character_ids": _as_list(current_state.get("active_character_ids"), [protagonist_id]),
        "nearby_character_ids": _as_list(current_state.get("nearby_character_ids"), []),
        "scene_goal": _as_str(current_state.get("scene_goal"), story_plan.get("opening_scene_intent", "начать первую сцену")),
        "last_player_input": _as_str(current_state.get("last_player_input"), ""),
        "outfit": _as_str(current_state.get("outfit"), "одежда не задана"),
        "inventory": _as_list(current_state.get("inventory"), []),
        "nearby_items": _as_list(current_state.get("nearby_items"), []),
        "environment": current_state.get("environment") if isinstance(current_state.get("environment"), dict) else {"light": "не указано", "sound": "не указано", "air": "не указано", "details": []},
        "status": {
            "hunger": _as_str(status.get("hunger"), "норма"),
            "fatigue": _as_str(status.get("fatigue"), "средняя"),
            "injuries": _as_list(status.get("injuries"), []),
            "emotional_state": _as_str(status.get("emotional_state"), "нейтрально"),
            "skills": _as_list(status.get("skills"), []),
            "custom": custom,
        },
    }


def normalize_bootstrap_json(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        data = {}
    raw_protagonist = data.get("protagonist") if isinstance(data.get("protagonist"), dict) else {}
    protagonist_id = data.get("protagonist_id") or raw_protagonist.get("id") or raw_protagonist.get("character_id") or "pc_01"
    protagonist_id = _safe_id(protagonist_id, "pc_01")
    raw_characters = data.get("characters") if isinstance(data.get("characters"), dict) else {}
    characters: dict[str, Any] = {}
    if protagonist_id not in raw_characters:
        raw_characters[protagonist_id] = raw_protagonist
    for cid, card in raw_characters.items():
        safe_cid = _safe_id(cid, "npc_01")
        role = "player_character" if safe_cid == protagonist_id else _as_str((card or {}).get("role") if isinstance(card, dict) else None, "npc")
        characters[safe_cid] = _normalize_character(card, safe_cid, role)
    protagonist = characters.get(protagonist_id) or _normalize_character(raw_protagonist, protagonist_id, "player_character")
    protagonist["role"] = "player_character"
    protagonist["introduced"] = True
    protagonist["known_to_player"] = True
    characters[protagonist_id] = protagonist
    story_plan = _normalize_story_plan(data.get("story_plan"), data)
    relationships = _normalize_relationships(data.get("relationships"), characters, protagonist_id)
    knowledge = _normalize_knowledge(data.get("knowledge"), characters)
    current_state = _normalize_current_state(data.get("current_state"), story_plan, protagonist_id)
    return {
        "protagonist": protagonist,
        "characters": characters,
        "relationships": relationships,
        "knowledge": knowledge,
        "story_plan": story_plan,
        "current_state": current_state,
        "npc_state": data.get("npc_state") if isinstance(data.get("npc_state"), dict) else {},
        "future_locks": data.get("future_locks") if isinstance(data.get("future_locks"), dict) else {"hidden_character_seeds": [], "do_not_reveal_yet": []},
        "continuity": data.get("continuity") if isinstance(data.get("continuity"), dict) else {},
        "scene_history": data.get("scene_history") if isinstance(data.get("scene_history"), list) else [],
        "turns": data.get("turns") if isinstance(data.get("turns"), list) else [],
    }
