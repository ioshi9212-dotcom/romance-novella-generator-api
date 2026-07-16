from __future__ import annotations

from typing import Any

from app.character_profiles import SIGNIFICANT_CAST_STATUSES, behavior_signature, prepare_bootstrap_cast


_PLACEHOLDER_EXACT = {
    "",
    "—",
    "-",
    "не указано",
    "не задано",
    "старт",
    "стартовая локация",
    "начало истории",
    "начать первую сцену",
    "открыть первую сцену",
    "сеттинг будет уточняться",
}
_PLACEHOLDER_SNIPPETS = (
    "будет уточняться",
    "не указано",
    "не задано",
    "placeholder",
    "живая, узнаваемая речь",
    "заметная привычка",
)


def _text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    if isinstance(value, str):
        return value.strip() or fallback
    if isinstance(value, (int, float, bool)):
        return str(value)
    return str(value).strip() or fallback


def _placeholder(value: Any) -> bool:
    text = " ".join(_text(value).lower().replace("ё", "е").split())
    return text in _PLACEHOLDER_EXACT or any(snippet in text for snippet in _PLACEHOLDER_SNIPPETS)


def _concrete(value: Any, fallback: str) -> str:
    return fallback if _placeholder(value) else _text(value, fallback)


def _role_kind(role: Any) -> str:
    text = _text(role).lower()
    if any(word in text for word in ("friend", "подруг", "друг", "bestie")):
        return "friend"
    if any(word in text for word in ("love", "romance", "boyfriend", "girlfriend", "lover", "crush", "парень", "влюб")):
        return "romance"
    if any(word in text for word in ("family", "brother", "sister", "mother", "father", "брат", "сестр", "мать", "отец", "родствен")):
        return "family"
    if any(word in text for word in ("colleague", "coworker", "boss", "manager", "коллег", "началь", "сотруд")):
        return "colleague"
    return "default"


def _visible_name(card: dict[str, Any], fallback: str) -> str:
    for key in ("display_name", "visible_name", "name_ru", "russian_name", "name"):
        value = card.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def _player_id(data: dict[str, Any]) -> str:
    protagonist = data.get("protagonist") if isinstance(data.get("protagonist"), dict) else {}
    current_state = data.get("current_state") if isinstance(data.get("current_state"), dict) else {}
    characters = data.get("characters") if isinstance(data.get("characters"), dict) else {}
    return _text(protagonist.get("id") or current_state.get("player_character_id") or next(iter(characters), "pc_01"), "pc_01")


def _character_goal(card: dict[str, Any], *, is_player: bool, player_name: str) -> str:
    life = card.get("life_outside_player") if isinstance(card.get("life_outside_player"), dict) else {}
    obligation = _concrete(life.get("current_obligation"), "довести ближайшее личное дело до результата")
    private_problem = _concrete(life.get("private_problem"), "не дать внутреннему напряжению разрушить привычный порядок")
    kind = _role_kind(card.get("role"))
    if is_player:
        return f"сохранить право решать самой, выполнить текущую обязанность — {obligation} — и не позволить проблеме «{private_problem}» определить следующий шаг"
    if kind == "friend":
        return f"остаться важной частью жизни {player_name}, добиться честного ответа и одновременно выполнить собственную обязанность — {obligation}"
    if kind == "romance":
        return f"получить ясность в отношениях с {player_name}, не потеряв контроль над собственной обязанностью — {obligation}"
    if kind == "family":
        return f"сохранить своё влияние на семейную ситуацию вокруг {player_name} и решить собственную задачу — {obligation}"
    if kind == "colleague":
        return f"довести рабочую задачу до результата — {obligation} — и понять, можно ли полагаться на {player_name} под давлением"
    return f"добиться собственного результата — {obligation} — и не позволить проблеме «{private_problem}» лишить себя контроля"


def _character_past(card: dict[str, Any], character_name: str) -> str:
    life = card.get("life_outside_player") if isinstance(card.get("life_outside_player"), dict) else {}
    behavior = card.get("behavior") if isinstance(card.get("behavior"), dict) else {}
    obligation = _concrete(life.get("current_obligation"), "собственная работа и бытовые обязательства")
    private_problem = _concrete(life.get("private_problem"), "давняя личная проблема, которую человек привык скрывать")
    stress = _concrete(behavior.get("stress_response"), "под давлением возвращается к привычному способу защищаться")
    return (
        f"До начала истории {character_name} уже жил(а) с обязанностью «{obligation}». "
        f"Под давлением обычно {stress}; поэтому текущая проблема — {private_problem} — возникла не внезапно и влияет на решения с первого дня."
    )


def _repair_characters(data: dict[str, Any]) -> None:
    characters = data.get("characters") if isinstance(data.get("characters"), dict) else {}
    player_id = _player_id(data)
    player_card = characters.get(player_id) if isinstance(characters.get(player_id), dict) else {}
    player_name = _visible_name(player_card, "героини")

    for character_id, raw_card in characters.items():
        if not isinstance(raw_card, dict):
            continue
        card = raw_card
        name = _visible_name(card, str(character_id))
        card["goal"] = _concrete(
            card.get("goal"),
            _character_goal(card, is_player=str(character_id) == player_id, player_name=player_name),
        )
        card["past_short"] = _concrete(
            card.get("past_short") or card.get("background"),
            _character_past(card, name),
        )

    if player_id in characters and isinstance(characters[player_id], dict):
        data["protagonist"] = characters[player_id]


