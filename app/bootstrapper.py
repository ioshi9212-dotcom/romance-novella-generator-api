from typing import Any
from app.id_utils import now_iso, pair_id


BASE_FILES = [
    "session.json",
    "user_request.json",
    "protagonist.json",
    "characters_index.json",
    "state/knowledge_index.json",
    "state/relationship_index.json",
    "story_plan.json",
    "current_state.json",
    "npc_state.json",
    "future_locks.json",
    "continuity.json",
    "scene_history.json",
    "turns.json",
]


def build_bootstrap_prompt(user_request: dict[str, Any]) -> str:
    return f"""
Ты создаёшь новую интерактивную новеллу с нуля.

ВАЖНО:
- Это генератор, готового канона нет.
- GitHub хранит только правила, схемы, шаблоны и сборщик.
- Конкретные персонажи, лор, отношения, знания и сюжет создаются здесь. Сначала они показываются пользователю как preview, и только после подтверждения сохраняются в state конкретной Railway-сессии.
- Не используй персонажей, имена, id, лор или связи из старых новелл, старых сессий или любых готовых историй.
- Один персонаж = одна короткая анкета в `characters/<character_id>.json`.
- Создай для каждого значимого персонажа свой уникальный `character_id` внутри этой сессии.
- Не используй заранее заданные id и имена из готовых историй.
- Не создавай три файла main/character/knowledge/past на персонажа.
- Базовые анкеты персонажей должны быть короткими, но полезными для поведения.
- Для значимых персонажей заполни goal, habits, likes_in_people, dislikes_in_people, relationship_triggers.
- Имена и фамилии персонажей должны быть не русскими, не славянскими, латиницей, в западно-японской/англо-японской стилистике.
- Не используй кириллицу в поле name. Не копируй имена из примеров, чужих новелл или старых сессий.
- `character_id` — машинный id этой сессии. Он создаётся в bootstrap и дальше используется для карточки, знаний и отношений. Не привязывай id к готовым именам.
- Не раскрывай будущих важных персонажей полностью, если персонаж игрока их ещё не знает.
- Для неизвестных будущих фигур делай только seed в future_locks.hidden_character_seeds, без имени и без полной карточки.
- Создай подробный story_plan: setting_summary, main_premise, protagonist_start, player_goal, central_conflict, central_question, opening_scene_intent, opening_pacing, scene_focus_rules, act_structure, character_arcs, relationship_focus, open_threads, forbidden_drift и ровно два story-specific status slots.
- player_goal — это личная цель героини, а не цель всего мира.
- NPC имеют собственные цели, маршруты, знания, страхи, сроки и желания. Они не обязаны хотеть того же, что хочет героиня.
- Не создавай NPC как консультантов, навигаторов, справочники, психологов, квестодателей или людей, которые ждут решения героини.
- В npc_state для значимых NPC задай коротко: current_goal, current_route, current_pressure, next_self_action_if_ignored.
- Если пользователь просит романтическую мистику / дораму / фэнтези / лёгкий хоррор / историю про видения, первые 2–3 сцены должны быть вводными: героиня, работа/быт, ближайшие NPC, обычная динамика, слабая мистика. Не начинай сразу с главной угрозы, договора, долга, квеста, пропажи, расследования, карты, записки или мистической процедуры.
- Мистика должна запускать отношения, ревность, недоверие, защиту, притяжение или конфликт, а не заменять их квестом.
- В current_state обязательно заполни: date, time, location, weather, scene_state, outfit, inventory, nearby_items.
- В current_state.status обязательно заполни: hunger, fatigue, injuries, emotional_state, skills, custom[2].
- Будущие сцены должны поддерживать игровую шапку без POV, 3 мысли, 3 реплики, 3 действия, состояние и отношения в сцене.

ЕСЛИ ДАННЫХ СЛИШКОМ МАЛО:
- Если запрос похож только на «начнем/начнём/старт», не создавай случайную историю.
- Верни видимый текст анкеты из prompts/start_questionnaire.md.

ЗАПРОС ПОЛЬЗОВАТЕЛЯ:
{user_request}

Верни СТРОГО JSON без markdown по схеме prompts/bootstrap_story.md. Не пиши первую сцену: этот JSON сначала будет превращён в preview для подтверждения пользователя.
""".strip()


