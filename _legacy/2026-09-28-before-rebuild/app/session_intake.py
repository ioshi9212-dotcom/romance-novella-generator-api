from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any

SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
TRANSLITERATION = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "kh",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "shch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}
PLAN_LIST_FIELDS = (
    "active_threads",
    "character_agendas",
    "event_windows",
    "collision_points",
    "offscreen_events",
    "consequences_without_pov",
    "possible_pov_contacts",
)


class IntakeRepairs:
    def __init__(self) -> None:
        self.notes: list[str] = []

    def add(self, note: str) -> None:
        if note not in self.notes and len(self.notes) < 40:
            self.notes.append(note)


def _dict(value: Any) -> dict[str, Any]:
    return deepcopy(value) if isinstance(value, dict) else {}


def _text(value: Any, fallback: str, *, limit: int | None = None) -> str:
    if isinstance(value, str):
        result = value.strip()
    elif value is None:
        result = ""
    elif isinstance(value, (int, float, bool)):
        result = str(value)
    else:
        result = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    result = result or fallback
    if limit is not None and len(result) > limit:
        result = result[: max(limit - 1, 1)].rstrip() + "…"
    return result


def _list(value: Any, fallback: list[Any] | None = None) -> list[Any]:
    if isinstance(value, list):
        result = deepcopy(value)
    elif isinstance(value, tuple):
        result = list(value)
    elif value in (None, ""):
        result = []
    else:
        result = [deepcopy(value)]
    return result or deepcopy(fallback or [])


def _text_list(
    value: Any,
    fallback: list[str] | None = None,
    *,
    maximum: int,
) -> list[str]:
    result = [
        _text(item, "", limit=3_000)
        for item in _list(value)
        if _text(item, "", limit=3_000)
    ]
    if not result:
        result = list(fallback or [])
    if len(result) > maximum:
        overflow = " ".join(result[maximum - 1 :])
        result = result[: maximum - 1] + [overflow]
    return result


def _nonnegative_int(value: Any, fallback: int = 0) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return fallback


def _transliterate(value: str) -> str:
    result: list[str] = []
    for character in value:
        replacement = TRANSLITERATION.get(character.casefold())
        if replacement is None:
            result.append(character if character.isascii() else "_")
        elif character.isupper():
            result.append(replacement.upper())
        else:
            result.append(replacement)
    return "".join(result)


def _id_candidate(value: Any, prefix: str, index: int) -> str:
    raw = _transliterate(_text(value, ""))
    raw = re.sub(r"[^A-Za-z0-9_-]+", "_", raw).strip("_-").lower()
    if not raw:
        raw = f"{prefix}_{index:03d}"
    elif not raw.startswith(f"{prefix}_"):
        raw = f"{prefix}_{raw}"
    if not raw[0].isalnum():
        raw = f"{prefix}_{raw}"
    return raw[:128].rstrip("_-") or f"{prefix}_{index:03d}"


def _unique_id(value: Any, prefix: str, index: int, used: set[str]) -> str:
    raw = _text(value, "")
    if SAFE_ID_RE.fullmatch(raw) and raw not in used:
        used.add(raw)
        return raw
    base = _id_candidate(raw, prefix, index)
    candidate = base
    suffix = 2
    while candidate in used:
        tail = f"_{suffix}"
        candidate = f"{base[: 128 - len(tail)]}{tail}"
        suffix += 1
    used.add(candidate)
    return candidate


def _bundle_items(value: Any, id_field: str, state_field: str) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [
            deepcopy(item) if isinstance(item, dict) else {state_field: item}
            for item in value
        ]
    if isinstance(value, dict):
        if id_field in value or state_field in value:
            return [deepcopy(value)]
        result: list[dict[str, Any]] = []
        for key, item in value.items():
            if isinstance(item, dict):
                bundle = deepcopy(item)
                bundle.setdefault(id_field, key)
                if state_field not in bundle and id_field != "character_id":
                    bundle = {id_field: key, state_field: bundle}
                elif state_field == "card" and "card" not in bundle:
                    bundle = {id_field: key, "card": bundle}
            else:
                bundle = {id_field: key, state_field: item}
            result.append(bundle)
        return result
    return []


