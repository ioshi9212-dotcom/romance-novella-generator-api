from __future__ import annotations
from typing import Any
import re


REQUIRED_SAFETY_CHECKS = [
    "used_only_loaded_characters",
    "respected_knowledge_boundaries",
    "no_hidden_future_reveal",
    "no_major_player_character_choice",
    "respected_player_input_order",
    "showed_only_scene_relationships",
    "header_has_no_focus_or_active_list",
]


MAX_FOOTER_NOTE_CHARS = 44


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


def _short_note(value: Any, fallback: str = "норма", limit: int = MAX_FOOTER_NOTE_CHARS) -> str:
    text = _as_str(value, fallback)
    text = re.sub(r"\s+", " ", text).strip(" .;—-")
    # Keep the first clause only. Footer is a dashboard, not a prose explanation.
    for sep in [";", ".", " потому что ", " так как ", " но ", " и "]:
        if sep in text and len(text.split(sep, 1)[0].strip()) >= 6:
            text = text.split(sep, 1)[0].strip()
            break
    if len(text) > limit:
        text = text[: limit - 1].rstrip(" ,;.-") + "…"
    return text or fallback


def _extract_score(text: str) -> int | None:
    match = re.search(r"(\d{1,3})\s*/\s*100", text)
    if match:
        value = int(match.group(1))
        return max(0, min(100, value))
    return None


def _estimate_score(text: str, *, kind: str) -> int:
    t = text.lower().replace("ё", "е")
    found = _extract_score(t)
    if found is not None:
        return found

    if kind == "injuries":
        if any(x in t for x in ["нет", "без", "свежих травм нет"]):
            return 0
        if any(x in t for x in ["шрам", "стар"]):
            return 10
        if any(x in t for x in ["кров", "боль", "трав", "ран"]):
            return 45
        return 0

    high = ["выс", "силь", "остр", "опас", "дав", "паник", "испуг", "актив", "раст", "замет"]
    mid = ["сред", "умерен", "напряж", "насторож", "раздраж", "голод", "устал"]
    low = ["низ", "легк", "лёгк", "слаб", "норма", "споко", "нет"]
    if any(x in t for x in high):
        return 75
    if any(x in t for x in mid):
        return 50
    if any(x in t for x in low):
        return 25
    return 50


def _meter(value: Any, *, kind: str, fallback: str = "норма") -> str:
    raw = _as_str(value, fallback)
    score = _estimate_score(raw, kind=kind)
    note = _short_note(re.sub(r"\d{1,3}\s*/\s*100", "", raw), fallback=fallback)
    return f"{score}/100 — {note}"


def _character_display_map(bundle: dict[str, Any]) -> dict[str, str]:
    characters = bundle.get("characters") or {}
    mapping: dict[str, str] = {}
    for cid, card in characters.items():
        if not isinstance(card, dict):
            continue
        mapping[str(cid)] = str(cid)
        for key in ["name", "display_name", "visible_name", "name_ru", "russian_name"]:
            value = card.get(key)
            if isinstance(value, str) and value.strip():
                mapping[value.strip()] = str(cid)
    return mapping


def _resolve_character_id(value: Any, bundle: dict[str, Any], scene: dict[str, Any]) -> str:
    current_state = bundle.get("current_state") or {}
    player_id = str(current_state.get("player_character_id") or "pc_01")
    text = _as_str(value)

    header = scene.get("header") if isinstance(scene.get("header"), dict) else {}
    player_visible_name = _as_str(header.get("player_name"))
    if text and player_visible_name and text == player_visible_name:
        return player_id

    mapping = _character_display_map(bundle)
    if text in mapping:
        return mapping[text]

    return text


