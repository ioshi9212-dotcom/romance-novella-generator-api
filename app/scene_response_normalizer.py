from __future__ import annotations
from typing import Any


def _as_list(value: Any) -> list[Any]:
    if value is None: return []
    if isinstance(value, list): return value
    if isinstance(value, tuple): return list(value)
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    return [value]


def _as_str(value: Any, fallback: str = "") -> str:
    if value is None: return fallback
    if isinstance(value, str): return value.strip() or fallback
    if isinstance(value, list):
        parts = [str(x).strip() for x in value if str(x).strip()]
        return ", ".join(parts) or fallback
    if isinstance(value, dict):
        parts = [f"{k}: {v}" for k, v in value.items() if str(v).strip()]
        return "; ".join(parts) or fallback
    return str(value).strip() or fallback


def _character_display_map(bundle: dict[str, Any]) -> dict[str, str]:
    characters = bundle.get("characters") or {}
    current_state = bundle.get("current_state") or {}
    player_id = current_state.get("player_character_id") or "pc_01"
    mapping: dict[str, str] = {}
    for cid, card in characters.items():
        if not isinstance(card, dict): continue
        mapping[str(cid)] = str(cid)
        for key in ["name", "display_name", "visible_name", "name_ru", "russian_name"]:
            value = card.get(key)
            if isinstance(value, str) and value.strip():
                mapping[value.strip()] = str(cid)
    mapping.setdefault("героиня", str(player_id))
    mapping.setdefault("Героиня", str(player_id))
    return mapping


def _resolve_character_id(value: Any, bundle: dict[str, Any], scene: dict[str, Any]) -> str:
    current_state = bundle.get("current_state") or {}
    player_id = current_state.get("player_character_id") or "pc_01"
    text = _as_str(value)
    header = scene.get("header") if isinstance(scene.get("header"), dict) else {}
    player_visible_name = _as_str(header.get("player_name"))
    if text and player_visible_name and text == player_visible_name:
        return str(player_id)
    mapping = _character_display_map(bundle)
    if text in mapping: return mapping[text]
    active_ids = current_state.get("active_character_ids") or []
    if len(active_ids) == 1: return str(active_ids[0])
    return str(player_id)


def _normalize_header(scene: dict[str, Any]) -> None:
    header = scene.setdefault("header", {})
    if not isinstance(header, dict):
        scene["header"] = header = {}
    if "story_title" not in header and "title" in header:
        header["story_title"] = header.get("title")
    defaults = {
        "story_title": "Новая новелла", "date": "День 1", "time": "время не задано",
        "location": "локация не задана", "weather": "атмосфера не задана",
        "scene_state": "сцена началась", "player_name": "Героиня",
        "visible_state": "нейтрально", "outfit": "одежда не задана", "inventory": ""
    }
    for key, fallback in defaults.items():
        header[key] = _as_str(header.get(key), fallback)


def _normalize_options(scene: dict[str, Any]) -> None:
    raw = scene.get("player_options")
    if isinstance(raw, list):
        options = {"actions": raw, "dialogue": [], "thoughts": []}
        scene["player_options"] = options
    elif isinstance(raw, dict):
        options = raw
    else:
        options = {}; scene["player_options"] = options
    defaults = {
        "thoughts": ["Отметить, что изменилось.", "Сдержать первую реакцию.", "Понять, чего она сейчас хочет."],
        "dialogue": ["Сказать коротко и холодно.", "Задать прямой вопрос.", "Промолчать, но показать реакцию."],
        "actions": ["Проверить деталь, которая изменилась.", "Сделать шаг к следующему конфликту.", "Выбрать, как встретить давление."],
    }
    for key, fallback in defaults.items():
        items = [_as_str(x) for x in _as_list(options.get(key)) if _as_str(x)]
        while len(items) < 3:
            items.append(fallback[len(items)])
        options[key] = items[:3]


