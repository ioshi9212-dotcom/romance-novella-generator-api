from __future__ import annotations

from pathlib import Path


path = Path("app/character_profiles.py")
text = path.read_text(encoding="utf-8")
if "def _normalise_connections(" in text:
    print("Bootstrap compatibility repair already applied.")
    raise SystemExit(0)

list_marker = '''def _list(value: Any, fallback: list[str], *, minimum: int = 1) -> list[str]:
    if isinstance(value, list):
        cleaned = [str(item).strip() for item in value if str(item).strip() and not _placeholder(item)]
        if len(cleaned) >= minimum:
            return cleaned
    elif isinstance(value, str) and value.strip() and not _placeholder(value):
        return [value.strip()]
    return list(fallback)


def infer_cast_status'''

helpers = '''def _list(value: Any, fallback: list[str], *, minimum: int = 1) -> list[str]:
    if isinstance(value, list):
        cleaned = [str(item).strip() for item in value if str(item).strip() and not _placeholder(item)]
        if len(cleaned) >= minimum:
            return cleaned
    elif isinstance(value, str) and value.strip() and not _placeholder(value):
        return [value.strip()]
    return list(fallback)


DIRECTIONAL_SCORE_KEYS = {
    "trust",
    "attachment",
    "attraction",
    "respect",
    "resentment",
    "fear",
    "jealousy",
    "dependency",
    "protectiveness",
}
DIRECTIONAL_SCORE_ALIASES = {
    "romantic_interest": "attraction",
    "presence_pull": "attraction",
}


def _normalise_connections(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    source = value if isinstance(value, list) else [value]
    result: list[dict[str, Any]] = []
    for item in source:
        if isinstance(item, dict):
            if item:
                result.append(dict(item))
            continue
        text = str(item or "").strip()
        if text:
            result.append({"relation": "connection", "summary": text})
    return result


def _normalise_social_triggers(value: Any, fallback_reaction: str) -> list[dict[str, Any]]:
    defaults = [
        {
            "behavior": "человек отвечает прямо и выдерживает последствия своих слов",
            "interpretation": "ему можно верить хотя бы в текущем вопросе",
            "usual_reaction": "становится немного открытее, но не меняет отношение мгновенно",
        },
        {
            "behavior": "человек уклоняется, исчезает или меняет правила без объяснения",
            "interpretation": "от него что-то скрывают или им пытаются управлять",
            "usual_reaction": fallback_reaction,
        },
    ]
    source = value if isinstance(value, list) else ([] if value is None else [value])
    repaired: list[dict[str, Any]] = []
    for index, item in enumerate(source[:6]):
        fallback = defaults[min(index, 1)]
        if isinstance(item, dict):
            trigger = dict(item)
            trigger["behavior"] = _text(
                item.get("behavior") or item.get("trigger") or item.get("visible_behavior") or item.get("situation"),
                fallback["behavior"],
            )
            trigger["interpretation"] = _text(
                item.get("interpretation") or item.get("meaning") or item.get("reads_as") or item.get("assumption"),
                fallback["interpretation"],
            )
            trigger["usual_reaction"] = _text(
                item.get("usual_reaction") or item.get("reaction") or item.get("response"),
                fallback["usual_reaction"],
            )
        else:
            trigger = {
                "behavior": _text(item, fallback["behavior"]),
                "interpretation": fallback["interpretation"],
                "usual_reaction": fallback["usual_reaction"],
            }
        repaired.append(trigger)
    while len(repaired) < 2:
        repaired.append(dict(defaults[len(repaired)]))
    return repaired[:6]


def _normalise_directional_scores(value: Any) -> dict[str, int | float]:
    source = value if isinstance(value, dict) else {}
    result: dict[str, int | float] = {}

    def add_score(target_key: str, raw_value: Any) -> None:
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            return
        bounded = max(0, min(100, raw_value))
        result[target_key] = int(bounded) if float(bounded).is_integer() else float(bounded)

    for key in DIRECTIONAL_SCORE_KEYS:
        if key in source:
            add_score(key, source[key])
    for old_key, target_key in DIRECTIONAL_SCORE_ALIASES.items():
        if target_key not in result and old_key in source:
            add_score(target_key, source[old_key])
    return result


def _normalise_relationship_score_blocks(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    for direction_key in ("a_to_b", "b_to_a"):
        block = result.get(direction_key)
        if not isinstance(block, dict):
            continue
        repaired_block = dict(block)
        repaired_block["scores"] = _normalise_directional_scores(block.get("scores"))
        result[direction_key] = repaired_block
    return result


def infer_cast_status'''

if text.count(list_marker) != 1:
    raise SystemExit("Could not locate _list insertion marker")
text = text.replace(list_marker, helpers, 1)

habits_marker = '    result["habits"] = _list(result.get("habits"), template["habits"])\n\n    social_triggers = result.get("social_triggers")\n'
habits_replacement = '    result["habits"] = _list(result.get("habits"), template["habits"])\n    result["connections"] = _normalise_connections(result.get("connections"))\n\n    social_triggers = result.get("social_triggers")\n'
if text.count(habits_marker) != 1:
    raise SystemExit("Could not locate connections repair marker")
text = text.replace(habits_marker, habits_replacement, 1)

old_social = '''    social_triggers = result.get("social_triggers")
    if not isinstance(social_triggers, list) or len([item for item in social_triggers if isinstance(item, dict)]) < 2:
        social_triggers = [
            {
                "behavior": "человек отвечает прямо и выдерживает последствия своих слов",
                "interpretation": "ему можно верить хотя бы в текущем вопросе",
                "usual_reaction": "становится немного открытее, но не меняет отношение мгновенно",
            },
            {
                "behavior": "человек уклоняется, исчезает или меняет правила без объяснения",
                "interpretation": "от него что-то скрывают или им пытаются управлять",
                "usual_reaction": result["behavior"]["conflict_style"],
            },
        ]
    result["social_triggers"] = social_triggers
'''
new_social = '''    result["social_triggers"] = _normalise_social_triggers(
        result.get("social_triggers"),
        result["behavior"]["conflict_style"],
    )
'''
if text.count(old_social) != 1:
    raise SystemExit("Could not locate social trigger repair block")
text = text.replace(old_social, new_social, 1)

relationships_marker = '    relationships = data.get("relationships") if isinstance(data.get("relationships"), dict) else {}\n    for character_id, card in enriched.items():\n'
relationships_replacement = '''    raw_relationships = data.get("relationships") if isinstance(data.get("relationships"), dict) else {}
    relationships = {
        str(relationship_id): _normalise_relationship_score_blocks(relationship)
        for relationship_id, relationship in raw_relationships.items()
        if isinstance(relationship, dict)
    }
    for character_id, card in enriched.items():
'''
if text.count(relationships_marker) != 1:
    raise SystemExit("Could not locate relationship repair marker")
text = text.replace(relationships_marker, relationships_replacement, 1)

path.write_text(text, encoding="utf-8")
print("Applied bootstrap compatibility repair.")