def debug_stub_bootstrap(session_id: str, user_request: dict[str, Any]) -> dict[str, Any]:
    """Purely technical test data. Not canon, not default story content."""
    language = user_request.get("language") or "ru"
    genre = user_request.get("genre") or "debug novella"
    tone = user_request.get("tone") or "technical debug"
    setting_request = user_request.get("setting_request") or "debug location"
    protagonist_request = user_request.get("protagonist_request") or "debug player character"

    protagonist_id = "pc_debug_01"
    support_id = "npc_debug_witness_01"

    protagonist = {
        "id": protagonist_id,
        "name": "Debug Player",
        "role": "protagonist",
        "age": 25,
        "introduced": True,
        "known_to_player": True,
        "locked": True,
        "appearance": {
            "height": "не задано",
            "build": "не задано",
            "hair": "не задано",
            "eyes": "не задано",
            "face": "не задано",
            "style": "не задано",
        },
        "personality": {
            "core": ["debug placeholder"],
            "flaws": [],
            "speech": "нейтрально, без канона",
        },
        "goal": "debug: проверить ход сцены",
        "past_short": f"Техническая анкета для проверки. Стартовый запрос: {protagonist_request}",
        "habits": ["debug placeholder habit"],
        "likes_in_people": ["clear visible actions"],
        "dislikes_in_people": ["unsupported assumptions"],
        "relationship_triggers": {"improves_when": ["clear source is provided"], "worsens_when": ["source is missing"]},
        "skills": ["debug observation"],
        "connections": [
            {"character_id": support_id, "relation": "debug witness", "summary": "Техническая связь для проверки отношений."}
        ],
    }

    support_npc = {
        "id": support_id,
        "name": "Debug Witness",
        "role": "debug witness",
        "age": 30,
        "introduced": False,
        "known_to_player": True,
        "locked": True,
        "appearance": {
            "height": "не задано",
            "build": "не задано",
            "hair": "не задано",
            "eyes": "не задано",
            "face": "не задано",
            "style": "не задано",
        },
        "personality": {
            "core": ["debug placeholder"],
            "flaws": [],
            "speech": "коротко",
        },
        "goal": "debug: быть свидетелем проверки",
        "past_short": "Тестовый NPC без сюжетного канона.",
        "habits": ["debug placeholder habit"],
        "likes_in_people": ["clear visible actions"],
        "dislikes_in_people": ["unsupported assumptions"],
        "relationship_triggers": {"improves_when": ["clear source is provided"], "worsens_when": ["source is missing"]},
        "skills": [],
        "connections": [
            {"character_id": protagonist_id, "relation": "debug witness", "summary": "Техническая связь."}
        ],
    }

    characters = {protagonist_id: protagonist, support_id: support_npc}
    relationships = {
        pair_id(protagonist_id, support_id): {
            "type": "debug_relation",
            "trust": 50,
            "tension": 0,
            "attachment": 0,
            "status": "тестовая связь",
            "known_history": "нет сюжетной истории",
            "open_threads": [],
            "scores": {"trust": 50, "tension": 0, "attachment": 0, "respect": 0, "fear": 0},
            "a_view_of_b": {"summary": "debug-only view", "current_assumption": "none"},
            "b_view_of_a": {"summary": "debug-only view", "current_assumption": "none"},
        }
    }
    knowledge = {
        protagonist_id: {
            "character_id": protagonist_id,
            "known_facts": [{"text": "это техническая debug-сессия", "source_type": "system_debug", "certainty": "high"}],
            "observations": [],
            "assumptions": [],
            "wrong_beliefs": [],
            "does_not_know": [],
            "must_not_assume": ["не считать debug-данные каноном истории"],
            "recent_memories": [],
            "open_questions": [],
            "knows": ["это техническая debug-сессия"],
            "history": [],
        },
        support_id: {
            "character_id": support_id,
            "known_facts": [{"text": "это техническая debug-сессия", "source_type": "system_debug", "certainty": "high"}],
            "observations": [],
            "assumptions": [],
            "wrong_beliefs": [],
            "does_not_know": [],
            "must_not_assume": [],
            "recent_memories": [],
            "open_questions": [],
            "knows": ["это техническая debug-сессия"],
            "history": [],
        },
    }
    story_plan = {
        "genre": genre,
        "language": language,
        "tone": tone,
        "main_premise": f"Техническая проверка сборки. Запрошенный сеттинг: {setting_request}",
        "player_goal": "debug: проверить личную цель персонажа игрока отдельно от целей NPC",
        "opening_pacing": "debug: не начинать с канонной угрозы",
        "scene_focus_rules": ["NPC имеют собственные действия"],
        "act_structure": [
            {"act": 1, "goal": "проверить создание сессии и scene_contract", "must_happen": ["создать state", "собрать contract", "сохранить turn"]}
        ],
        "status_slots": [
            {"id": "story_slot_1", "label": "Debug slot 1", "description": "Техническое поле", "initial_value": "не задано"},
            {"id": "story_slot_2", "label": "Debug slot 2", "description": "Техническое поле", "initial_value": "не задано"},
        ],
        "forbidden_drift": ["не превращать debug_stub в готовый канон"],
        "current_story_position": "debug_start",
    }
    current_state = {
        "turn_number": 0,
        "date": "Day 1",
        "time": "00:00",
        "location": "debug location",
        "weather": "debug atmosphere",
        "scene_state": "проверка сборки без внутреннего LLM",
        "player_character_id": protagonist_id,
        "active_character_ids": [protagonist_id],
        "nearby_character_ids": [],
        "scene_goal": "проверить формат шапки и сохранение state",
        "last_player_input": "",
        "outfit": "debug outfit",
        "inventory": ["debug item"],
        "nearby_items": [],
        "environment": {"light": "debug", "sound": "debug", "air": "debug", "details": []},
        "status": {
            "hunger": "норма",
            "fatigue": "низкая",
            "injuries": [],
            "emotional_state": "нейтрально",
            "skills": ["debug observation"],
            "custom": [
                {"id": "story_slot_1", "label": "Debug slot 1", "value": "не задано"},
                {"id": "story_slot_2", "label": "Debug slot 2", "value": "не задано"},
            ],
        },
    }
    created_at = now_iso()
    session = {
        "session_id": session_id,
        "title": user_request.get("title") or "Debug novella session",
        "status": "active",
        "engine_version": "novella-generator-gpt-actions-v8",
        "created_at": created_at,
        "updated_at": created_at,
    }
    return {
        "session": session,
        "user_request": user_request,
        "protagonist": protagonist,
        "characters": characters,
        "relationships": relationships,
        "knowledge": knowledge,
        "story_plan": story_plan,
        "current_state": current_state,
        "npc_state": {
            support_id: {
                "current_goal": "debug: сохранять независимую цель",
                "current_route": "debug: присутствовать как свидетель",
                "current_pressure": "debug: нет давления",
                "next_self_action_if_ignored": "debug: продолжить свою проверку",
            }
        },
        "future_locks": {"hidden_character_seeds": [], "do_not_reveal_yet": []},
        "continuity": {"locked_facts": []},
        "scene_history": [],
        "turns": [],
    }
