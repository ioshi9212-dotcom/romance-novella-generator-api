from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.id_utils import pair_id


CAST_STATUSES = {"player", "known_core", "known_support", "hidden_core", "background"}
VISIBLE_PREVIEW_STATUSES = {"player", "known_core", "known_support"}
SIGNIFICANT_CAST_STATUSES = {"player", "known_core", "known_support", "hidden_core"}

_PLACEHOLDER_SNIPPETS = (
    "будет уточняться",
    "не указано",
    "живая, узнаваемая речь",
    "заметная привычка",
    "закрытый характер",
    "честность в действиях",
    "давление и ложь",
)

_ROLE_TEMPLATES: dict[str, dict[str, Any]] = {
    "friend": {
        "inner_logic": {
            "core_need": "оставаться важной частью жизни близкого человека",
            "main_fear": "оказаться лишней и узнать о серьёзной проблеме последней",
            "blind_spot": "принимает молчание за подтверждение, что нужно надавить сильнее",
            "contradiction": "хочет поддержать, но превращает заботу в контроль",
        },
        "behavior": {
            "conflict_style": "задаёт вопрос повторно, перебивает уклончивые ответы и не отпускает тему",
            "care_style": "помогает делами, приносит нужное без просьбы и проверяет состояние напрямую",
            "closeness_style": "считает давнюю близость правом задавать неудобные вопросы",
            "touch_style": "легко касается плеча или руки, если раньше это было обычным между ними",
            "stress_response": "говорит быстрее и громче, начинает распоряжаться и проверять",
            "rejection_response": "сначала шутит, потом обижается и возвращается к вопросу ещё прямее",
            "change_inertia": "может понять, что давит, но при новой тревоге повторяет тот же паттерн",
            "inconvenient_pattern": "лезет в личное, когда уверена, что другого способа помочь нет",
        },
        "speech_profile": {
            "baseline": "быстрая разговорная речь, прямые вопросы и знакомые бытовые подколы",
            "under_pressure": "перебивает, повторяет ключевой вопрос и повышает голос",
            "verbal_habits": ["обращается полным именем, когда злится", "повторяет вопрос другими словами"],
            "avoids": ["прямо говорить, что боится потерять близость"],
        },
        "life_outside_player": {
            "current_obligation": "держит собственную работу и бытовые обязательства, которые не исчезают из-за героини",
            "private_problem": "сама устала быть человеком, который всегда первым замечает чужие проблемы",
            "person_or_place_that_matters": "место или человек из её отдельной жизни, куда она возвращается после сцены",
        },
        "habits": ["проверяет телефон во время пауз", "приносит еду вместо долгих утешений"],
    },
    "romance": {
        "inner_logic": {
            "core_need": "получить подтверждение, что связь с героиней реальна и взаимна",
            "main_fear": "потерять её, пока он снова соблюдает дистанцию и ждёт подходящего момента",
            "blind_spot": "может путать настойчивость с доказательством серьёзности чувств",
            "contradiction": "хочет быть надёжным, но под страхом потери начинает удерживать и давить",
        },
        "behavior": {
            "conflict_style": "возвращается к теме, требует ясности и плохо переносит неопределённость",
            "care_style": "делает практические вещи и старается быть рядом раньше, чем его попросят",
            "closeness_style": "сокращает расстояние и ищет поводы остаться рядом дольше",
            "touch_style": "может потянуться к кисти, локтю или плечу, если считает близость между ними привычной",
            "stress_response": "становится резче, ревнивее и пытается контролировать следующий шаг",
            "rejection_response": "останавливается в моменте, но холодеет, спорит или возвращается к теме позже",
            "change_inertia": "понимает замечание не сразу и под сильным страхом повторяет старую ошибку",
            "inconvenient_pattern": "пытается удержать контакт именно тогда, когда героине требуется отступить",
        },
        "speech_profile": {
            "baseline": "личная, внимательная речь с недосказанностью и вопросами, на которые ему важен настоящий ответ",
            "under_pressure": "говорит короче и жёстче, перестаёт скрывать ревность или раздражение",
            "verbal_habits": ["цепляется за неточную формулировку", "задаёт второй вопрос до полного ответа на первый"],
            "avoids": ["прямо называть страх быть отвергнутым"],
        },
        "life_outside_player": {
            "current_obligation": "имеет собственную работу, обязанности и планы, которые могут конфликтовать со встречей",
            "private_problem": "долго живёт с чувствами, не получая ясного ответа, и устал притворяться спокойным",
            "person_or_place_that_matters": "личное пространство или близкий человек, не связанный с героиней",
        },
        "habits": ["запоминает мелкие бытовые детали", "задерживается рядом после окончания разговора"],
    },
    "family": {
        "inner_logic": {
            "core_need": "сохранить своё место в семье и привычный порядок близости",
            "main_fear": "что семья распадётся или перестанет нуждаться в нём",
            "blind_spot": "считает родство разрешением вмешиваться без приглашения",
            "contradiction": "защищает близких и одновременно лишает их права решать самим",
        },
        "behavior": {
            "conflict_style": "вспоминает старые долги, говорит прямо и продолжает спор после попытки закончить тему",
            "care_style": "решает бытовые проблемы, контролирует деньги, еду, дорогу или безопасность",
            "closeness_style": "ведёт себя так, будто семейный доступ не нужно подтверждать каждый раз",
            "touch_style": "может обнять, удержать за плечи или забрать вещь из рук по привычке",
            "stress_response": "становится командным, повышает голос и начинает решать за всех",
            "rejection_response": "обижается, обвиняет в неблагодарности или демонстративно отстраняется",
            "change_inertia": "извиняется за форму, но долго сохраняет убеждение, что по сути был прав",
            "inconvenient_pattern": "использует заботу как аргумент в пользу контроля",
        },
        "speech_profile": {
            "baseline": "бытовая прямая речь, старые семейные обращения и отсутствие церемоний",
            "under_pressure": "говорит громче, перечисляет прошлые случаи и начинает командовать",
            "verbal_habits": ["напоминает, как было раньше", "использует семейные прозвища в споре"],
            "avoids": ["признавать собственную зависимость от семьи"],
        },
        "life_outside_player": {
            "current_obligation": "занят собственными семейными, финансовыми или рабочими делами",
            "private_problem": "боится потерять привычную роль и потому держится за контроль",
            "person_or_place_that_matters": "другой родственник, дом или обязанность вне текущей сцены",
        },
        "habits": ["переставляет вещи на привычные места", "проверяет, поела ли героиня"],
    },
    "colleague": {
        "inner_logic": {
            "core_need": "сохранить компетентность, влияние и устойчивое положение в своей среде",
            "main_fear": "оказаться крайним, слабым звеном или человеком, которого легко заменить",
            "blind_spot": "принимает чужую растерянность за непрофессионализм или скрытность",
            "contradiction": "нуждается в сотрудничестве, но конкурирует за контроль над ситуацией",
        },
        "behavior": {
            "conflict_style": "спорит по фактам, фиксирует ошибки и может вынести конфликт в рабочую плоскость",
            "care_style": "подменяет, прикрывает или решает практическую задачу без эмоциональных разговоров",
            "closeness_style": "сближается через совместную работу, привычный ритм и обмен услугами",
            "touch_style": "обычно держит рабочую дистанцию, но может физически направить или остановить в спешке",
            "stress_response": "становится сухим, резким и начинает распределять обязанности",
            "rejection_response": "делает вывод о ненадёжности и перестраивает планы без долгих объяснений",
            "change_inertia": "может признать конкретную ошибку, не меняя общий способ обращаться с людьми",
            "inconvenient_pattern": "ставит результат выше чужого комфорта и считает это нормальным",
        },
        "speech_profile": {
            "baseline": "короткая предметная речь с рабочими сокращениями и конкретными требованиями",
            "under_pressure": "говорит отрывисто, жёстко расставляет приоритеты и перебивает оправдания",
            "verbal_habits": ["возвращает разговор к задаче", "называет точное время и последствия"],
            "avoids": ["обсуждать личные чувства на работе"],
        },
        "life_outside_player": {
            "current_obligation": "ведёт собственную смену, проект или карьерную задачу",
            "private_problem": "рискует репутацией или местом из-за чужих и собственных решений",
            "person_or_place_that_matters": "команда, должность или дело, существующее независимо от героини",
        },
        "habits": ["проверяет время перед ответом", "исправляет мелкие рабочие ошибки на ходу"],
    },
    "default": {
        "inner_logic": {
            "core_need": "сохранить контроль над собственной жизнью и быть значимым для выбранных людей",
            "main_fear": "оказаться бессильным, ненужным или использованным",
            "blind_spot": "слишком быстро объясняет чужое поведение через собственный страх",
            "contradiction": "хочет близости, но защищается способом, который эту близость портит",
        },
        "behavior": {
            "conflict_style": "не отпускает важную для себя тему и защищает собственную версию происходящего",
            "care_style": "помогает так, как умеет сам, а не обязательно так, как удобно героине",
            "closeness_style": "проверяет близость действиями и реакцией на отказ",
            "touch_style": "физическая дистанция зависит от привычки, статуса отношений и текущего напряжения",
            "stress_response": "теряет часть самоконтроля и возвращается к привычной защите",
            "rejection_response": "может спорить, закрыться, обидеться или сделать неверный вывод",
            "change_inertia": "понимание ошибки не превращается в мгновенно новое поведение",
            "inconvenient_pattern": "в критический момент выбирает знакомый способ защиты, даже если он уже вредил отношениям",
        },
        "speech_profile": {
            "baseline": "узнаваемая речь с собственным темпом, словарём и способом уходить от неудобного",
            "under_pressure": "манера речи заметно меняется: темп, громкость или резкость выдают напряжение",
            "verbal_habits": ["повторяет характерную формулировку", "по-своему уходит от прямого признания"],
            "avoids": ["называть главный страх напрямую"],
        },
        "life_outside_player": {
            "current_obligation": "имеет собственные дела и сроки вне героини",
            "private_problem": "решает личную проблему, которую не обязан сразу раскрывать",
            "person_or_place_that_matters": "человек, место или дело из отдельной жизни",
        },
        "habits": ["делает повторяющийся жест в напряжении", "проверяет важную для себя вещь или сообщение"],
    },
}