def _normalize_visual_noticeability(value: Any) -> str:
    allowed = {"unremarkable", "pleasant", "attractive", "striking", "distinctive"}
    raw = _text(value, "").casefold()
    if raw in allowed:
        return raw
    if any(marker in raw for marker in ("ярк", "эффект", "striking")):
        return "striking"
    if any(marker in raw for marker in ("привлек", "красив", "attractive")):
        return "attractive"
    if any(marker in raw for marker in ("узнаваем", "особ", "distinct")):
        return "distinctive"
    return "unremarkable"


def _normalize_card(
    raw_value: Any,
    character_id: str,
    index: int,
    repairs: IntakeRepairs,
) -> dict[str, Any]:
    raw = _dict(raw_value)
    identity_raw = raw.get("identity")
    if isinstance(identity_raw, str):
        identity = {"name": identity_raw}
    else:
        identity = _dict(identity_raw)
    name = _text(
        identity.get("name")
        or identity.get("full_name")
        or raw.get("name")
        or raw.get("display_name"),
        f"Персонаж {index}",
        limit=200,
    )
    card_hint = _text(
        raw.get("card_hint") or raw.get("description") or identity.get("role"),
        f"{name}: участник подтверждённой истории.",
        limit=3_000,
    )

    level = _text(raw.get("card_level"), "")
    origin = _text(raw.get("origin"), "")
    if origin not in {"player", "director_setup", "runtime"}:
        origin = (
            "director_setup"
            if level in {"noticeable", "recurring", "important"}
            else "player"
        )
    if level not in {"noticeable", "recurring", "important", "player_defined"}:
        level = "player_defined" if origin == "player" else "important"
    if origin == "player":
        level = "player_defined"
    elif level == "player_defined":
        origin = "player"

    identity = {
        **identity,
        "name": name,
        "age": _text(identity.get("age") or raw.get("age"), "не указано", limit=100),
        "role": _text(identity.get("role") or raw.get("role"), card_hint, limit=500),
        "occupation": _text(
            identity.get("occupation") or raw.get("occupation"),
            "не установлено в исходном каноне",
            limit=500,
        ),
    }

    appearance_value = raw.get("appearance")
    appearance = _dict(appearance_value)
    appearance_summary = _text(
        appearance_value
        if isinstance(appearance_value, str)
        else appearance.get("summary"),
        "внешность следует подтверждённой карточке",
        limit=500,
    )
    distinguishing = _text_list(
        appearance.get("distinguishing_details") or appearance.get("details"),
        [appearance_summary],
        maximum=6,
    )
    appearance = {
        **appearance,
        "height": _text(appearance.get("height"), "не указано", limit=200),
        "build": _text(appearance.get("build"), "не указано", limit=300),
        "hair": _text(appearance.get("hair"), "не указано", limit=300),
        "eyes": _text(appearance.get("eyes"), "не указано", limit=300),
        "face": _text(appearance.get("face"), appearance_summary, limit=500),
        "skin_and_features": _text(
            appearance.get("skin_and_features") or appearance.get("features"),
            "не указано",
            limit=500,
        ),
        "movement_and_mannerisms": _text(
            appearance.get("movement_and_mannerisms") or appearance.get("mannerisms"),
            "движения определяются характером и текущим состоянием",
            limit=700,
        ),
        "clothing_style": _text(
            appearance.get("clothing_style") or appearance.get("style"),
            "одежда соответствует миру и ситуации",
            limit=700,
        ),
        "distinguishing_details": distinguishing,
        "visual_impression": _text(
            appearance.get("visual_impression"), appearance_summary, limit=500
        ),
        "visual_noticeability": _normalize_visual_noticeability(
            appearance.get("visual_noticeability")
        ),
    }

    personality_value = raw.get("personality")
    personality = _dict(personality_value)
    personality_summary = _text(
        personality_value
        if isinstance(personality_value, str)
        else personality.get("summary"),
        card_hint,
        limit=1_000,
    )
    habits = _text_list(
        personality.get("habits") or raw.get("habits"),
        [
            "сохраняет привычную манеру держаться",
            "реагирует согласно текущему состоянию",
        ],
        maximum=6,
    )
    if len(habits) == 1:
        habits.append("реагирует согласно текущему состоянию")
    personality = {
        **personality,
        "outward_mask": _text(
            personality.get("outward_mask"), personality_summary, limit=700
        ),
        "inner_character": _text(
            personality.get("inner_character") or personality.get("core"),
            personality_summary,
            limit=1_000,
        ),
        "strengths": _text_list(
            personality.get("strengths"), ["последовательность"], maximum=8
        ),
        "flaws": _text_list(personality.get("flaws"), ["может ошибаться"], maximum=8),
        "temperament": _text(
            personality.get("temperament"), personality_summary, limit=400
        ),
        "internal_conflict": _text(
            personality.get("internal_conflict"),
            "личные цели могут вступать в конфликт с обстоятельствами",
            limit=1_000,
        ),
        "behavior_under_pressure": _text(
            personality.get("behavior_under_pressure"),
            "действует в соответствии со своим характером, опытом и интересами",
            limit=700,
        ),
        "habits": habits,
        "speech": _text(
            personality.get("speech") or raw.get("speech"),
            "манера речи соответствует характеру и биографии",
            limit=700,
        ),
    }

    preferences_value = raw.get("preferences")
    preferences = _dict(preferences_value)
    preferences = {
        **preferences,
        "likes": _text_list(
            preferences.get("likes"),
            ["то, что согласуется с личными целями"],
            maximum=8,
        ),
        "dislikes": _text_list(
            preferences.get("dislikes"), ["помехи личным целям"], maximum=8
        ),
        "likes_in_people": _text_list(
            preferences.get("likes_in_people"),
            ["черты, соответствующие личным ценностям"],
            maximum=6,
        ),
        "dislikes_in_people": _text_list(
            preferences.get("dislikes_in_people"),
            ["поведение, противоречащее личным ценностям"],
            maximum=6,
        ),
    }

    immediate_goal = _text(
        raw.get("immediate_scene_goal") or raw.get("current_goal"),
        "действовать согласно своей текущей цели и обстоятельствам",
        limit=700,
    )
    goals_value = raw.get("goals")
    goals = _dict(goals_value)
    if isinstance(goals_value, str):
        goals["personal"] = goals_value
    goals = {
        **goals,
        "personal": _text(
            goals.get("personal") or raw.get("goal"), immediate_goal, limit=1_000
        ),
        "immediate": _text(goals.get("immediate"), immediate_goal, limit=700),
        "toward_pov": _text(
            goals.get("toward_pov"),
            "определяется установленными отношениями и знаниями",
            limit=700,
        ),
        "story_function": _text(goals.get("story_function"), card_hint, limit=1_000),
        "possible_arc": _text(
            goals.get("possible_arc"),
            "меняется только через реально произошедшие события",
            limit=1_000,
        ),
    }
    biography = _text_list(
        raw.get("biography")
        or raw.get("background")
        or raw.get("past")
        or raw.get("bio"),
        [card_hint],
        maximum=12,
    )
    constraints = _text_list(
        raw.get("constraints"),
        ["не противоречить установленной карточке и канону"],
        maximum=8,
    )

    if (
        not raw.get("appearance")
        or not raw.get("biography")
        or not raw.get("constraints")
    ):
        repairs.add(f"Дополнены обязательные служебные разделы карточки {name}.")

    return {
        **raw,
        "character_id": character_id,
        "card_level": level,
        "origin": origin,
        "card_hint": card_hint,
        "record_status": raw.get("record_status")
        if raw.get("record_status") in {"active", "inactive"}
        else "active",
        "story_status": raw.get("story_status")
        if raw.get("story_status")
        in {"not_introduced", "active", "offstage", "missing", "dead", "retired"}
        else ("not_introduced" if origin == "director_setup" else "active"),
        "player_visibility": raw.get("player_visibility")
        if raw.get("player_visibility") in {"hidden", "partial", "visible"}
        else ("hidden" if origin == "director_setup" else "visible"),
        "identity": identity,
        "appearance": appearance,
        "immediate_scene_goal": immediate_goal,
        "personality": personality,
        "preferences": preferences,
        "biography": biography,
        "skills": _text_list(raw.get("skills"), [], maximum=12),
        "goals": goals,
        "hidden_motives": _text_list(raw.get("hidden_motives"), [], maximum=8),
        "secrets": _text_list(raw.get("secrets"), [], maximum=8),
        "constraints": constraints,
    }


