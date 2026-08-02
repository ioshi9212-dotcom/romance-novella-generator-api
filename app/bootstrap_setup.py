from __future__ import annotations

import json
from typing import Any

from app.bootstrap_normalizer import normalize_bootstrap_json
from app.character_profiles import prepare_bootstrap_cast, visible_character_ids



def build_bootstrap_prompt(user_request: dict[str, Any]) -> str:
    request_json = json.dumps(user_request, ensure_ascii=False, indent=2)
    return f"""
Ты создаёшь новую интерактивную визуальную новеллу с нуля.

КАНОН
- raw_start_text — точный ответ пользователя и главный источник. Сохрани каждый конкретный факт и каждый явный запрет.
- Частичная анкета, «Рандом», прочерк и пропущенный пункт допустимы: всё неуказанное придумай сама. Повторно спрашивать анкету нельзя.
- Не оставляй заглушки вроде «не указано», «будет уточняться», «ценит честность» или одинаковые шаблоны у разных людей.
- Не заимствуй имена, id, лор и персонажей из других новелл или старых сессий.

ОДИН BOOTSTRAP
Создай один объект и сразу вызови createBootstrapPreview с единственным полем bootstrap_json. Не показывай JSON пользователю.

Обязательное смысловое ядро:
- characters: только героиня, знакомые ей на старте значимые люди и персонажи, реально присутствующие в первой сцене;
- story_plan: открытый сюжетный компас без заранее решённого финала;
- current_state: конкретный стартовый кадр;
- future_locks.hidden_character_seeds: короткие заготовки будущих НЕЗНАКОМЫХ людей;
- scene_history=[] и turns=[].
Railway сам нормализует protagonist, relationships, knowledge, npc_state, continuity и скрытые режиссёрские технические поля.

ПЕРСОНАЖИ НА СТАРТЕ
- Ровно одна карточка cast_status=player; current_state.player_character_id указывает на неё.
- Явно описанный знакомый получает отдельную карточку known_core или known_support. Пропущенные сведения придумай.
- Значимая карточка содержит: id, name, display_name, role, age, appearance, personality, past_short, goal, habits, skills, connections; отличимую речь; способ спорить, заботиться, сближаться и реагировать на стресс/отказ; слабость и неудобный устойчивый паттерн; собственную задачу вне героини.
- Описывай наблюдаемые действия. Не делай всех тихими, понимающими психологами. Любящий человек может давить, ревновать, ошибаться и считать близость правом вмешиваться.
- Осознание ошибки не равно мгновенному изменению; под стрессом возможен возврат к старой защите.
- ids — латиница/цифры/_/-. name — латиницей; display_name можно русской транскрипцией.

БУДУЩИЕ НЕЗНАКОМЦЫ
- Не создавай им заранее имя, внешность или полную карточку в characters.
- Для каждого нужного направления добавь seed: id, role, story_function, entry_condition, earliest_turn, notes_for_engine, known_to_player=false, introduced=false, generate_full_card_on_first_appearance=true.
- Seed — условие и функция, не готовый человек. Полная карточка будет создана только в той сцене, где персонаж действительно появится.

STORY PLAN
Заполни genre, language, tone, setting_summary, main_premise, protagonist_start, player_goal, central_conflict, central_question, opening_scene_intent, act_structure, character_arcs, relationship_focus, open_threads, forbidden_drift, current_story_position и ровно два status_slots.
- Актам дай разные конкретные goal/must_happen, но не назначай единственный исход.
- Романтика и отношения остаются центром; мистика не превращается в бесконечное расследование артефакта, если пользователь этого не просил.
- Мир и NPC действуют при пассивности игрока, но не принимают важные решения за героиню.

CURRENT STATE
Заполни turn_number=0, last_player_input="", date, time, location, weather, scene_state, scene_goal, outfit, inventory, nearby_items, environment, active_character_ids, nearby_character_ids, status и time_skip_control. В active/nearby — только реально доступные стартовые персонажи. На старте time_skip_control.allowed=false и blockers=["opening_scene_not_played"].

ЗАПРОС ПОЛЬЗОВАТЕЛЯ:
{request_json}

После createBootstrapPreview покажи полный preview и жди явного подтверждения. Первую сцену до подтверждения не начинай.
""".strip()



