from __future__ import annotations

import json
from typing import Any

from app.bootstrap_normalizer import normalize_bootstrap_json
from app.character_profiles import prepare_bootstrap_cast, visible_character_ids



def build_bootstrap_prompt(user_request: dict[str, Any]) -> str:
    request_json = json.dumps(user_request, ensure_ascii=False, indent=2)
    return f"""
Ты создаёшь новую интерактивную визуальную новеллу с нуля.

ИСТОЧНИК ДАННЫХ
- Сохрани все конкретные факты пользователя. Не заменяй их удобными шаблонами.
- Всё, чего пользователь не указал, придумай сам логично из жанра, роли, прошлого и стартовой ситуации.
- Пустые поля, прочерки и отсутствующие пункты не являются ошибкой и не требуют новой анкеты: это разрешение придумать недостающее.
- raw_start_text хранит точный полный ответ пользователя и является главным источником при конфликте со структурированными полями.
- Явный запрет пользователя имеет приоритет над любым сгенерированным вариантом.
- Перед finalize сверь результат с запросом: каждый явно описанный знакомый и будущий значимый персонаж должен иметь карточку.
- Если finalize вернул bootstrap_repair_required, исправь перечисленные части через saveBootstrapPart и повтори finalize; служебный ответ пользователю не показывай.
- Не оставляй «будет уточняться», «не указано», «ценит честность», «не любит ложь», «живая речь» и другие заглушки.
- Значимые персонажи должны отличаться способом заботиться, спорить, сближаться, прикасаться, ревновать, ошибаться и реагировать на отказ.
- Любовь, дружба и родство не означают автоматическое уважение дистанции. Добрый человек может давить; любящий — ревновать и лезть; близкий — считать, что имеет право спрашивать повторно.
- Осознание ошибки не равно изменению. Для каждого значимого персонажа задай устойчивый неудобный паттерн и способ возврата к нему под стрессом.

СОСТАВ ПЕРСОНАЖЕЙ
Каждая карточка имеет cast_status:
- player — персонаж игрока, ровно один;
- known_core — главный человек, которого героиня уже знает: близкий друг, родственник, партнёр, бывший, важный коллега;
- known_support — знакомый второстепенный персонаж, который может участвовать в сценах;
- hidden_core — будущий значимый персонаж, с которым героиня ещё не знакома;
- background — одноразовый или малозначимый фон.

Правила состава:
- player, known_core и known_support видимы в preview.
- hidden_core создаётся СРАЗУ полной карточкой: имя, внешность, характер, прошлое, цель, поведение, речь, связи и скрытые знания.
- hidden_core: known_to_player=false, introduced=false, show_in_preview=false, available_to_scene=false.
- Не ставь hidden_core в current_state.active_character_ids/nearby_character_ids.
- Не описывай hidden_core в видимой части story_plan, preview-полях или знаниях героини.
- background не раздувай полной биографией без сюжетной причины.

ПОРЯДОК STAGED-СБОРКИ
1. Сначала выпиши для себя чек-лист всех явных фактов и всех названных пользователем ролей. Не показывай его пользователю.
2. Сохрани героиню ОДИН раз: section=characters, item_id=<её id>, value=<полная карточка>, role=player_character, cast_status=player. Не создавай сокращённую копию в protagonist.
3. Сохрани отдельную карточку каждого явно указанного знакомого и будущего значимого персонажа. Недостающие внешность, характер, прошлое и цель придумай сам.
4. Сохрани story_plan и current_state. У каждого акта должны быть свои goal/must_happen; «старт/развитие/выбор» и повтор «развить конфликт» запрещены.
5. Сама придумай и сохрани director_bible: причинную правду мира, скрытый лор, крючки, конфликты, будущие последствия, план раскрытий, функции персонажей и очередь событий. Это авторский материал GPT, а не видимый preview. Сервер только нормализует и дополняет пропущенные технические поля.
6. Вызови finalizeBootstrapPreview. Сервер сам построит protagonist, relationships, knowledge, npc_state, future_locks и continuity; пустые технические разделы не отправляй.
7. Если finalize вернул `bootstrap_repair_required`, не показывай его и не спрашивай анкету заново: прочитай repair_plan.source_request, дополни только указанные секции и повтори finalize.

КАРТОЧКА ЗНАЧИМОГО ПЕРСОНАЖА
Заполни строго по Action-схеме:
- appearance и personality;
- goal, past_short, habits, skills, connections;
- inner_logic: core_need, main_fear, blind_spot, contradiction;
- behavior: conflict_style, care_style, closeness_style, touch_style, stress_response, rejection_response, change_inertia, inconvenient_pattern;
- speech_profile: baseline, under_pressure, verbal_habits, avoids;
- life_outside_player: current_obligation, private_problem, person_or_place_that_matters;
- минимум два social_triggers: видимое поведение → личная интерпретация → обычная реакция.

Поля должны описывать ДЕЙСТВИЯ, а не моральные качества. Не пиши всем «говорит тихо/ровно», «даёт пространство», «уважает границы». У каждого свой темп, громкость, словарь и изменение речи под стрессом.

ЗНАКОМЫЕ НА СТАРТЕ
Для known_core/known_support сохрани в карточке связи, общую историю, открытые темы и собственную текущую задачу, если пользователь дал материал. Из этого сервер создаст стартовые отношения, знания и npc_state.

СКРЫТЫЕ НА СТАРТЕ
- Полная карточка hidden_core хранится в characters; сервер создаст его knowledge, npc_state и блокировку раскрытия.
- Не используй seed вместо полной карточки для будущего главного персонажа. hidden_character_seeds оставь только для действительно неопределённых далёких фигур.

СТРУКТУРА
Обязательное смысловое ядро: characters, story_plan, current_state.
- characters — объект по id; ровно одна карточка имеет cast_status=player.
- current_state.player_character_id указывает на id героини.
- turn_number=0, last_player_input="". scene_history и turns создаёт сервер.
- status_slots и current_state.status.custom — ровно два story-specific поля.
- Имена полные, латиницей, не русские/славянские; display_name можно дать русской транскрипцией.
- Не используй персонажей, имена, id и лор из 1206, Академии, других новелл, старых сессий и примеров.

STORY PLAN
Создай подробный, но открытый сюжетный компас: setting_summary, main_premise, protagonist_start, player_goal, central_conflict, central_question, opening_scene_intent, opening_pacing, scene_focus_rules, act_structure, character_arcs, relationship_focus, open_threads, forbidden_drift, current_story_position и два status_slots.
Не фиксируй единственный финал. NPC имеют собственные дела и маршруты. Первые сцены не должны превращаться в инструкцию, квест или процедуру.

РЕЖИССЁРСКИЕ ОПОРЫ
Story plan должен дать серверу материал для скрытой режиссуры: конкретную причинную основу мира, минимум две незакрытые сюжетные нити, разные функции значимых NPC, будущие последствия и три возможных ближайших давления. Это не рельсы: события адаптируются к действиям игрока и не решают выбор героини заранее.

В director_bible сохрани минимум:
- world_truth с конкретной причиной происходящего и правилами мира;
- hidden_lore и evidence_chain без раннего раскрытия;
- story_hooks и active_conflicts;
- planned_reveals, связанные с hidden_core через related_character_ids;
- у planned_reveals держи status=locked, пока вход запрещён; status=available означает, что карточку уже можно предложить ближайшей сцене;
- event_queue минимум из трёх разных событий с participants, earliest_turn и последствиями игнорирования;
- character_functions для значимых NPC.
Не копируй туда пользовательскую анкету и не раскрывай этот раздел в preview.

CURRENT STATE
Заполни конкретно date, time, location, weather, scene_state, outfit, inventory, nearby_items, environment и status. В active/nearby только реально доступные стартовые персонажи. time_skip_control на старте: allowed=false, blockers=["opening_scene_not_played"].

ЗАПРОС ПОЛЬЗОВАТЕЛЯ:
{request_json}

Не выводи JSON пользователю. Сохрани characters, story_plan, current_state и director_bible небольшими вызовами saveBootstrapPart, затем вызови finalizeBootstrapPreview. Первую сцену не пиши: сначала пользователь должен увидеть полный preview и подтвердить его.
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



def _profile_lines(card: dict[str, Any]) -> list[str]:
    inner = card.get("inner_logic") if isinstance(card.get("inner_logic"), dict) else {}
    behavior = card.get("behavior") if isinstance(card.get("behavior"), dict) else {}
    speech = card.get("speech_profile") if isinstance(card.get("speech_profile"), dict) else {}
    life = card.get("life_outside_player") if isinstance(card.get("life_outside_player"), dict) else {}
    return [
        f"  - **Внутреннее противоречие:** {_one_line(inner.get('contradiction'))}",
        f"  - **Главный страх / слепая зона:** {_one_line(inner.get('main_fear'))}; {_one_line(inner.get('blind_spot'))}",
        f"  - **Забота / конфликт:** {_one_line(behavior.get('care_style'))}; {_one_line(behavior.get('conflict_style'))}",
        f"  - **Близость / прикосновения:** {_one_line(behavior.get('closeness_style'))}; {_one_line(behavior.get('touch_style'))}",
        f"  - **Под стрессом / при отказе:** {_one_line(behavior.get('stress_response'))}; {_one_line(behavior.get('rejection_response'))}",
        f"  - **Неудобный паттерн:** {_one_line(behavior.get('inconvenient_pattern'))}",
        f"  - **Почему быстро не исправится:** {_one_line(behavior.get('change_inertia'))}",
        f"  - **Речь:** {_one_line(speech.get('baseline'))}; под давлением — {_one_line(speech.get('under_pressure'))}",
        f"  - **Своя жизнь:** {_one_line(life.get('current_obligation'))}; личная проблема — {_one_line(life.get('private_problem'))}",
    ]



def _append_character(lines: list[str], card: dict[str, Any]) -> None:
    lines.append(f"- **{_visible_name(card)}** — {_one_line(card.get('role'))}, {_one_line(card.get('age'))}")
    lines.append(f"  - **Кто это:** {_one_line(card.get('past_short'))}")
    lines.append(f"  - **Собственная цель:** {_one_line(card.get('goal'))}")
    lines.extend(_profile_lines(card))
    lines.append(f"  - **Привычки:** {_one_line(card.get('habits'))}")



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
        "Это ещё не активная сцена и не сохранённая игра. Проверь героиню, знакомых ей людей и видимый сюжетный план. Скрытые будущие персонажи и тайный лор в preview не выводятся.",
        "",
    ]

    source = user_request if isinstance(user_request, dict) else {}
    raw_start_text = source.get("raw_start_text")
    if isinstance(raw_start_text, str) and raw_start_text.strip():
        lines.extend([
            "### Исходная анкета пользователя",
            "",
            raw_start_text,
            "",
        ])
    elif source:
        visible_source = {
            key: value
            for key, value in source.items()
            if key not in {"mode", "language"}
            and value is not None
            and value != ""
            and not (isinstance(value, (list, dict, tuple)) and not value)
        }
        if visible_source:
            lines.extend([
                "### Исходные пожелания пользователя",
                "",
                "```json",
                json.dumps(visible_source, ensure_ascii=False, indent=2),
                "```",
                "",
            ])

    lines.extend([
        "### Главная героиня / персонаж игрока",
        f"- **Имя:** {_visible_name(pc_card)}",
        f"- **Возраст / роль:** {_one_line(pc_card.get('age'))} · {_one_line(pc_card.get('role'))}",
        f"- **Кто она:** {_one_line(pc_card.get('past_short'))}",
        f"- **Цель:** {_one_line(pc_card.get('goal'))}",
        f"- **Характер:** {_one_line((pc_card.get('personality') or {}).get('core'))}",
    ])
    lines.extend(_profile_lines(pc_card))
    lines.append(f"- **Привычки:** {_one_line(pc_card.get('habits'))}")
    lines.append("")

    appearance = pc_card.get("appearance") or {}
    if isinstance(appearance, dict) and appearance:
        lines.append("### Внешность героини")
        labels = {"height": "Рост", "build": "Телосложение", "hair": "Волосы", "eyes": "Глаза", "face": "Лицо", "style": "Стиль"}
        for key in ("height", "build", "hair", "eyes", "face", "style"):
            if appearance.get(key):
                lines.append(f"- **{labels[key]}:** {_one_line(appearance.get(key))}")
        lines.append("")

    lines.extend([
        "### Жизнь и стартовое положение",
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

    lines.append("### Главные люди, которых героиня уже знает")
    if known_core:
        for card in known_core[:8]:
            _append_character(lines, card)
    else:
        lines.append("- На старте нет главных знакомых персонажей.")
    lines.append("")

    if known_support:
        lines.append("### Второстепенные знакомые")
        for card in known_support[:8]:
            _append_character(lines, card)
        lines.append("")

    lines.extend([
        "### План новеллы без спойлеров",
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

    act_structure = story_plan.get("act_structure") or []
    if isinstance(act_structure, list) and act_structure:
        lines.append("### Сюжетный компас")
        for act in act_structure[:4]:
            if isinstance(act, dict):
                lines.append(f"- **{act.get('act') or act.get('id') or 'акт'}:** {_one_line(act.get('goal'))}. Важно: {_one_line(act.get('must_happen'))}")
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
            scores = relation.get("scores") or {}
            score_line = ", ".join(f"{key}: {value}" for key, value in scores.items()) if scores else "уровни будут уточняться сценами"
            lines.append(f"- **{_visible_name(a_card)} ↔ {_visible_name(b_card)}:** {_one_line(relation.get('status'))}. {score_line}")
            open_threads = _short_list(relation.get("open_threads"), 3)
            if open_threads:
                lines.append("  - **Незакрыто:** " + "; ".join(open_threads))
        lines.append("")

    lines.extend([
        "### Что дальше",
        "Напиши `подтверждаю`, если всё подходит. Или укажи, что изменить: героиню, конкретного знакомого, его поведение, речь, отношения, сеттинг, стартовую сцену или план.",
    ])
    return "\n".join(lines)