def _normalize_status_panel(scene: dict[str, Any]) -> None:
    panel = scene.setdefault("status_panel", {})
    if not isinstance(panel, dict):
        panel = {}; scene["status_panel"] = panel
    panel["hunger"] = _as_str(panel.get("hunger"), "норма")
    panel["fatigue"] = _as_str(panel.get("fatigue"), "не указано")
    panel["injuries"] = _as_str(panel.get("injuries"), "нет")
    panel["emotional_state"] = _as_str(panel.get("emotional_state"), "не указано")
    panel["skills"] = _as_str(panel.get("skills"), "без активного ресурса")
    custom = _as_list(panel.get("custom")); normalized = []
    for index in range(2):
        item = custom[index] if index < len(custom) else {}
        if not isinstance(item, dict): item = {"value": item}
        label = _as_str(item.get("label") or item.get("id"), f"Поле истории {index + 1}")
        normalized.append({"id": _as_str(item.get("id") or label, f"story_slot_{index + 1}"), "label": label, "value": _as_str(item.get("value"), "не задано")})
    panel["custom"] = normalized


def _normalize_relationships_panel(scene: dict[str, Any]) -> None:
    panel = _as_list(scene.get("relationships_panel")); result = []
    for item in panel:
        if not isinstance(item, dict):
            result.append({"label": "Отношения", "value": _as_str(item)}); continue
        label = _as_str(item.get("label") or item.get("name") or item.get("pair_id"), "Отношения")
        value = _as_str(item.get("value"))
        if not value:
            bits = []
            for key in ["status", "tension", "trust", "respect", "curiosity", "attachment", "fear"]:
                if item.get(key) is not None: bits.append(f"{key}: {item.get(key)}")
            value = "; ".join(bits) or "без изменений"
        normalized = dict(item); normalized["label"] = label; normalized["value"] = value
        result.append(normalized)
    scene["relationships_panel"] = result


def _normalize_knowledge_patches(updates: dict[str, Any], bundle: dict[str, Any], scene: dict[str, Any]) -> None:
    result = []
    for patch in _as_list(updates.get("knowledge_patches")):
        if not isinstance(patch, dict): continue
        normalized = dict(patch)
        normalized["character_id"] = _resolve_character_id(normalized.get("character_id") or normalized.get("who") or normalized.get("name"), bundle, scene)
        for old_key in ["known", "add", "knows"]:
            if old_key in normalized and "add_knows" not in normalized:
                normalized["add_knows"] = _as_list(normalized.get(old_key))
        if "source" in normalized and "source_in_scene" not in normalized:
            normalized["source_in_scene"] = _as_str(normalized.get("source"), "scene")
        normalized["source_in_scene"] = _as_str(normalized.get("source_in_scene"), "scene")
        normalized["reason"] = _as_str(normalized.get("reason"), "Важное знание появилось в текущей сцене.")
        if normalized.get("add_knows") and "add_recent_memories" not in normalized:
            normalized["add_recent_memories"] = [_as_str(x) for x in _as_list(normalized["add_knows"]) if _as_str(x)][:5]
        for old_key in ["who", "name", "add", "source", "known", "knows"]:
            normalized.pop(old_key, None)
        result.append(normalized)
    updates["knowledge_patches"] = result


def _normalize_relationship_patches(updates: dict[str, Any]) -> None:
    result = []
    for patch in _as_list(updates.get("relationship_patches")):
        if not isinstance(patch, dict): continue
        normalized = dict(patch)
        if not normalized.get("pair_id"): continue
        normalized["change_type"] = _as_str(normalized.get("change_type"), "scene_change")
        normalized["entry"] = _as_str(normalized.get("entry"), "отношение изменилось после текущей сцены")
        normalized["reason"] = _as_str(normalized.get("reason"), "Реакция на событие текущей сцены.")
        normalized["source_in_scene"] = _as_str(normalized.get("source_in_scene") or normalized.get("source"), "scene")
        normalized.pop("source", None)
        result.append(normalized)
    updates["relationship_patches"] = result


def _looks_like_full_rendered_text(text: str, body: str, header: dict[str, Any]) -> bool:
    if not text: return False
    if "🎭" not in text or "🕒" not in text or "✦ Что можно сделать" not in text: return False
    body_excerpt = body[:80].strip()
    if body_excerpt and body_excerpt not in text: return False
    if _as_str(header.get("player_name"), "") and _as_str(header.get("player_name")) not in text: return False
    return True