def _one_line(value: Any, fallback: str = "—") -> str:
    if value is None:
        return fallback
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if str(item).strip()) or fallback
    if isinstance(value, dict):
        return "; ".join(f"{key}: {item}" for key, item in value.items()) or fallback
    text = str(value).strip()
    return text or fallback



def _visible_name(card: dict[str, Any]) -> str:
    for key in ("display_name", "visible_name", "name_ru", "russian_name", "name"):
        value = card.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "—"



def _short_list(items: Any, limit: int = 5) -> list[str]:
    if not isinstance(items, list):
        return []
    return [str(item) for item in items[:limit] if str(item).strip()]


def _visible_role(value: Any) -> str:
    role = _one_line(value)
    lowered = role.lower().replace("_", " ")
    mappings = (
        (("player character", "protagonist", "героин"), "главная героиня"),
        (("older brother", "elder brother", "старший брат"), "старший брат"),
        (("best friend", "лучшая подруга"), "лучшая подруга"),
        (("childhood friend", "друг детства"), "друг детства"),
        (("friend's mother", "friend mother", "мать друга"), "мать друга детства"),
        (("coworker", "colleague", "коллег"), "коллега"),
    )
    for markers, label in mappings:
        if any(marker in lowered for marker in markers):
            return label
    return role


def _appearance_text(card: dict[str, Any]) -> str:
    appearance = card.get("appearance") if isinstance(card.get("appearance"), dict) else {}
    labels = {
        "height": "рост",
        "build": "телосложение",
        "hair": "волосы",
        "eyes": "глаза",
        "face": "лицо",
        "style": "одежда",
    }
    parts = [f"{labels[key]} — {_one_line(appearance.get(key))}" for key in labels if appearance.get(key)]
    return "; ".join(parts) or "—"



def _profile_lines(card: dict[str, Any]) -> list[str]:
    behavior = card.get("behavior") if isinstance(card.get("behavior"), dict) else {}
    speech = card.get("speech_profile") if isinstance(card.get("speech_profile"), dict) else {}
    life = card.get("life_outside_player") if isinstance(card.get("life_outside_player"), dict) else {}
    personality = card.get("personality") if isinstance(card.get("personality"), dict) else {}
    return [
        f"  - **Характер:** {_one_line(personality.get('core'))}. **Слабости:** {_one_line(personality.get('flaws'))}.",
        f"  - **Забота и конфликт:** {_one_line(behavior.get('care_style'))}; {_one_line(behavior.get('conflict_style'))}",
        f"  - **Манера речи:** {_one_line(speech.get('baseline'))}",
        f"  - **Своя жизнь:** {_one_line(life.get('current_obligation'))}; {_one_line(life.get('private_problem'))}",
    ]



def _append_character(lines: list[str], card: dict[str, Any]) -> None:
    lines.append(f"- **{_visible_name(card)}** — {_visible_role(card.get('role'))}, {_one_line(card.get('age'))}")
    lines.append(f"  - **Внешность:** {_appearance_text(card)}")
    lines.append(f"  - **Прошлое:** {_one_line(card.get('past_short'))}")
    lines.append(f"  - **Собственная цель:** {_one_line(card.get('goal'))}")
    lines.extend(_profile_lines(card))