def _role_kind(role: Any) -> str:
    text = str(role or "").lower()
    if any(word in text for word in ("friend", "подруг", "друг", "bestie")):
        return "friend"
    if any(word in text for word in ("love", "romance", "boyfriend", "girlfriend", "lover", "crush", "парень", "влюб")):
        return "romance"
    if any(word in text for word in ("family", "brother", "sister", "mother", "father", "брат", "сестр", "мать", "отец", "родствен")):
        return "family"
    if any(word in text for word in ("colleague", "coworker", "boss", "manager", "коллег", "началь", "сотруд")):
        return "colleague"
    return "default"


def _placeholder(value: Any) -> bool:
    text = " ".join(str(value or "").lower().split())
    return not text or any(snippet in text for snippet in _PLACEHOLDER_SNIPPETS)


def _text(value: Any, fallback: str) -> str:
    return fallback if _placeholder(value) else str(value).strip()


def _list(value: Any, fallback: list[str], *, minimum: int = 1) -> list[str]:
    if isinstance(value, list):
        cleaned = [str(item).strip() for item in value if str(item).strip() and not _placeholder(item)]
        if len(cleaned) >= minimum:
            return cleaned
    elif isinstance(value, str) and value.strip() and not _placeholder(value):
        return [value.strip()]
    return list(fallback)


