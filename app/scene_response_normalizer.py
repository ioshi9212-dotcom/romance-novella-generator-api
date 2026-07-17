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


# -----------------------------------------------------------------------------
# Basic coercion helpers
# -----------------------------------------------------------------------------

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
    for sep in [";", ".", " потому что ", " так как ", " но ", " и "]:
        if sep in text and len(text.split(sep, 1)[0].strip()) >= 6:
            text = text.split(sep, 1)[0].strip()
            break
    if len(text) > limit:
        text = text[: limit - 1].rstrip(" ,;.-") + "…"
    return text or fallback


def _clean_footer_option(value: Any) -> str:
    text = _as_str(value)
    text = re.sub(r"^\s*(?:[—\-•◈]+)\s*", "", text).strip()
    return text


# -----------------------------------------------------------------------------
# Footer options
# -----------------------------------------------------------------------------

_DIALOGUE_OPTION_TRIGGERS = (
    "сказать", "спросить", "попросить", "предупредить", "ответить", "крикнуть",
    "позвать", "передать", "объяснить", "согласиться", "отказаться", "приказать",
    "потребовать", "пошутить", "буркнуть", "произнести", "напомнить",
)

_THOUGHT_OPTION_TRIGGERS = (
    "подумать", "решить", "вспомнить", "отметить", "понять", "прикинуть",
    "заметить про себя", "удержать в голове",
)

_BANNED_FALLBACK_PARTS = (
    "проверить важную деталь",
    "сделать следующий физический шаг",
    "удержать безопасную дистанцию",
    "сказать коротко и прямо",
    "задать один конкретный вопрос",
    "отметить, что изменилось",
    "сдержать первую реакцию",
)


def _option_kind(text: str, preferred: str) -> str:
    t = text.lower().replace("ё", "е").strip()
    if not t:
        return preferred
    if t.startswith(("если ", "почему ", "что если ", "надо ", "теперь ", "кажется ")):
        return "thoughts"
    if any(t.startswith(word) for word in _DIALOGUE_OPTION_TRIGGERS):
        return "dialogue"
    if any(word in t[:80] for word in [" сказать ", " спросить ", " попросить ", " передать "]):
        return "dialogue"
    if any(t.startswith(word) for word in _THOUGHT_OPTION_TRIGGERS):
        return "thoughts"
    return preferred


def _normalize_options(scene: dict[str, Any]) -> None:
    raw = scene.get("player_options")
    if isinstance(raw, list):
        raw_options = {"actions": raw, "dialogue": [], "thoughts": []}
    elif isinstance(raw, dict):
        raw_options = raw
    else:
        raw_options = {}

    buckets = {"actions": [], "dialogue": [], "thoughts": []}
    for preferred in ("actions", "dialogue", "thoughts"):
        for raw_item in _as_list(raw_options.get(preferred)):
            text = _clean_footer_option(raw_item)
            if not text:
                continue
            low = text.lower().replace("ё", "е")
            # Do not keep backend-prohibited generic placeholders if GPT returns them.
            if any(part in low for part in _BANNED_FALLBACK_PARTS):
                continue
            kind = _option_kind(text, preferred)
            buckets[kind].append(text)

    defaults = {
        "actions": [
            "Остаться на месте и осмотреть ближайший видимый предмет.",
            "Сместиться к ближайшей безопасной точке, не начиная разговор.",
            "Убрать руки от вещей и дать ситуации секунду измениться.",
        ],
        "dialogue": [
            "Что именно вы от меня сейчас хотите?",
            "Говорите нормально. Без загадок.",
            "Я не буду угадывать за вас.",
        ],
        "thoughts": [
            "Что здесь изменилось после моего действия?",
            "Кто сейчас давит сильнее остальных?",
            "Лучше смотреть на людей, а не на странные совпадения.",
        ],
    }

    options: dict[str, list[str]] = {}
    for key in ("actions", "dialogue", "thoughts"):
        seen: list[str] = []
        for item in buckets[key]:
            clean = _clean_footer_option(item)
            if clean and clean not in seen:
                seen.append(clean)
        while len(seen) < 3:
            fallback = defaults[key][len(seen)]
            if fallback not in seen:
                seen.append(fallback)
            else:
                seen.append(f"{fallback}.")
        options[key] = seen[:3]
    scene["player_options"] = options