def _normalize_header(scene: dict[str, Any]) -> None:
    header = scene.setdefault("header", {})
    if not isinstance(header, dict):
        scene["header"] = header = {}
    if "story_title" not in header and "title" in header:
        header["story_title"] = header.get("title")
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
        options = {}
        scene["player_options"] = options
    defaults = {
        "thoughts": ["Отметить, что изменилось.", "Сдержать первую реакцию.", "Понять, чего она сейчас хочет."],
        "dialogue": ["Сказать коротко.", "Задать прямой вопрос.", "Промолчать."],
        "actions": ["Проверить важную деталь.", "Сделать следующий шаг.", "Выбрать границу."],
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

    panel["hunger"] = _meter(panel.get("hunger"), kind="hunger", fallback="норма")
    panel["fatigue"] = _meter(panel.get("fatigue"), kind="fatigue", fallback="низкая")
    panel["injuries"] = _meter(panel.get("injuries"), kind="injuries", fallback="нет")
    panel["emotional_state"] = _meter(panel.get("emotional_state"), kind="emotional", fallback="ровно")
    panel["skills"] = _meter(panel.get("skills"), kind="skills", fallback="активны")

    custom = _as_list(panel.get("custom"))
    normalized = []
    for index in range(2):
        item = custom[index] if index < len(custom) else {}
        if not isinstance(item, dict):
            raw_text = _as_str(item)
            if ":" in raw_text:
                label, value = raw_text.split(":", 1)
                item = {"label": label.strip(), "value": value.strip()}
            else:
                item = {"value": raw_text}
        label = _short_note(item.get("label") or item.get("id"), f"Поле истории {index + 1}", 26)
        raw_value = item.get("value")
        normalized.append({
            "id": _as_str(item.get("id") or label, f"story_slot_{index + 1}"),
            "label": label,
            "value": _meter(raw_value, kind="custom", fallback="старт"),
        })
    panel["custom"] = normalized


def _normalize_relationships_panel(scene: dict[str, Any]) -> None:
    panel = _as_list(scene.get("relationships_panel"))
    result = []
    for item in panel:
        if not isinstance(item, dict):
            text = _as_str(item)
            if ":" in text:
                label, value = text.split(":", 1)
            else:
                label, value = "Отношения", text
            result.append({"label": _short_note(label, "Отношения", 28), "value": _meter(value, kind="relationship", fallback="нейтрально")})
            continue
        label = _short_note(item.get("label") or item.get("name") or item.get("pair_id"), "Отношения", 28)
        value = _as_str(item.get("value"))
        if not value:
            bits = []
            for key in ["status", "tension", "trust", "respect", "curiosity", "attachment", "fear"]:
                if item.get(key) is not None:
                    bits.append(f"{key}: {item.get(key)}")
            value = "; ".join(bits) or "без изменений"
        result.append({**item, "label": label, "value": _meter(value, kind="relationship", fallback="нейтрально")})
    scene["relationships_panel"] = result


def _normalize_knowledge_patches(updates: dict[str, Any], bundle: dict[str, Any], scene: dict[str, Any]) -> None:
    result = []
    for patch in _as_list(updates.get("knowledge_patches")):
        if not isinstance(patch, dict):
            continue
        normalized = dict(patch)
        normalized["character_id"] = _resolve_character_id(
            normalized.get("character_id") or normalized.get("who") or normalized.get("name"),
            bundle,
            scene,
        )
        for old_key in ["known", "add", "knows"]:
            if old_key in normalized and "add_knows" not in normalized:
                normalized["add_knows"] = _as_list(normalized.get(old_key))
        if "source" in normalized and "source_in_scene" not in normalized:
            normalized["source_in_scene"] = _as_str(normalized.get("source"))
        if normalized.get("add_knows") and "add_recent_memories" not in normalized:
            normalized["add_recent_memories"] = [_as_str(x) for x in _as_list(normalized["add_knows"]) if _as_str(x)][:5]
        for old_key in ["who", "name", "add", "source", "known", "knows"]:
            normalized.pop(old_key, None)
        result.append(normalized)
    updates["knowledge_patches"] = result


def _normalize_relationship_patches(updates: dict[str, Any]) -> None:
    result = []
    for patch in _as_list(updates.get("relationship_patches")):
        if not isinstance(patch, dict):
            continue
        normalized = dict(patch)
        if not normalized.get("pair_id"):
            result.append(normalized)
            continue
        normalized["change_type"] = _as_str(normalized.get("change_type"))
        normalized["entry"] = _as_str(normalized.get("entry"))
        normalized["reason"] = _as_str(normalized.get("reason"))
        normalized["source_in_scene"] = _as_str(normalized.get("source_in_scene") or normalized.get("source"))
        normalized.pop("source", None)
        result.append(normalized)
    updates["relationship_patches"] = result


def _extract_body_from_rendered_text(rendered_text: str) -> str:
    text = _as_str(rendered_text)
    if not text:
        return ""
    delimiter = "━━━━━━━━━━━━━━━━━━━━"
    if delimiter in text:
        parts = text.split(delimiter)
        if len(parts) >= 3:
            return parts[1].strip()
        if len(parts) >= 2:
            candidate = parts[1]
            if "✦ Что можно сделать" in candidate:
                candidate = candidate.split("✦ Что можно сделать", 1)[0]
            return candidate.strip()
    candidate = text
    if "✦ Что можно сделать" in candidate:
        candidate = candidate.split("✦ Что можно сделать", 1)[0]
    return candidate.strip()


def _format_dialogue_line(line: str) -> str:
    raw = line.strip()
    if not raw or raw.startswith("*") and "—" not in raw:
        return line
    match = re.match(r"^\*\*?([^*—]+?)\*\*?\s*—\s*(.+)$", raw) or re.match(r"^([^—]+?)\s*—\s*(.+)$", raw)
    if not match:
        return line
    speaker = match.group(1).strip(" *")
    content = match.group(2).strip()
    aside = ""
    aside_match = re.search(r"\s*\(([^()]*)\)\s*$", content)
    if aside_match:
        aside = aside_match.group(1).strip()
        content = content[: aside_match.start()].rstrip()
    if aside:
        return f"**{speaker}** — {content} *({aside})*"
    return f"**{speaker}** — {content}"


def _format_dialogue_in_body(body: str) -> str:
    """Normalize dialogue inside body and remove old separate 'Диалог:' heading."""
    if not body:
        return body
    body = re.sub(r"\n\s*Диалог:\s*\n", "\n", body)
    lines = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        if stripped.startswith("**"):
            fixed = re.sub(r"(\*\*[^*]+\*\*\s+—\s+.*?)(\s*)\(([^()]*)\)\s*$", r"\1 *(\3)*", stripped)
            fixed = re.sub(r"\*\(([^()]*)\)\*", r"*(\1)*", fixed)
            lines.append(fixed)
            continue
        m = re.match(r"^([А-ЯЁA-Z][А-Яа-яЁёA-Za-z0-9 .'\-]{0,40})\s+—\s+(.+?)(?:\s*\(([^()]*)\))?$", stripped)
        if m and not stripped.lower().startswith(("снаружи ", "за дверью ", "изнутри ", "в проходе ", "потом ")):
            speaker, speech, aside = m.groups()
            speech = speech.strip()
            if speech and not speech.endswith((".", "!", "?", "…")):
                speech += "."
            if aside:
                lines.append(f"**{speaker.strip()}** — {speech} *({aside.strip()})*")
            else:
                lines.append(f"**{speaker.strip()}** — {speech}")
            continue
        fixed = re.sub(
            r"^(Снаружи|За дверью|Изнутри|В проходе)\s+(.{0,80}?)\s+(говорит|произносит|отвечает|спрашивает)\s+—\s+(.+)$",
            lambda mm: f"{mm.group(1)} {mm.group(2)} {mm.group(3)}. {mm.group(4)}",
            stripped,
            flags=re.I,
        )
        lines.append(fixed)
    return "\n".join(lines).strip()


def _looks_like_full_rendered_text(text: str, body: str, header: dict[str, Any]) -> bool:
    if not text:
        return False
    if "🎭" not in text or "🕒" not in text or "✦ Что можно сделать" not in text:
        return False
    if _as_str(header.get("player_name"), "") and _as_str(header.get("player_name")) not in text:
        return False
    body_excerpt = body[:80].strip()
    if body_excerpt and len(body.strip()) >= 500 and body_excerpt not in text:
        return False
    return True


def _build_rendered_text(scene: dict[str, Any]) -> str:
    header = scene["header"]
    body = _format_dialogue_in_body(_as_str(scene.get("body"), ""))
    options = scene["player_options"]
    status = scene["status_panel"]
    relationships = scene.get("relationships_panel") or []
    thoughts = options.get("thoughts", [])[:3]
    dialogue = options.get("dialogue", [])[:3]
    actions = options.get("actions", [])[:3]
    custom = status.get("custom", [])[:2]

    rel_lines = []
    for rel in relationships:
        if isinstance(rel, dict):
            rel_lines.append(f"{_as_str(rel.get('label'), 'Отношения')}: {_as_str(rel.get('value'), '50/100 — нейтрально')}")
        else:
            rel_lines.append(_as_str(rel))
    if not rel_lines:
        rel_lines = ["Нет активных изменений."]

    return f"""🎭 {header['story_title']} · {header['date']}
🕒 {header['time']} · 📍 {header['location']}
🌦️ Погода: {header['weather']}
⚙️ Состояние сцены: {header['scene_state']}

✦ {header['player_name']} · {header['visible_state']}
🧥 {header['outfit']}
◈ {header['inventory']}

━━━━━━━━━━━━━━━━━━━━

{body}

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


def _has_full_visible_scene(rendered_text: str) -> bool:
    text = _as_str(rendered_text)
    required = ["🎭", "🕒", "📍", "━━━━━━━━━━━━━━━━━━━━", "✦ Что можно сделать", "✦ Что можно сказать", "✦ Мысли", "✦ Состояние", "✦ Отношения"]
    return all(marker in text for marker in required)


def _normalize_safety_checks(result: dict[str, Any], scene: dict[str, Any]) -> None:
    checks = result.setdefault("safety_checks", {})
    if not isinstance(checks, dict):
        checks = {}
        result["safety_checks"] = checks
    rendered_text = _as_str(scene.get("rendered_text"))
    body = _as_str(scene.get("body"))
    can_fill_missing = _has_full_visible_scene(rendered_text) and len(body) >= 500
    for key in REQUIRED_SAFETY_CHECKS:
        if key not in checks and can_fill_missing:
            checks[key] = True
    checks["notes"] = _as_list(checks.get("notes"))


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

    top_level_rendered = _as_str(result.get("rendered_text"))
    if top_level_rendered and not _as_str(scene.get("rendered_text")):
        scene["rendered_text"] = top_level_rendered

    _normalize_header(scene)
    _normalize_options(scene)
    _normalize_status_panel(scene)
    _normalize_relationships_panel(scene)

    current_body = _as_str(scene.get("body"), "")
    current_rendered = _as_str(scene.get("rendered_text"), "")
    if len(current_body) < 500 and current_rendered:
        extracted_body = _extract_body_from_rendered_text(current_rendered)
        if len(extracted_body) > len(current_body):
            current_body = extracted_body

    scene["body"] = _format_dialogue_in_body(current_body)
    # Always rebuild the visible frame from normalized scene fields. This keeps
    # the prose body but makes footer/dialogue formatting deterministic and short.
    scene["rendered_text"] = _build_rendered_text(scene)

    result["player_input"] = _as_str(result.get("player_input"))

    updates = result.setdefault("proposed_updates", {})
    if not isinstance(updates, dict):
        updates = {}
        result["proposed_updates"] = updates
    if not isinstance(updates.setdefault("scene_state_patch", {}), dict):
        updates["scene_state_patch"] = {}
    _normalize_knowledge_patches(updates, bundle, scene)
    _normalize_relationship_patches(updates)
    updates["new_or_updated_characters"] = _as_list(updates.get("new_or_updated_characters"))

    _normalize_safety_checks(result, scene)
    return result