def infer_cast_status(card: dict[str, Any], *, is_player: bool = False) -> str:
    if is_player:
        return "player"
    explicit = str(card.get("cast_status") or "").strip().lower()
    if explicit in CAST_STATUSES:
        return explicit
    if card.get("generate_full_card_on_first_appearance"):
        return "hidden_core"
    role = str(card.get("role") or "").lower()
    if any(word in role for word in ("background", "minor", "extra", "фон", "эпизод")):
        return "background"
    if bool(card.get("known_to_player")):
        return "known_core" if any(
            word in role
            for word in ("friend", "family", "brother", "sister", "love", "romance", "partner", "подруг", "брат", "сестр", "парень")
        ) else "known_support"
    return "hidden_core"


def _normalise_object(source: Any, defaults: dict[str, Any]) -> dict[str, Any]:
    source = source if isinstance(source, dict) else {}
    result: dict[str, Any] = {}
    for key, fallback in defaults.items():
        value = source.get(key)
        if isinstance(fallback, list):
            result[key] = _list(value, fallback, minimum=0 if not fallback else 1)
        else:
            result[key] = _text(value, str(fallback))
    for key, value in source.items():
        if key not in result:
            result[key] = value
    return result


def enrich_character_card(card: dict[str, Any], character_id: str, *, is_player: bool = False) -> dict[str, Any]:
    result = deepcopy(card) if isinstance(card, dict) else {}
    cast_status = infer_cast_status(result, is_player=is_player)
    template = _ROLE_TEMPLATES[_role_kind(result.get("role"))]

    result["id"] = character_id
    result["cast_status"] = cast_status
    result["known_to_player"] = cast_status in {"player", "known_core", "known_support"}
    result["introduced"] = cast_status in {"player", "known_core", "known_support"}
    result["show_in_preview"] = cast_status in VISIBLE_PREVIEW_STATUSES
    result["available_to_scene"] = cast_status != "hidden_core"
    result["locked"] = True

    result["inner_logic"] = _normalise_object(result.get("inner_logic"), template["inner_logic"])
    result["behavior"] = _normalise_object(result.get("behavior"), template["behavior"])
    result["speech_profile"] = _normalise_object(result.get("speech_profile"), template["speech_profile"])
    result["life_outside_player"] = _normalise_object(result.get("life_outside_player"), template["life_outside_player"])
    result["habits"] = _list(result.get("habits"), template["habits"])

    social_triggers = result.get("social_triggers")
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

    personality = result.get("personality") if isinstance(result.get("personality"), dict) else {}
    personality["core"] = _list(personality.get("core"), [result["inner_logic"]["contradiction"]])
    personality["flaws"] = _list(personality.get("flaws"), [result["behavior"]["inconvenient_pattern"]])
    personality["speech"] = _text(personality.get("speech"), result["speech_profile"]["baseline"])
    result["personality"] = personality

    first_trigger = result["social_triggers"][0]
    second_trigger = result["social_triggers"][1]
    result["likes_in_people"] = _list(
        result.get("likes_in_people"),
        [str(first_trigger.get("behavior") or "последовательное видимое поведение")],
    )
    result["dislikes_in_people"] = _list(
        result.get("dislikes_in_people"),
        [str(second_trigger.get("behavior") or "непредсказуемое давление")],
    )
    triggers = result.get("relationship_triggers") if isinstance(result.get("relationship_triggers"), dict) else {}
    result["relationship_triggers"] = {
        **triggers,
        "improves_when": _list(
            triggers.get("improves_when"),
            [str(first_trigger.get("usual_reaction") or "видит повторяющееся надёжное действие")],
        ),
        "worsens_when": _list(
            triggers.get("worsens_when"),
            [str(second_trigger.get("usual_reaction") or "видит повторяющееся нарушение ожиданий")],
        ),
    }
    return result