def _normalize_location_state(raw_value: Any, fallback_name: str) -> dict[str, Any]:
    state = _dict(raw_value)
    canon_value = state.get("canon")
    canon = _dict(canon_value)
    if isinstance(canon_value, str):
        canon["name"] = canon_value
    name = _text(canon.get("name") or state.get("name"), fallback_name, limit=300)
    canon = {
        **canon,
        "name": name,
        "purpose": _text(
            canon.get("purpose"), "место действия подтверждённой истории", limit=500
        ),
        "scale": _text(canon.get("scale"), "масштаб следует описанию мира", limit=300),
        "layout": _text(
            canon.get("layout"),
            "пространство следует установленному канону",
            limit=1_200,
        ),
        "zones": _text_list(canon.get("zones"), ["основная зона"], maximum=20),
        "visual_style": _text(
            canon.get("visual_style"), "соответствует миру новеллы", limit=700
        ),
        "condition": _text(
            canon.get("condition"), "текущее состояние установлено на старте", limit=500
        ),
        "color_palette": _text_list(
            canon.get("color_palette"), ["цвета исходной сцены"], maximum=10
        ),
        "materials": _text_list(
            canon.get("materials"), ["материалы исходной сцены"], maximum=10
        ),
        "lighting": _text(
            canon.get("lighting"), "освещение соответствует времени и месту", limit=700
        ),
        "windows_and_view": _text(
            canon.get("windows_and_view"), "не указано", limit=700
        ),
        "entrances": _text_list(canon.get("entrances"), ["основной вход"], maximum=12),
        "permanent_objects": _text_list(canon.get("permanent_objects"), [], maximum=30),
        "signature_details": _text_list(
            canon.get("signature_details"), [name], maximum=10
        ),
    }
    return {
        **state,
        "canon": canon,
        "current_changes": _text_list(state.get("current_changes"), [], maximum=30),
        "access": _text_list(state.get("access"), [], maximum=20),
        "damage_or_modifications": _text_list(
            state.get("damage_or_modifications"), [], maximum=20
        ),
    }


