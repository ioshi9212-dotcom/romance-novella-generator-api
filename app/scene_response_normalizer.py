from __future__ import annotations

from typing import Any


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    return [value]


def _as_str(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    if isinstance(value, str):
        return value.strip() or fallback
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
        if not isinstance(card, dict):
            continue
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
    if text in mapping:
        return mapping[text]
    active_ids = current_state.get("active_character_ids") or []
    if len(active_ids) == 1:
        return str(active_ids[0])
    return str(player_id)


def _normalize_header(scene: dict[str, Any]) -> None:
    header = scene.setdefault("header", {})
    if not isinstance(header, dict):
        scene["header"] = header = {}
    defaults = {
        "story_title": "Новая новелла",
        "date": "День 1",
        "time": "время не задано",
        "location": "локация не задана",
        "weather": "атмосфера не задана",
        "scene_state": "сцена началась",
        "player_name": "Героиня",
        "visible_state": "нейтрально",
        "outfit": "одежда не задана",
        "inventory": "",
    }
    header["inventory"] = _as_str(header.get("inventory"), "")
    for key, fallback in defaults.items():
        header[key] = _as_str(header.get(key), fallback)


def _normalize_options(scene: dict[str, Any]) -> None:
    options = scene.setdefault("player_options", {})
    if not isinstance(options, dict):
        options = {}
        scene["player_options"] = options
    defaults = {
        "thoughts": ["Отметить главное.", "Сдержать реакцию.", "Подумать, что делать дальше."],
        "dialogue": ["Продолжим.", "Что происходит?", "Не сейчас."],
        "actions": ["Осмотреться.", "Проверить вещи.", "Сделать следующий шаг."],
    }
    for key, fallback in defaults.items():
        items = [_as_str(x) for x in _as_list(options.get(key)) if _as_str(x)]
        while len(items) < 3:
            items.append(fallback[len(items)])
        options[key] = items[:3]


def _normalize_status_panel(scene: dict[str, Any]) -> None:
    panel = scene.setdefault("status_panel", {})
    if not isinstance(panel, dict):
        panel = {}
        scene["status_panel"] = panel
    panel["hunger"] = _as_str(panel.get("hunger"), "норма")
    panel["fatigue"] = _as_str(panel.get("fatigue"), "не указано")
    panel["injuries"] = _as_str(panel.get("injuries"), "нет")
    panel["emotional_state"] = _as_str(panel.get("emotional_state"), "не указано")
    panel["skills"] = _as_str(panel.get("skills"), "без активного ресурса")
    custom = _as_list(panel.get("custom"))
    normalized = []
    for index in range(2):
        item = custom[index] if index < len(custom) else {}
        if not isinstance(item, dict):
            item = {"value": item}
        label = _as_str(item.get("label") or item.get("id"), f"Поле истории {index + 1}")
        normalized.append({"id": _as_str(item.get("id") or label, f"story_slot_{index + 1}"), "label": label, "value": _as_str(item.get("value"), "не задано")})
    panel["custom"] = normalized


def _normalize_relationships_panel(scene: dict[str, Any]) -> None:
    panel = _as_list(scene.get("relationships_panel"))
    result = []
    for item in panel:
        if not isinstance(item, dict):
            result.append({"label": "Отношения", "value": _as_str(item)})
            continue
        label = _as_str(item.get("label") or item.get("name") or item.get("pair_id"), "Отношения")
        value = _as_str(item.get("value"))
        if not value:
            bits = []
            for key in ["status", "tension", "trust", "respect", "curiosity", "attachment", "fear"]:
                if item.get(key) is not None:
                    bits.append(f"{key}: {item.get(key)}")
            value = "; ".join(bits) or "без изменений"
        normalized = dict(item)
        normalized["label"] = label
        normalized["value"] = value
        result.append(normalized)
    scene["relationships_panel"] = result


def _normalize_knowledge_patches(updates: dict[str, Any], bundle: dict[str, Any], scene: dict[str, Any]) -> None:
    result = []
    for patch in _as_list(updates.get("knowledge_patches")):
        if not isinstance(patch, dict):
            continue
        normalized = dict(patch)
        normalized["character_id"] = _resolve_character_id(normalized.get("character_id") or normalized.get("who") or normalized.get("name"), bundle, scene)
        if "add" in normalized and "add_knows" not in normalized:
            normalized["add_knows"] = _as_list(normalized.get("add"))
        if "source" in normalized and "source_in_scene" not in normalized:
            normalized["source_in_scene"] = _as_str(normalized.get("source"), "scene")
        normalized["source_in_scene"] = _as_str(normalized.get("source_in_scene"), "scene")
        normalized["reason"] = _as_str(normalized.get("reason"), "Важное знание/наблюдение появилось в текущей сцене.")
        if normalized.get("add_knows") and "add_recent_memories" not in normalized:
            normalized["add_recent_memories"] = [_as_str(x) for x in _as_list(normalized.get("add_knows")) if _as_str(x)][:5]
        for old_key in ["who", "name", "add", "source"]:
            normalized.pop(old_key, None)
        result.append(normalized)
    updates["knowledge_patches"] = result


def _normalize_relationship_patches(updates: dict[str, Any]) -> None:
    result = []
    for patch in _as_list(updates.get("relationship_patches")):
        if not isinstance(patch, dict) or not patch.get("pair_id"):
            continue
        normalized = dict(patch)
        normalized["change_type"] = _as_str(normalized.get("change_type"), "scene_change")
        normalized["entry"] = _as_str(normalized.get("entry"), "отношение изменилось после текущей сцены")
        normalized["reason"] = _as_str(normalized.get("reason"), "Реакция на событие текущей сцены.")
        normalized["source_in_scene"] = _as_str(normalized.get("source_in_scene") or normalized.get("source"), "scene")
        normalized.pop("source", None)
        result.append(normalized)
    updates["relationship_patches"] = result


def normalize_scene_response(data: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        data = {}
    result = dict(data)
    result["response_version"] = result.get("response_version") or "novella.scene_response.v1"
    result["summary"] = _as_str(result.get("summary"), "Сцена сыграна.")
    result["important_facts"] = _as_list(result.get("important_facts"))
    result["witnesses"] = _as_list(result.get("witnesses"))
    scene = result.setdefault("scene", {})
    if not isinstance(scene, dict):
        scene = {}
        result["scene"] = scene
    _normalize_header(scene)
    _normalize_options(scene)
    _normalize_status_panel(scene)
    _normalize_relationships_panel(scene)
    scene["body"] = _as_str(scene.get("body"), "")
    scene["rendered_text"] = _as_str(scene.get("rendered_text") or scene.get("body"), scene["body"])
    result["player_input"] = _as_str(result.get("player_input"), _as_str((bundle.get("current_state") or {}).get("last_player_input"), ""))
    updates = result.setdefault("proposed_updates", {})
    if not isinstance(updates, dict):
        updates = {}
        result["proposed_updates"] = updates
    if not isinstance(updates.get("scene_state_patch"), dict):
        updates["scene_state_patch"] = {}
    else:
        updates.setdefault("scene_state_patch", {})
    _normalize_knowledge_patches(updates, bundle, scene)
    _normalize_relationship_patches(updates)
    updates["new_or_updated_characters"] = _as_list(updates.get("new_or_updated_characters"))
    checks = result.setdefault("safety_checks", {})
    if not isinstance(checks, dict):
        checks = {}
        result["safety_checks"] = checks
    for key in ["used_only_loaded_characters", "respected_knowledge_boundaries", "no_hidden_future_reveal", "no_major_player_character_choice", "respected_player_input_order", "showed_only_scene_relationships", "header_has_no_focus_or_active_list"]:
        checks[key] = bool(checks.get(key, True))
    checks["notes"] = _as_list(checks.get("notes"))
    return result