# -----------------------------------------------------------------------------
# Status footer
# -----------------------------------------------------------------------------

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
        if any(x in t for x in ["нет", "без", "свежих травм нет"]) and not any(x in t for x in ["боль", "болит", "жжет", "жж", "штамп"]):
            return 0
        if any(x in t for x in ["шрам", "стар"]):
            return 10
        if any(x in t for x in ["штамп", "рук", "кисть", "ладон", "жжет", "жж", "ломит", "кров", "боль", "болит", "трав", "ран", "ожог"]):
            return 55
        return 0

    high = ["выс", "силь", "остр", "опас", "дав", "паник", "испуг", "страх", "бою", "тревог", "актив", "раст", "замет", "предел"]
    mid = ["сред", "умерен", "напряж", "насторож", "раздраж", "голод", "устал"]
    low = ["низ", "легк", "лёгк", "слаб", "норма", "споко", "нет", "ровно"]
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


def _preview_bundle_with_scene_status_patch(bundle: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    """Build the post-patch frame used by the visible header and footer.

    StateUpdater persists proposed_updates after normalization. Rendering from
    this merged frame prevents the model-authored header from disagreeing with
    the state that the backend is about to save.
    """
    if not isinstance(updates, dict):
        return bundle
    scene_patch = updates.get("scene_state_patch")
    if not isinstance(scene_patch, dict):
        return bundle
    preview = dict(bundle)
    current_state = dict(bundle.get("current_state") or {})
    for key, value in scene_patch.items():
        if key == "status" and isinstance(value, dict):
            state_status = current_state.get("status") if isinstance(current_state.get("status"), dict) else {}
            current_state["status"] = {**state_status, **value}
        elif value is not None:
            current_state[key] = value
    preview["current_state"] = current_state
    return preview


def _status_source_value(bundle: dict[str, Any], scene: dict[str, Any], key: str) -> Any:
    current_state = bundle.get("current_state") or {}
    state_status = current_state.get("status") if isinstance(current_state.get("status"), dict) else {}
    panel = scene.get("status_panel") if isinstance(scene.get("status_panel"), dict) else {}
    if key in state_status:
        return state_status.get(key)
    return panel.get(key)


def _coerce_custom_slot(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and ":" in value:
        label, raw_value = value.split(":", 1)
        return {"label": label.strip(), "value": raw_value.strip()}
    if value:
        return {"value": value}
    return {}


def _merged_status_custom(bundle: dict[str, Any], scene: dict[str, Any]) -> list[dict[str, Any]]:
    current_state = bundle.get("current_state") or {}
    story_plan = bundle.get("story_plan") or {}
    state_status = current_state.get("status") if isinstance(current_state.get("status"), dict) else {}
    panel = scene.get("status_panel") if isinstance(scene.get("status_panel"), dict) else {}

    state_custom = _as_list(state_status.get("custom"))
    panel_custom = _as_list(panel.get("custom"))
    slots = _as_list(story_plan.get("status_slots"))

    result: list[dict[str, Any]] = []
    for index in range(2):
        slot = slots[index] if index < len(slots) and isinstance(slots[index], dict) else {}
        st = state_custom[index] if index < len(state_custom) and isinstance(state_custom[index], dict) else {}
        pn = _coerce_custom_slot(panel_custom[index] if index < len(panel_custom) else {})
        fallback_label = "Сюжетное давление" if index == 0 else "Мистический отклик"
        panel_label = pn.get("label") if not str(pn.get("label", "")).startswith("Поле истории") else ""
        label = st.get("label") or slot.get("label") or panel_label or fallback_label
        value = st.get("value")
        if value is None:
            value = pn.get("value")
        if value is None:
            value = slot.get("initial_value", "низкий")
        result.append({
            "id": _as_str(st.get("id") or slot.get("id") or pn.get("id") or f"story_slot_{index + 1}"),
            "label": _short_note(label, fallback_label, 30),
            "value": value,
        })
    return result


def _normalize_status_panel(scene: dict[str, Any], bundle: dict[str, Any]) -> None:
    panel = scene.setdefault("status_panel", {})
    if not isinstance(panel, dict):
        panel = {}
        scene["status_panel"] = panel

    panel["hunger"] = _meter(_status_source_value(bundle, scene, "hunger"), kind="hunger", fallback="норма")
    panel["fatigue"] = _meter(_status_source_value(bundle, scene, "fatigue"), kind="fatigue", fallback="низкая")
    panel["injuries"] = _meter(_status_source_value(bundle, scene, "injuries"), kind="injuries", fallback="нет")
    panel["emotional_state"] = _meter(_status_source_value(bundle, scene, "emotional_state"), kind="emotional", fallback="ровно")
    panel["skills"] = _meter(_status_source_value(bundle, scene, "skills"), kind="skills", fallback="активны")

    normalized = []
    for index, item in enumerate(_merged_status_custom(bundle, scene)):
        normalized.append({
            "id": _as_str(item.get("id"), f"story_slot_{index + 1}"),
            "label": _short_note(item.get("label"), "Сюжет", 30),
            "value": _meter(item.get("value"), kind="custom", fallback="низкий"),
        })
    while len(normalized) < 2:
        idx = len(normalized)
        normalized.append({
            "id": f"story_slot_{idx + 1}",
            "label": "Сюжетное давление" if idx == 0 else "Мистический отклик",
            "value": "25/100 — низкий",
        })
    panel["custom"] = normalized[:2]


# -----------------------------------------------------------------------------
# Relationships footer
# -----------------------------------------------------------------------------

_EVENT_LABEL_WORDS = (
    "пакет", "жакет", "двер", "телефон", "маршрут", "снаружи", "внутрь", "вош", "выш",
    "принес", "забрал", "отдал", "избав", "сделал", "сказал",
)


def _display_name_for_id(bundle: dict[str, Any], character_id: str) -> str:
    characters = bundle.get("characters") or {}
    card = characters.get(character_id) if isinstance(characters, dict) else None
    if isinstance(card, dict):
        for key in ("display_name", "visible_name", "name_ru", "russian_name", "name"):
            value = card.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return character_id


def _relationship_participants(pair_id_value: str, entry: dict[str, Any]) -> tuple[str | None, str | None]:
    a = entry.get("character_a") or entry.get("a") or entry.get("left")
    b = entry.get("character_b") or entry.get("b") or entry.get("right")
    if a and b:
        return str(a), str(b)
    if "__" in pair_id_value:
        left, right = pair_id_value.split("__", 1)
        return left, right
    return None, None


def _relationship_score(entry: dict[str, Any]) -> int:
    scores = entry.get("scores") if isinstance(entry.get("scores"), dict) else {}
    for key in ("overall", "relationship", "trust", "respect", "attachment", "curiosity"):
        value = scores.get(key, entry.get(key))
        try:
            if value is not None:
                return max(0, min(100, int(float(value))))
        except Exception:
            pass
    for key in ("tension", "fear"):
        value = scores.get(key, entry.get(key))
        try:
            if value is not None:
                return max(0, min(100, 100 - int(float(value))))
        except Exception:
            pass
    return 50


def _relationship_note(entry: dict[str, Any]) -> str:
    for key in ("status", "dynamic", "current_state", "label", "visible_label"):
        value = _as_str(entry.get(key))
        if value:
            note = _short_note(value, "нейтрально", 28)
            low = note.lower().replace("ё", "е")
            if not any(word in low for word in _EVENT_LABEL_WORDS):
                return note

    scores = entry.get("scores") if isinstance(entry.get("scores"), dict) else {}
    trust = scores.get("trust", entry.get("trust"))
    tension = scores.get("tension", entry.get("tension"))
    try:
        if tension is not None and int(float(tension)) >= 70:
            return "острое напряжение"
        if trust is not None and int(float(trust)) >= 70:
            return "устойчивое доверие"
        if trust is not None and int(float(trust)) <= 25:
            return "низкое доверие"
    except Exception:
        pass
    return "нейтрально"


def _state_relationships_panel(bundle: dict[str, Any], scene: dict[str, Any], updates: dict[str, Any] | None = None) -> list[dict[str, str]]:
    relationships = bundle.get("relationships") or {}
    current_state = bundle.get("current_state") or {}
    player_id = str(current_state.get("player_character_id") or "pc_01")
    active = [str(x) for x in _as_list(current_state.get("active_character_ids")) if str(x)]
    visible_ids = {player_id, *active}
    if not active:
        visible_ids.add(player_id)

    patched_pair_ids: set[str] = set()
    if isinstance(updates, dict):
        for patch in _as_list(updates.get("relationship_patches")):
            if isinstance(patch, dict) and patch.get("pair_id"):
                patched_pair_ids.add(str(patch.get("pair_id")))

    result: list[dict[str, str]] = []
    for pid, entry in relationships.items():
        if not isinstance(entry, dict):
            continue
        a, b = _relationship_participants(str(pid), entry)
        if not a or not b:
            continue
        in_scene = a in visible_ids and b in visible_ids
        directly_touched = str(pid) in patched_pair_ids
        if not in_scene and not directly_touched:
            continue

        if a == player_id:
            label = _display_name_for_id(bundle, b)
        elif b == player_id:
            label = _display_name_for_id(bundle, a)
        else:
            label = f"{_display_name_for_id(bundle, a)} ↔ {_display_name_for_id(bundle, b)}"
        result.append({
            "label": _short_note(label, "Отношения", 30),
            "value": f"{_relationship_score(entry)}/100 — {_relationship_note(entry)}",
        })

    if result:
        return result[:4]

    panel = _as_list(scene.get("relationships_panel"))
    sanitized: list[dict[str, str]] = []
    for item in panel[:3]:
        if isinstance(item, dict):
            label = _short_note(item.get("label") or item.get("name") or item.get("pair_id"), "Отношения", 30)
            raw_value = _as_str(item.get("value") or item.get("status") or item.get("dynamic"))
        else:
            text = _as_str(item)
            label, raw_value = text.split(":", 1) if ":" in text else ("Отношения", text)
            label = _short_note(label, "Отношения", 30)
        note = _relationship_note({"status": raw_value})
        sanitized.append({"label": label, "value": f"{_estimate_score(raw_value, kind='relationship')}/100 — {note}"})
    return sanitized


def _normalize_relationships_panel(scene: dict[str, Any], bundle: dict[str, Any], updates: dict[str, Any] | None = None) -> None:
    scene["relationships_panel"] = _state_relationships_panel(bundle, scene, updates)


# -----------------------------------------------------------------------------
# Header, body, patches, rendered text
# -----------------------------------------------------------------------------

def _normalize_header(scene: dict[str, Any], bundle: dict[str, Any]) -> None:
    header = scene.setdefault("header", {})
    if not isinstance(header, dict):
        scene["header"] = header = {}
    if "story_title" not in header and "title" in header:
        header["story_title"] = header.get("title")
    current_state = bundle.get("current_state") if isinstance(bundle.get("current_state"), dict) else {}
    story_plan = bundle.get("story_plan") if isinstance(bundle.get("story_plan"), dict) else {}
    session = bundle.get("session") if isinstance(bundle.get("session"), dict) else {}
    characters = bundle.get("characters") if isinstance(bundle.get("characters"), dict) else {}
    player_id = str(current_state.get("player_character_id") or "")
    player_card = characters.get(player_id) if isinstance(characters.get(player_id), dict) else {}

    session_title = _as_str(session.get("title"))
    if session_title and session_title != "Untitled novella":
        header["story_title"] = session_title
    elif _as_str(story_plan.get("title")):
        header["story_title"] = _as_str(story_plan.get("title"))

    state_fields = {
        "date": "date",
        "time": "time",
        "location": "location",
        "weather": "weather",
        "scene_state": "scene_state",
        "outfit": "outfit",
        "inventory": "inventory",
    }
    for header_key, state_key in state_fields.items():
        state_value = current_state.get(state_key)
        if state_key in current_state and state_value is not None and state_value != "":
            header[header_key] = current_state.get(state_key)

    for name_key in ("display_name", "visible_name", "name_ru", "russian_name", "name"):
        if _as_str(player_card.get(name_key)):
            header["player_name"] = _as_str(player_card.get(name_key))
            break
    status = current_state.get("status") if isinstance(current_state.get("status"), dict) else {}
    emotional_state = status.get("emotional_state")
    if emotional_state is not None and emotional_state != "":
        header["visible_state"] = status.get("emotional_state")
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


def _resolve_character_id(value: Any, bundle: dict[str, Any], scene: dict[str, Any]) -> str:
    current_state = bundle.get("current_state") or {}
    player_id = str(current_state.get("player_character_id") or "pc_01")
    text = _as_str(value)
    header = scene.get("header") if isinstance(scene.get("header"), dict) else {}
    if text and text == _as_str(header.get("player_name")):
        return player_id
    characters = bundle.get("characters") or {}
    if isinstance(characters, dict):
        for cid, card in characters.items():
            if not isinstance(card, dict):
                continue
            names = [card.get(k) for k in ("name", "display_name", "visible_name", "name_ru", "russian_name")]
            if text in [x for x in names if isinstance(x, str) and x.strip()]:
                return str(cid)
    return text


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


def _format_dialogue_in_body(body: str) -> str:
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

    while len(thoughts) < 3:
        thoughts.append("Лучше пока не делать вид, что всё понятно.")
    while len(dialogue) < 3:
        dialogue.append("Говорите яснее.")
    while len(actions) < 3:
        actions.append("Остаться на месте и осмотреть ближайшую деталь.")
    while len(custom) < 2:
        custom.append({"label": "Сюжет", "value": "25/100 — низкий"})

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
Варианты ниже не считаются действием, пока игрок не выбрал.

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
    # Self-review flags are diagnostics supplied by the scene writer. Never
    # manufacture successful checks from formatting markers.
    checks["notes"] = _as_list(checks.get("notes"))


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------

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

    updates = result.setdefault("proposed_updates", {})
    if not isinstance(updates, dict):
        updates = {}
        result["proposed_updates"] = updates
    for key in ("scene_state_patch", "continuity_patch", "director_bible_patches"):
        # GPT occasionally emits [] for an empty patch. Empty means no change;
        # normalize it before strict schema validation instead of rejecting an
        # otherwise valid, already-written scene.
        if not isinstance(updates.get(key), dict):
            updates[key] = {}
    for key in (
        "relationship_patches",
        "knowledge_patches",
        "npc_state_patches",
        "new_or_updated_characters",
    ):
        value = updates.get(key)
        if isinstance(value, list):
            updates[key] = value
        elif isinstance(value, dict) and value:
            updates[key] = [value]
        else:
            updates[key] = []

    status_bundle = _preview_bundle_with_scene_status_patch(bundle, updates)
    _normalize_header(scene, status_bundle)
    _normalize_options(scene)
    _normalize_status_panel(scene, status_bundle)

    current_body = _as_str(scene.get("body"), "")
    current_rendered = _as_str(scene.get("rendered_text"), "")
    if len(current_body) < 500 and current_rendered:
        extracted_body = _extract_body_from_rendered_text(current_rendered)
        if len(extracted_body) > len(current_body):
            current_body = extracted_body
    scene["body"] = _format_dialogue_in_body(current_body)
    scene["rendered_text"] = _build_rendered_text(scene)

    result["player_input"] = _as_str(result.get("player_input"))

    _normalize_knowledge_patches(updates, bundle, scene)
    _normalize_relationship_patches(updates)
    _normalize_relationships_panel(scene, status_bundle, updates)

    scene["rendered_text"] = _build_rendered_text(scene)
    _normalize_safety_checks(result, scene)
    return result