def visible_character_ids(data: dict[str, Any]) -> set[str]:
    characters = data.get("characters") if isinstance(data.get("characters"), dict) else {}
    return {
        character_id
        for character_id, card in characters.items()
        if isinstance(card, dict) and card.get("cast_status") in VISIBLE_PREVIEW_STATUSES
    }


def behavior_signature(card: dict[str, Any]) -> tuple[str, str, str, str]:
    behavior = card.get("behavior") if isinstance(card.get("behavior"), dict) else {}
    speech = card.get("speech_profile") if isinstance(card.get("speech_profile"), dict) else {}
    return tuple(
        " ".join(str(value or "").lower().split())
        for value in (
            behavior.get("care_style"),
            behavior.get("conflict_style"),
            behavior.get("stress_response"),
            speech.get("baseline"),
        )
    )


def _baseline_scores(cast_status: str, role: Any) -> dict[str, int]:
    kind = _role_kind(role)
    if kind == "friend":
        return {"trust": 60, "tension": 20, "attachment": 55, "respect": 40, "fear": 0, "curiosity": 20}
    if kind == "family":
        return {"trust": 45, "tension": 40, "attachment": 65, "respect": 35, "fear": 5, "curiosity": 10}
    if kind == "romance":
        return {"trust": 40, "tension": 50, "attachment": 55, "respect": 35, "fear": 10, "curiosity": 55}
    if kind == "colleague":
        return {"trust": 45, "tension": 25, "attachment": 10, "respect": 45, "fear": 0, "curiosity": 20}
    if cast_status == "known_core":
        return {"trust": 45, "tension": 30, "attachment": 35, "respect": 35, "fear": 0, "curiosity": 25}
    return {"trust": 40, "tension": 20, "attachment": 10, "respect": 35, "fear": 0, "curiosity": 20}


