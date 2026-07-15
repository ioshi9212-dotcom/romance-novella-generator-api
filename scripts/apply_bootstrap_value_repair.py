from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NORMALIZER = ROOT / "app" / "bootstrap_normalizer.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"missing patch anchor: {label}")
    return text.replace(old, new, 1)


text = NORMALIZER.read_text(encoding="utf-8")

age_helpers = '''\n\nAGE_NUMBER_RE = re.compile(r"(?<!\\d)(\\d{1,3}(?:[.,]\\d+)?)(?!\\d)")\nAGE_UNKNOWN_VALUES = {\n    "", "—", "-", "не указано", "неизвестно", "неизвестен", "unknown", "n/a", "none", "null",\n}\nBOOTSTRAP_PLACEHOLDER_VALUES = {\n    "", "—", "-", "не указано", "старт", "стартовая локация", "начало истории",\n    "начать первую сцену", "открыть первую сцену", "будет уточняться",\n}\n\n\ndef _normalize_age(value: Any) -> int | float | None:\n    if value is None or isinstance(value, bool):\n        return None\n    if isinstance(value, (int, float)):\n        return value\n    if not isinstance(value, str):\n        return None\n    text = " ".join(value.strip().lower().split())\n    if text in AGE_UNKNOWN_VALUES:\n        return None\n    matches = AGE_NUMBER_RE.findall(text)\n    if len(matches) != 1:\n        return None\n    number = float(matches[0].replace(",", "."))\n    return int(number) if number.is_integer() else number\n\n\ndef _is_bootstrap_placeholder(value: Any) -> bool:\n    text = " ".join(str(value or "").strip().lower().split())\n    return text in BOOTSTRAP_PLACEHOLDER_VALUES or any(\n        snippet in text for snippet in ("будет уточняться", "не указано", "placeholder")\n    )\n\n\ndef _normalize_scene_state(current_state: dict[str, Any], story_plan: dict[str, Any]) -> str:\n    raw = _as_str(current_state.get("scene_state"), "")\n    if raw and not _is_bootstrap_placeholder(raw):\n        return raw\n    for candidate in (\n        current_state.get("scene_goal"),\n        story_plan.get("opening_scene_intent"),\n        story_plan.get("protagonist_start"),\n    ):\n        text = _as_str(candidate, "")\n        if text and not _is_bootstrap_placeholder(text):\n            return text\n    return raw or "начало истории"\n'''

text = replace_once(
    text,
    '''def _safe_id(value: Any, fallback: str) -> str:\n''',
    age_helpers + '''\n\ndef _safe_id(value: Any, fallback: str) -> str:\n''',
    "age and scene-state helpers",
)
text = replace_once(
    text,
    '''        "age": card.get("age", "не указано"),\n''',
    '''        "age": _normalize_age(card.get("age")),\n''',
    "character age normalization",
)
text = replace_once(
    text,
    '''    custom = []\n    for index in range(2):\n''',
    '''    custom = []\n    scene_state = _normalize_scene_state(current_state, story_plan)\n    for index in range(2):\n''',
    "scene state computation",
)
text = replace_once(
    text,
    '''        "scene_state": _as_str(current_state.get("scene_state"), "начало истории"),\n''',
    '''        "scene_state": scene_state,\n''',
    "scene state normalization",
)

NORMALIZER.write_text(text, encoding="utf-8")