def _rewrite_exact_ids(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {
            mapping.get(str(key), str(key)): _rewrite_exact_ids(item, mapping)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_rewrite_exact_ids(item, mapping) for item in value]
    if isinstance(value, str):
        return mapping.get(value, value)
    return deepcopy(value)


def _name_key(value: Any) -> str:
    return " ".join(_text(value, "").casefold().replace("ё", "е").split())


def _normalize_plan_list(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in _list(value):
        if isinstance(item, dict):
            if item:
                result.append(deepcopy(item))
        else:
            text = _text(item, "")
            if text:
                result.append({"summary": text})
    return result


def _first_story_thread(plot_state: dict[str, Any]) -> str:
    for field in (
        "active_lines",
        "open_threads",
        "next_pressure_points",
        "pending_consequences",
    ):
        for item in _list(plot_state.get(field)):
            if isinstance(item, dict):
                for key in (
                    "current_question",
                    "summary",
                    "name",
                    "title",
                    "premise",
                    "description",
                ):
                    if item.get(key):
                        return _text(item[key], "")
            else:
                text = _text(item, "")
                if text:
                    return text
    return "Как подтверждённая исходная ситуация изменит цели и отношения персонажей?"


def normalize_create_session_payload(value: Any) -> Any:
    """Repair fillable transport/schema defects before strict Pydantic validation.

    The Custom GPT still sends the entire confirmed setup in one createSession call.
    This layer changes only technical representation: safe IDs, missing required
    containers and neutral fallbacks. It does not replace the packet/chunk runtime.
    """

    if not isinstance(value, dict):
        return value
    data = deepcopy(value)
    repairs = IntakeRepairs()

    novel = _dict(data.get("novel"))
    hidden_lore = _dict(data.get("hidden_lore"))
    plot_state = _dict(data.get("plot_state"))
    world_state = _dict(data.get("world_state"))
    scene_state = _dict(data.get("scene_state"))

    raw_characters = _bundle_items(data.get("characters"), "character_id", "card")
    used_character_ids: set[str] = set()
    character_id_map: dict[str, str] = {}
    prepared_characters: list[dict[str, Any]] = []
    character_aliases: list[set[str]] = []

    for index, raw_bundle in enumerate(raw_characters, start=1):
        raw_card = _dict(raw_bundle.get("card"))
        identity = _dict(raw_card.get("identity"))
        aliases = {
            _text(raw_bundle.get("character_id"), ""),
            _text(raw_card.get("character_id"), ""),
            _text(raw_bundle.get("id"), ""),
        }
        aliases.discard("")
        preferred = (
            raw_bundle.get("character_id")
            or raw_card.get("character_id")
            or identity.get("name")
            or raw_card.get("name")
        )
        character_id = _unique_id(preferred, "char", index, used_character_ids)
        if _text(preferred, "") != character_id:
            repairs.add(
                f"Внутренний ID персонажа №{index} нормализован как {character_id}."
            )
        for alias in aliases:
            character_id_map.setdefault(alias, character_id)
        card = _normalize_card(raw_card, character_id, index, repairs)
        character_aliases.append(aliases)
        prepared_characters.append(
            {
                "character_id": character_id,
                "card": card,
                "current_state": _dict(raw_bundle.get("current_state")),
                "relationships": deepcopy(raw_bundle.get("relationships", {})),
                "knowledge": deepcopy(raw_bundle.get("knowledge", {})),
            }
        )

    name_to_character_id: dict[str, str] = {}
    for character in prepared_characters:
        name = character["card"]["identity"]["name"]
        full_key = _name_key(name)
        if full_key:
            name_to_character_id.setdefault(full_key, character["character_id"])
        first_key = _name_key(name.split()[0]) if name.split() else ""
        if first_key:
            name_to_character_id.setdefault(first_key, character["character_id"])

    def character_reference(value: Any) -> str | None:
        raw = _text(value, "")
        if not raw:
            return None
        if raw in character_id_map:
            return character_id_map[raw]
        if raw in used_character_ids:
            return raw
        return name_to_character_id.get(_name_key(raw))

    pov_id = character_reference(novel.get("pov_character_id"))
    if pov_id is None:
        for character in prepared_characters:
            role = _name_key(character["card"]["identity"].get("role"))
            if any(
                marker in role for marker in ("pov", "героин", "главн", "протагонист")
            ):
                pov_id = character["character_id"]
                break
    if pov_id is None and prepared_characters:
        pov_id = prepared_characters[0]["character_id"]
        repairs.add(
            "POV привязан к первому подтверждённому персонажу, потому что ID не был указан."
        )
    if pov_id:
        novel["pov_character_id"] = pov_id

    raw_locations = _bundle_items(data.get("locations"), "location_id", "state")
    if not raw_locations:
        raw_location = scene_state.get("location_id") or scene_state.get(
            "location_name"
        )
        raw_locations = [
            {
                "location_id": raw_location or "loc_start",
                "state": {
                    "canon": {
                        "name": scene_state.get("location_name")
                        or raw_location
                        or "Стартовая локация"
                    }
                },
            }
        ]
        repairs.add("Создана техническая карточка стартовой локации.")

    used_location_ids: set[str] = set()
    location_id_map: dict[str, str] = {}
    prepared_locations: list[dict[str, Any]] = []
    for index, raw_bundle in enumerate(raw_locations, start=1):
        raw_state = _dict(raw_bundle.get("state"))
        canon = _dict(raw_state.get("canon"))
        raw_id = raw_bundle.get("location_id") or canon.get("name")
        location_id = _unique_id(raw_id, "loc", index, used_location_ids)
        if _text(raw_id, ""):
            location_id_map.setdefault(_text(raw_id, ""), location_id)
        fallback_name = _text(canon.get("name") or raw_id, f"Локация {index}")
        prepared_locations.append(
            {
                "location_id": location_id,
                "state": _normalize_location_state(raw_state, fallback_name),
            }
        )
        if _text(raw_id, "") != location_id:
            repairs.add(
                f"Внутренний ID локации №{index} нормализован как {location_id}."
            )

    raw_objects = _bundle_items(data.get("objects"), "object_id", "state")
    used_object_ids: set[str] = set()
    object_id_map: dict[str, str] = {}
    prepared_objects: list[dict[str, Any]] = []
    for index, raw_bundle in enumerate(raw_objects, start=1):
        raw_id = raw_bundle.get("object_id") or _dict(raw_bundle.get("state")).get(
            "name"
        )
        object_id = _unique_id(raw_id, "obj", index, used_object_ids)
        if _text(raw_id, ""):
            object_id_map.setdefault(_text(raw_id, ""), object_id)
        prepared_objects.append(
            {"object_id": object_id, "state": _dict(raw_bundle.get("state"))}
        )
        if _text(raw_id, "") != object_id:
            repairs.add(f"Внутренний ID объекта №{index} нормализован как {object_id}.")

    exact_id_map = {**character_id_map, **location_id_map, **object_id_map}

    def normalize_relationships(value: Any, owner_id: str) -> dict[str, Any]:
        source = _dict(value)
        raw_relations = source.get(
            "relations", value if isinstance(value, list) else []
        )
        if isinstance(raw_relations, dict):
            raw_relations = [
                (
                    {"target_character_id": target, **item}
                    if isinstance(item, dict)
                    else {"target_character_id": target, "current_dynamic": item}
                )
                for target, item in raw_relations.items()
            ]
        relations_by_target: dict[str, dict[str, Any]] = {}
        for relation_index, raw_relation in enumerate(_list(raw_relations), start=1):
            relation = _dict(raw_relation)
            target_raw = (
                relation.get("target_character_id")
                or relation.get("target_id")
                or relation.get("name")
            )
            target_id = character_reference(target_raw)
            if target_id is None and target_raw:
                target_id = _id_candidate(target_raw, "char", relation_index)
                repairs.add(
                    f"Связь {owner_id} сохранила внешнюю цель под безопасным ID {target_id}."
                )
            if not target_id or target_id == owner_id:
                continue
            dimensions: list[dict[str, Any]] = []
            used_dimension_keys: set[str] = set()
            raw_dimensions = relation.get("dimensions", [])
            if isinstance(raw_dimensions, dict):
                raw_dimensions = [
                    {"key": key, "label": key, "value": item}
                    for key, item in raw_dimensions.items()
                ]
            for dimension_index, raw_dimension in enumerate(
                _list(raw_dimensions)[:8], start=1
            ):
                dimension = _dict(raw_dimension)
                label = _text(
                    dimension.get("label") or dimension.get("key"),
                    f"параметр {dimension_index}",
                    limit=100,
                )
                key = _unique_id(
                    dimension.get("key") or label,
                    "dimension",
                    dimension_index,
                    used_dimension_keys,
                )
                try:
                    numeric_value = float(dimension.get("value", 50))
                except (TypeError, ValueError):
                    numeric_value = 50.0
                numeric_value = max(0.0, min(100.0, numeric_value))
                dimensions.append({"key": key, "label": label, "value": numeric_value})
            normalized = {
                **relation,
                "target_character_id": target_id,
                "relationship_type": _text(
                    relation.get("relationship_type") or relation.get("type"),
                    "установленная связь",
                    limit=200,
                ),
                "relationship_context": _text(
                    relation.get("relationship_context") or relation.get("context"),
                    "контекст следует подтверждённым данным",
                    limit=1_000,
                ),
                "current_dynamic": _text(
                    relation.get("current_dynamic") or relation.get("dynamic"),
                    "текущая динамика следует подтверждённым данным",
                    limit=1_000,
                ),
                "dimensions": dimensions,
                "beliefs_about_target": _text_list(
                    relation.get("beliefs_about_target"), [], maximum=30
                ),
                "unresolved_between_them": _text_list(
                    relation.get("unresolved_between_them"), [], maximum=30
                ),
                "dynamic_constraints": _text_list(
                    relation.get("dynamic_constraints"), [], maximum=20
                ),
                "change_reasons": _text_list(
                    relation.get("change_reasons"), [], maximum=50
                ),
                "last_changed_turn": _nonnegative_int(
                    relation.get("last_changed_turn", 0)
                ),
            }
            existing = relations_by_target.get(target_id)
            if existing is None:
                relations_by_target[target_id] = normalized
            else:
                dimensions_by_key = {
                    item["key"]: item for item in existing.get("dimensions", [])
                }
                for item in normalized.get("dimensions", []):
                    dimensions_by_key.setdefault(item["key"], item)
                existing["dimensions"] = list(dimensions_by_key.values())[:8]
                for field, maximum in (
                    ("beliefs_about_target", 30),
                    ("unresolved_between_them", 30),
                    ("dynamic_constraints", 20),
                    ("change_reasons", 50),
                ):
                    existing[field] = list(
                        dict.fromkeys(
                            existing.get(field, []) + normalized.get(field, [])
                        )
                    )[:maximum]
                repairs.add(f"Дубли связи {owner_id} → {target_id} объединены.")
        return {
            **source,
            "owner_character_id": owner_id,
            "relations": list(relations_by_target.values()),
        }

    for character in prepared_characters:
        character["current_state"] = _rewrite_exact_ids(
            character["current_state"], exact_id_map
        )
        character["current_state"]["character_id"] = character["character_id"]
        character["relationships"] = normalize_relationships(
            character["relationships"], character["character_id"]
        )
        knowledge = character["knowledge"]
        if isinstance(knowledge, list):
            knowledge = {"entries": knowledge}
        knowledge = _rewrite_exact_ids(_dict(knowledge), exact_id_map)
        knowledge.setdefault("character_id", character["character_id"])
        character["knowledge"] = knowledge

    novel = _rewrite_exact_ids(novel, exact_id_map)
    hidden_lore = _rewrite_exact_ids(hidden_lore, exact_id_map)
    plot_state = _rewrite_exact_ids(plot_state, exact_id_map)
    world_state = _rewrite_exact_ids(world_state, exact_id_map)
    scene_state = _rewrite_exact_ids(scene_state, exact_id_map)

    fallback_location_id = prepared_locations[0]["location_id"]
    raw_scene_location = scene_state.get("location_id")
    scene_location_id = location_id_map.get(
        _text(raw_scene_location, ""), raw_scene_location
    )
    if scene_location_id not in used_location_ids:
        scene_location_id = fallback_location_id
    scene_state["location_id"] = scene_location_id
    scene_state.setdefault("turn_number", 0)
    scene_state["scene_id"] = _id_candidate(scene_state.get("scene_id"), "scene", 0)
    scene_state.setdefault(
        "story_datetime", world_state.get("story_datetime") or "не указано"
    )

    present_ids: list[str] = []
    for item in _list(scene_state.get("present_character_ids")):
        resolved = character_reference(item)
        if resolved and resolved not in present_ids:
            present_ids.append(resolved)
    if pov_id and pov_id not in present_ids:
        present_ids.insert(0, pov_id)
        repairs.add("POV добавлен в состав стартовой сцены.")
    scene_state["present_character_ids"] = present_ids
    for field in ("entered_character_ids", "left_character_ids"):
        resolved_values: list[str] = []
        for item in _list(scene_state.get(field)):
            resolved = character_reference(item)
            if resolved and resolved not in resolved_values:
                resolved_values.append(resolved)
        scene_state[field] = resolved_values

    for character in prepared_characters:
        current_state = character["current_state"]
        current_location = current_state.get("current_location_id")
        if current_location not in used_location_ids:
            current_state["current_location_id"] = scene_location_id
        current_state.setdefault(
            "present_in_scene", character["character_id"] in present_ids
        )

    director_plan = _dict(data.get("director_plan"))
    director_plan = _rewrite_exact_ids(director_plan, exact_id_map)
    for field in PLAN_LIST_FIELDS:
        director_plan[field] = _normalize_plan_list(director_plan.get(field))
    if data.get("runtime_contract_version") == "2.0":
        if not director_plan["active_threads"]:
            director_plan["active_threads"] = [
                {
                    "thread_id": "thread_opening",
                    "current_question": _first_story_thread(plot_state),
                    "current_pressure": "Подтверждённая исходная ситуация уже требует естественного продолжения.",
                    "status": "active",
                }
            ]
            repairs.add("Добавлена техническая стартовая нить director_plan.")
        if not director_plan["character_agendas"] and prepared_characters:
            agenda_character = next(
                (
                    item
                    for item in prepared_characters
                    if item["character_id"] != pov_id
                ),
                prepared_characters[0],
            )
            director_plan["character_agendas"] = [
                {
                    "character_id": agenda_character["character_id"],
                    "current_goal": agenda_character["card"]["goals"]["personal"],
                    "next_plausible_action": agenda_character["card"][
                        "immediate_scene_goal"
                    ],
                    "conditions": [],
                }
            ]
            repairs.add("Добавлена техническая стартовая agenda director_plan.")

    data.update(
        {
            "novel": novel,
            "hidden_lore": hidden_lore,
            "plot_state": plot_state,
            "director_plan": director_plan,
            "world_state": world_state,
            "scene_state": scene_state,
            "characters": prepared_characters,
            "locations": prepared_locations,
            "objects": [
                {
                    "object_id": item["object_id"],
                    "state": _rewrite_exact_ids(item["state"], exact_id_map),
                }
                for item in prepared_objects
            ],
            "intake_repairs_internal": repairs.notes,
        }
    )
    return data