def prepare_bootstrap_cast(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return data
    characters = data.get("characters") if isinstance(data.get("characters"), dict) else {}
    protagonist = data.get("protagonist") if isinstance(data.get("protagonist"), dict) else {}
    current_state = data.get("current_state") if isinstance(data.get("current_state"), dict) else {}
    protagonist_id = str(
        protagonist.get("id")
        or current_state.get("player_character_id")
        or next(iter(characters), "pc_01")
    )

    enriched: dict[str, Any] = {}
    for character_id, card in characters.items():
        enriched[str(character_id)] = enrich_character_card(
            card if isinstance(card, dict) else {},
            str(character_id),
            is_player=str(character_id) == protagonist_id,
        )
    if protagonist_id not in enriched:
        enriched[protagonist_id] = enrich_character_card(protagonist, protagonist_id, is_player=True)
    data["characters"] = enriched
    data["protagonist"] = enriched[protagonist_id]

    hidden_ids = {
        character_id
        for character_id, card in enriched.items()
        if card.get("cast_status") == "hidden_core"
    }
    current_state["player_character_id"] = protagonist_id
    active_ids = [str(item) for item in current_state.get("active_character_ids", []) if str(item) in enriched and str(item) not in hidden_ids]
    nearby_ids = [str(item) for item in current_state.get("nearby_character_ids", []) if str(item) in enriched and str(item) not in hidden_ids]
    if protagonist_id not in active_ids:
        active_ids.insert(0, protagonist_id)
    current_state["active_character_ids"] = list(dict.fromkeys(active_ids))
    current_state["nearby_character_ids"] = list(dict.fromkeys(nearby_ids))
    data["current_state"] = current_state

    knowledge = data.get("knowledge") if isinstance(data.get("knowledge"), dict) else {}
    for character_id in enriched:
        entry = knowledge.get(character_id) if isinstance(knowledge.get(character_id), dict) else {}
        knowledge[character_id] = {
            "character_id": character_id,
            "known_facts": list(entry.get("known_facts") or []),
            "observations": list(entry.get("observations") or []),
            "assumptions": list(entry.get("assumptions") or []),
            "wrong_beliefs": list(entry.get("wrong_beliefs") or []),
            "does_not_know": list(entry.get("does_not_know") or []),
            "must_not_assume": list(entry.get("must_not_assume") or []),
            "recent_memories": list(entry.get("recent_memories") or []),
            "open_questions": list(entry.get("open_questions") or []),
            "knows": list(entry.get("knows") or []),
            **{key: value for key, value in entry.items() if key not in {
                "character_id", "known_facts", "observations", "assumptions", "wrong_beliefs",
                "does_not_know", "must_not_assume", "recent_memories", "open_questions", "knows",
            }},
        }
    data["knowledge"] = knowledge

    relationships = data.get("relationships") if isinstance(data.get("relationships"), dict) else {}
    for character_id, card in enriched.items():
        if character_id == protagonist_id or card.get("cast_status") not in {"known_core", "known_support"}:
            continue
        pid = pair_id(protagonist_id, character_id)
        if pid in relationships:
            continue
        a, b = sorted((protagonist_id, character_id))
        relationships[pid] = {
            "pair_id": pid,
            "character_a": a,
            "character_b": b,
            "type": "starting_relationship",
            "status": "отношения существуют до начала истории и содержат привычки, ожидания и незакрытые темы",
            "scores": _baseline_scores(str(card.get("cast_status")), card.get("role")),
            "a_view_of_b": {"summary": "восприятие основано на общей истории и может быть предвзятым", "current_assumption": "частично ошибается"},
            "b_view_of_a": {"summary": "восприятие основано на общей истории и может быть предвзятым", "current_assumption": "частично ошибается"},
            "shared_history": [],
            "recent_changes": [],
            "open_threads": [str(card.get("behavior", {}).get("inconvenient_pattern") or "незакрытая привычная динамика")],
        }
    data["relationships"] = relationships

    npc_state = data.get("npc_state") if isinstance(data.get("npc_state"), dict) else {}
    for character_id, card in enriched.items():
        if character_id == protagonist_id or card.get("cast_status") == "background":
            continue
        state = npc_state.get(character_id) if isinstance(npc_state.get(character_id), dict) else {}
        life = card.get("life_outside_player") if isinstance(card.get("life_outside_player"), dict) else {}
        behavior = card.get("behavior") if isinstance(card.get("behavior"), dict) else {}
        npc_state[character_id] = {
            **state,
            "current_goal": state.get("current_goal") or card.get("goal"),
            "current_route": state.get("current_route") or life.get("current_obligation"),
            "current_pressure": state.get("current_pressure") or life.get("private_problem"),
            "next_self_action_if_ignored": state.get("next_self_action_if_ignored") or behavior.get("inconvenient_pattern"),
        }
    data["npc_state"] = npc_state

    future_locks = data.get("future_locks") if isinstance(data.get("future_locks"), dict) else {}
    future_locks.setdefault("hidden_character_seeds", [])
    future_locks.setdefault("do_not_reveal_yet", [])
    future_locks["hidden_character_ids"] = sorted(hidden_ids)
    data["future_locks"] = future_locks
    return data