def build_setup_preview(
    bootstrap_json: dict[str, Any],
    *,
    user_request: dict[str, Any] | None = None,
) -> str:
    data = normalize_bootstrap_json(bootstrap_json)
    prepare_bootstrap_cast(data)
    protagonist = data.get("protagonist") or {}
    characters = data.get("characters") or {}
    relationships = data.get("relationships") or {}
    story_plan = data.get("story_plan") or {}
    current_state = data.get("current_state") or {}
    pc_id = protagonist.get("id") or current_state.get("player_character_id") or "pc_01"
    pc_card = characters.get(pc_id, protagonist if isinstance(protagonist, dict) else {}) or {}
    visible_ids = visible_character_ids(data)

    lines: list[str] = [
        "## Черновик новеллы",
        "",
        "Проверь героиню, знакомых ей людей и открытое направление истории. Будущие незнакомцы, скрытые причины и служебные данные здесь не раскрываются.",
        "",
    ]

    lines.extend([
        "### Главная героиня",
        f"- **Имя:** {_visible_name(pc_card)}",
        f"- **Возраст:** {_one_line(pc_card.get('age'))}",
        f"- **Внешность:** {_appearance_text(pc_card)}",
        f"- **Прошлое:** {_one_line(pc_card.get('past_short'))}",
        f"- **Цель:** {_one_line(pc_card.get('goal'))}",
    ])
    lines.extend(_profile_lines(pc_card))
    lines.append("")

    lines.extend([
        "### Где начинается история",
        f"- **Где стартуем:** {_one_line(current_state.get('location'))}",
        f"- **Дата/время:** {_one_line(current_state.get('date'))} · {_one_line(current_state.get('time'))}",
        f"- **Погода/атмосфера:** {_one_line(current_state.get('weather'))}",
        f"- **Состояние сцены:** {_one_line(current_state.get('scene_state'))}",
        f"- **Одежда:** {_one_line(current_state.get('outfit'))}",
        f"- **При себе:** {_one_line(current_state.get('inventory'))}",
        "",
    ])

    known_core = [card for cid, card in characters.items() if cid != pc_id and cid in visible_ids and card.get("cast_status") == "known_core"]
    known_support = [card for cid, card in characters.items() if cid != pc_id and cid in visible_ids and card.get("cast_status") == "known_support"]

    known_characters = [*known_core, *known_support]
    lines.append("### Люди, которых героиня уже знает")
    if known_characters:
        for card in known_characters[:10]:
            _append_character(lines, card)
    else:
        lines.append("- Значимые знакомые появятся естественно из выбранного старта.")
    lines.append("")

    lines.extend([
        "### Открытое направление истории",
        f"- **Жанр:** {_one_line(story_plan.get('genre'))}",
        f"- **Тон:** {_one_line(story_plan.get('tone'))}",
        f"- **Сеттинг:** {_one_line(story_plan.get('setting_summary'))}",
        f"- **Главная завязка:** {_one_line(story_plan.get('main_premise'))}",
        f"- **Цель героини:** {_one_line(story_plan.get('player_goal'))}",
        f"- **Главный конфликт:** {_one_line(story_plan.get('central_conflict'))}",
        f"- **Вопрос истории:** {_one_line(story_plan.get('central_question'))}",
        f"- **Стартовая сцена должна:** {_one_line(story_plan.get('opening_scene_intent'))}",
    ])
    open_threads = _short_list(story_plan.get("open_threads"), 6)
    if open_threads:
        lines.append("- **Открытые нити:** " + "; ".join(open_threads))
    forbidden = _short_list(story_plan.get("forbidden_drift"), 6)
    if forbidden:
        lines.append("- **Не уводить в:** " + "; ".join(forbidden))
    lines.append("")

    visible_relationships = []
    for relation in relationships.values():
        if not isinstance(relation, dict):
            continue
        a = relation.get("character_a")
        b = relation.get("character_b")
        if a in visible_ids and b in visible_ids:
            visible_relationships.append(relation)
    if visible_relationships:
        lines.append("### Стартовые отношения")
        for relation in visible_relationships[:12]:
            a_card = characters.get(relation.get("character_a"), {})
            b_card = characters.get(relation.get("character_b"), {})
            shared = relation.get("shared") if isinstance(relation.get("shared"), dict) else {}
            status = shared.get("status") or relation.get("status")
            lines.append(f"- **{_visible_name(a_card)} ↔ {_visible_name(b_card)}:** {_one_line(status)}")
            relationship_threads = _short_list(shared.get("unresolved_threads") or relation.get("open_threads"), 2)
            if relationship_threads:
                lines.append("  - **Незакрыто:** " + "; ".join(relationship_threads))
        lines.append("")

    lines.extend([
        "### Что дальше",
        "Напиши `подтверждаю`, если всё подходит. Или укажи, что изменить: героиню, конкретного знакомого, его поведение, речь, отношения, сеттинг, стартовую сцену или план.",
    ])
    # The original questionnaire is already preserved verbatim in
    # user_request.json. Echoing it here duplicated long text and obscured the
    # actual review surface, so preview shows the structured canon only.
    _ = user_request
    return "\n".join(lines)