def _repair_story_plan(data: dict[str, Any]) -> None:
    story_plan = data.get("story_plan") if isinstance(data.get("story_plan"), dict) else {}
    current_state = data.get("current_state") if isinstance(data.get("current_state"), dict) else {}
    characters = data.get("characters") if isinstance(data.get("characters"), dict) else {}
    player_id = _player_id(data)
    player_card = characters.get(player_id) if isinstance(characters.get(player_id), dict) else {}
    player_name = _visible_name(player_card, "Героиня")
    player_goal = _concrete(player_card.get("goal"), "сохранить контроль над собственной жизнью")

    location = _concrete(current_state.get("location"), "рабочее место героини в современном городе")
    time = _concrete(current_state.get("time"), "вечер, 19:30")
    genre = _concrete(story_plan.get("genre"), "романтическая драма с мистическим слоем")

    story_plan["setting_summary"] = _concrete(
        story_plan.get("setting_summary"),
        f"{genre.capitalize()} в современном городе; история начинается {time} в месте «{location}», где повседневное давление сталкивается с самостоятельными целями персонажей.",
    )
    story_plan["main_premise"] = _concrete(
        story_plan.get("main_premise"),
        f"{player_name} пытается {player_goal}, но чужая цель и первый необъяснимый сдвиг нарушают привычный порядок.",
    )
    story_plan["protagonist_start"] = _concrete(
        story_plan.get("protagonist_start"),
        f"{player_name} начинает историю {time} в месте «{location}», уже занятая собственной проблемой и не готовая передавать решение другому человеку.",
    )
    story_plan["player_goal"] = _concrete(story_plan.get("player_goal"), player_goal)
    story_plan["central_conflict"] = _concrete(
        story_plan.get("central_conflict"),
        f"Цель {player_name} сталкивается с самостоятельными планами близких людей; помощь легко превращается в давление, а бездействие имеет цену.",
    )
    story_plan["central_question"] = _concrete(
        story_plan.get("central_question"),
        f"Что выберет {player_name}, когда сохранить контроль и сохранить важные отношения одновременно станет невозможно?",
    )
    story_plan["opening_scene_intent"] = _concrete(
        story_plan.get("opening_scene_intent"),
        f"Открыть сцену {time} в месте «{location}»: показать текущую задачу {player_name}, самостоятельный шаг другого персонажа и один конкретный сдвиг ситуации.",
    )
    data["story_plan"] = story_plan


def _repair_current_state(data: dict[str, Any]) -> None:
    story_plan = data.get("story_plan") if isinstance(data.get("story_plan"), dict) else {}
    current_state = data.get("current_state") if isinstance(data.get("current_state"), dict) else {}
    current_state["time"] = _concrete(current_state.get("time"), "вечер, 19:30")
    current_state["location"] = _concrete(current_state.get("location"), "рабочее место героини в современном городе")
    current_state["weather"] = _concrete(current_state.get("weather"), "прохладный сухой вечер; свет с улицы уже искусственный")
    current_state["scene_state"] = _concrete(current_state.get("scene_state"), _text(story_plan.get("opening_scene_intent"), "стартовая ситуация уже требует реакции"))
    current_state["outfit"] = _concrete(current_state.get("outfit"), "повседневная одежда по сезону, выбранная для текущих дел")
    data["current_state"] = current_state


def _ensure_distinct_behavior_signatures(data: dict[str, Any]) -> None:
    characters = data.get("characters") if isinstance(data.get("characters"), dict) else {}
    player_id = _player_id(data)
    seen: dict[tuple[str, str, str, str], str] = {}
    variations = [
        "Важное требование произносит последним, после одной бытовой детали.",
        "Перед спором задаёт один точный вопрос и не принимает ответ, который считает уклончивым.",
        "Под давлением сокращает фразы до глаголов и конкретных последствий.",
        "Начинает мягче обычного, но возвращается к главному вопросу второй раз уже без смягчений.",
        "Сначала замолкает и наблюдает, затем формулирует претензию одной длинной фразой.",
        "Использует сухую шутку как проверку реакции, а после неё говорит прямо.",
    ]
    duplicate_index = 0
    for character_id, card in characters.items():
        if character_id == player_id or not isinstance(card, dict):
            continue
        if card.get("cast_status") not in SIGNIFICANT_CAST_STATUSES:
            continue
        signature = behavior_signature(card)
        if signature not in seen:
            seen[signature] = str(character_id)
            continue
        speech = card.get("speech_profile") if isinstance(card.get("speech_profile"), dict) else {}
        variation = variations[duplicate_index % len(variations)]
        duplicate_index += 1
        baseline = _concrete(speech.get("baseline"), "разговорная речь с узнаваемым темпом")
        speech["baseline"] = f"{baseline} {variation}"
        card["speech_profile"] = speech
        seen[behavior_signature(card)] = str(character_id)


def repair_bootstrap_content(data: dict[str, Any]) -> dict[str, Any]:
    """Repair common model omissions before strict bootstrap validation.

    The normalizer is intentionally permissive, while the validator rejects
    placeholders. This pass bridges the two layers so missing optional prose is
    invented deterministically instead of turning a recoverable draft into an
    Action-level 422 response.
    """
    if not isinstance(data, dict):
        return data
    prepare_bootstrap_cast(data)
    _repair_characters(data)
    _repair_story_plan(data)
    _repair_current_state(data)
    _ensure_distinct_behavior_signatures(data)
    return data