def _build_rendered_text(scene: dict[str, Any]) -> str:
    header = scene["header"]; body = _as_str(scene.get("body"), "")
    options = scene["player_options"]; status = scene["status_panel"]; relationships = scene.get("relationships_panel") or []
    thoughts = options.get("thoughts", [])[:3]; dialogue = options.get("dialogue", [])[:3]; actions = options.get("actions", [])[:3]
    custom = status.get("custom", [])[:2]
    dialogue_block = scene.get("dialogue_text") or "Диалог:\n*Вслух пока ничего не сказано. Пауза тоже работает как ответ.*"
    rel_lines = []
    for rel in relationships:
        if isinstance(rel, dict): rel_lines.append(f"{_as_str(rel.get('label'), 'Отношения')}: {_as_str(rel.get('value'), 'без изменений')}")
        else: rel_lines.append(str(rel))
    if not rel_lines: rel_lines = ["Нет активных изменений."]
    return f"""🎭 {header['story_title']} · {header['date']}
🕒 {header['time']} · 📍 {header['location']}
🌦️ Погода: {header['weather']}
⚙️ Состояние сцены: {header['scene_state']}

✦ {header['player_name']} · {header['visible_state']}
🧥 {header['outfit']}
◈ {header['inventory']}

━━━━━━━━━━━━━━━━━━━━

{body}

{dialogue_block}

━━━━━━━━━━━━━━━━━━━━

✦ Что можно сделать
◈ {actions[0]}
◈ {actions[1]}
◈ {actions[2]}

✦ Что можно сказать
— {dialogue[0]}
— {dialogue[1]}
— {dialogue[2]}

✦ Мысли
— {thoughts[0]}
— {thoughts[1]}
— {thoughts[2]}

✦ Состояние
Голод: {status['hunger']}
Усталость: {status['fatigue']}
Травмы: {status['injuries']}
Эмоциональное состояние: {status['emotional_state']}
Навыки / ресурс: {status['skills']}
{custom[0]['label']}: {custom[0]['value']}
{custom[1]['label']}: {custom[1]['value']}

✦ Отношения
{chr(10).join(rel_lines)}

━━━━━━━━━━━━━━━━━━━━"""


def normalize_scene_response(data: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict): data = {}
    result = dict(data)
    result["response_version"] = result.get("response_version") or "novella.scene_response.v1"
    result["summary"] = _as_str(result.get("summary"), "Сцена сыграна.")
    result["important_facts"] = _as_list(result.get("important_facts"))
    result["witnesses"] = _as_list(result.get("witnesses"))
    scene = result.setdefault("scene", {})
    if not isinstance(scene, dict): scene = {}; result["scene"] = scene
    _normalize_header(scene); _normalize_options(scene); _normalize_status_panel(scene); _normalize_relationships_panel(scene)
    scene["body"] = _as_str(scene.get("body"), "")
    current_rendered = _as_str(scene.get("rendered_text"), "")
    scene["rendered_text"] = current_rendered if _looks_like_full_rendered_text(current_rendered, scene["body"], scene["header"]) else _build_rendered_text(scene)
    result["player_input"] = _as_str(result.get("player_input"), _as_str((bundle.get("current_state") or {}).get("last_player_input"), ""))
    updates = result.setdefault("proposed_updates", {})
    if not isinstance(updates, dict): updates = {}; result["proposed_updates"] = updates
    if not isinstance(updates.setdefault("scene_state_patch", {}), dict): updates["scene_state_patch"] = {}
    _normalize_knowledge_patches(updates, bundle, scene); _normalize_relationship_patches(updates)
    updates["new_or_updated_characters"] = _as_list(updates.get("new_or_updated_characters"))
    checks = result.setdefault("safety_checks", {})
    if not isinstance(checks, dict): checks = {}; result["safety_checks"] = checks
    for key in ["used_only_loaded_characters", "respected_knowledge_boundaries", "no_hidden_future_reveal", "no_major_player_character_choice", "respected_player_input_order", "showed_only_scene_relationships", "header_has_no_focus_or_active_list"]:
        checks[key] = bool(checks.get(key, True))
    checks["notes"] = _as_list(checks.get("notes"))
    return result
