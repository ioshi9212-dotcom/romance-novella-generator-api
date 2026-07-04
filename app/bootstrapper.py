from typing import Any
from app.id_utils import now_iso, slugify_id, pair_id


BASE_FILES = [
    "session.json",
    "user_request.json",
    "protagonist.json",
    "characters.json",
    "relationships.json",
    "knowledge.json",
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
Ты создаёшь новую интерактивную новеллу.

ВАЖНО:
- Это генератор, готового канона нет.
- Не используй персонажей из чужих историй.
- Создай только то, что нужно для старта.
- Всё, что создано, будет сохранено как state.
- Базовые анкеты персонажей должны быть короткими, но полезными.
- Один персонаж = одна анкета.
- Не создавай три файла main/character/knowledge.
- Не раскрывай будущих важных персонажей полностью, если героиня/герой их ещё не знает.
- Для неизвестных будущих фигур делай только seed.
- Создай ровно два story-specific status slots для нижнего блока сцены.
- В current_state обязательно заполни: date, time, location, weather, scene_state, outfit, inventory, nearby_items.
- В current_state.status обязательно заполни: hunger, fatigue, injuries, emotional_state, skills, custom[2].
- Будущие сцены должны поддерживать шапку, 3 мысли, 3 реплики, 3 действия, состояние и отношения в сцене.

ЕСЛИ ДАННЫХ СЛИШКОМ МАЛО:
- Если запрос похож только на «начнем/начнём/старт», верни анкету из prompts/start_questionnaire.md вместо случайного bootstrap.

ЗАПРОС ПОЛЬЗОВАТЕЛЯ:
{user_request}

Верни СТРОГО JSON без markdown по схеме prompts/bootstrap_story.md.
""".strip()


def local_stub_bootstrap(session_id: str, user_request: dict[str, Any]) -> dict[str, Any]:
    language = user_request.get("language") or "ru"
    genre = user_request.get("genre") or "romance"
    tone = user_request.get("tone") or "grounded, emotional"
    setting_request = user_request.get("setting_request") or "small seaside town"
    protagonist_request = user_request.get("protagonist_request") or "guarded adult protagonist"

    protagonist_id = "protagonist"
    mother_id = "mother"
    friend_id = "best_friend"
    ex_id = "ex_partner"

    protagonist = {
        "id": protagonist_id,
        "name": "Ника Мор",
        "role": "protagonist",
        "age": 27,
        "introduced": True,
        "known_to_player": True,
        "locked": True,
        "appearance": {
            "height": "средний рост",
            "build": "стройная, не хрупкая",
            "hair": "тёмные волосы, обычно собраны быстро и небрежно",
            "eyes": "серо-зелёные",
            "style": "простая одежда, старые куртки, минимум украшений"
        },
        "personality": {
            "core": ["наблюдательная", "сдержанная", "упрямая"],
            "flaws": ["замыкается вместо честного разговора", "режет фразы, когда больно"],
            "speech": "коротко, спокойно, иногда сухо"
        },
        "past_short": f"Вернулась туда, откуда однажды уехала после личного конфликта. Стартовый запрос: {protagonist_request}",
        "habits": [
            "проверяет выходы в незнакомых местах",
            "отвечает спокойнее, чем чувствует",
            "трогает рукав, когда нервничает"
        ],
        "skills": ["наблюдательность", "самоконтроль"],
        "connections": [
            {"character_id": mother_id, "relation": "mother", "summary": "Любят друг друга, но избегают прямых разговоров."},
            {"character_id": friend_id, "relation": "old friend", "summary": "Дружба сохранилась, но между ними есть пропущенные годы."},
            {"character_id": ex_id, "relation": "ex-partner", "summary": "Расстались плохо. Оба знают только свою половину истории."}
        ]
    }

    characters = {
        protagonist_id: protagonist,
        mother_id: {
            "id": mother_id,
            "name": "Марина Мор",
            "role": "mother",
            "age": 52,
            "introduced": False,
            "known_to_player": True,
            "locked": True,
            "appearance": {
                "height": "невысокая",
                "build": "мягкая, уставшая",
                "hair": "русые волосы с сединой",
                "eyes": "светлые, внимательные",
                "style": "домашние кофты, старое пальто"
            },
            "personality": {
                "core": ["заботливая", "упрямая", "молчаливая"],
                "flaws": ["скрывает плохие новости", "давит заботой"],
                "speech": "мягко, но с внутренним контролем"
            },
            "past_short": "Осталась в родном городе и не простила дочери внезапный отъезд.",
            "connections": [
                {"character_id": protagonist_id, "relation": "daughter", "summary": "Тёплая связь с сильным напряжением."}
            ]
        },
        friend_id: {
            "id": friend_id,
            "name": "Лея Ворон",
            "role": "old friend",
            "age": 27,
            "introduced": False,
            "known_to_player": True,
            "locked": True,
            "appearance": {
                "height": "чуть ниже главной героини",
                "build": "подвижная",
                "hair": "короткие светло-каштановые волосы",
                "eyes": "карие",
                "style": "яркие детали, удобная одежда"
            },
            "personality": {
                "core": ["шумная", "прямая", "верная"],
                "flaws": ["лезет туда, куда её не просили", "шутит, когда страшно"],
                "speech": "быстро, живо, без лишней дипломатии"
            },
            "past_short": "Осталась в городе и знает больше местных слухов, чем признаёт.",
            "connections": [
                {"character_id": protagonist_id, "relation": "best friend", "summary": "Близкие подруги, которым нужно заново привыкнуть друг к другу."}
            ]
        },
        ex_id: {
            "id": ex_id,
            "name": "Данил Кросс",
            "role": "ex-partner",
            "age": 29,
            "introduced": False,
            "known_to_player": True,
            "locked": True,
            "appearance": {
                "height": "высокий",
                "build": "сухой, крепкий",
                "hair": "тёмные волосы",
                "eyes": "тёмные",
                "style": "рабочая куртка, простые вещи, ничего лишнего"
            },
            "personality": {
                "core": ["молчаливый", "собранный", "язвительный"],
                "flaws": ["не объясняется первым", "держит обиду как факт"],
                "speech": "коротко, с паузами, без признаний в лоб"
            },
            "past_short": "Бывший партнёр главной героини. После разрыва остался в городе.",
            "connections": [
                {"character_id": protagonist_id, "relation": "ex", "summary": "Незакрытая история. Оба считают, что второй ушёл первым."}
            ]
        }
    }

    relationships = {
        pair_id(protagonist_id, mother_id): {
            "type": "mother_child",
            "trust": 55,
            "tension": 45,
            "attachment": 75,
            "status": "любовь есть, честности мало",
            "known_history": "Они давно не говорили прямо о причине отъезда.",
            "open_threads": ["мать знает больше о прошлом конфликте, чем говорит"]
        },
        pair_id(protagonist_id, friend_id): {
            "type": "old_friendship",
            "trust": 65,
            "tension": 20,
            "attachment": 70,
            "status": "тепло с неловкостью после долгой паузы",
            "known_history": "Подруга осталась в городе, героиня уехала.",
            "open_threads": ["подруга может стать проводником по изменениям города"]
        },
        pair_id(protagonist_id, ex_id): {
            "type": "exes",
            "trust": 20,
            "tension": 85,
            "attachment": 55,
            "status": "незакрытый разрыв",
            "known_history": "Расстались плохо и не договорили.",
            "open_threads": ["причина разрыва раскрывается постепенно"]
        }
    }

    knowledge = {
        protagonist_id: {
            "knows": [
                "она вернулась",
                "мать ждёт её дома",
                "бывший может всё ещё жить в городе"
            ],
            "does_not_know": [
                "что именно изменилось за время её отсутствия",
                "что бывший думает о её возвращении",
                "какую часть старой истории скрывает мать"
            ]
        },
        mother_id: {
            "knows": [
                "дочь возвращается",
                "город изменился",
                "старый конфликт не закрыт"
            ],
            "does_not_know": [
                "готова ли дочь остаться",
                "что дочь чувствует к бывшему сейчас"
            ]
        },
        friend_id: {
            "knows": [
                "главная героиня вернулась",
                "в городе есть слухи вокруг старого разрыва"
            ],
            "does_not_know": [
                "зачем героиня вернулась на самом деле"
            ]
        },
        ex_id: {
            "knows": [
                "главная героиня когда-то уехала",
                "их разрыв не был нормально проговорён"
            ],
            "does_not_know": [
                "что она уже вернулась",
                "почему она вернулась"
            ]
        }
    }

    story_plan = {
        "genre": genre,
        "language": language,
        "tone": tone,
        "main_premise": f"Героиня возвращается в место, связанное с незакрытым прошлым. Сеттинг: {setting_request}",
        "act_structure": [
            {
                "act": 1,
                "goal": "возвращение, дискомфорт, первые следы старого конфликта",
                "must_happen": ["героиня прибывает", "город ощущается знакомым и чужим", "бывший сначала упоминается, но не обязан появляться сразу"]
            },
            {
                "act": 2,
                "goal": "вынужденный контакт, столкновение версий прошлого",
                "must_happen": ["героиня встречает важного человека", "старые обиды мешают прямому разговору"]
            },
            {
                "act": 3,
                "goal": "постепенное раскрытие правды",
                "must_happen": ["одна старая ложь или ошибка выходит наружу", "отношения меняются, но не чинятся мгновенно"]
            }
        ],
        "status_slots": [
            {
                "id": "story_slot_1",
                "label": "Репутация в городе",
                "description": "Как местные воспринимают возвращение героини и слухи вокруг неё.",
                "initial_value": "нейтрально, но слухи могут всплыть"
            },
            {
                "id": "story_slot_2",
                "label": "Давление старой тайны",
                "description": "Насколько близко сцена подходит к скрытой причине прошлого конфликта.",
                "initial_value": "низкое"
            }
        ],
        "forbidden_drift": [
            "не решать главный конфликт слишком рано",
            "не делать NPC терапевтами",
            "не добавлять случайный любовный треугольник без setup",
            "не менять locked-анкету персонажа без явной причины"
        ],
        "current_story_position": "act_1_start"
    }

    current_state = {
        "turn_number": 0,
        "date": "Day 1",
        "time": "17:40",
        "location": "автостанция у маленького приморского города",
        "weather": "пасмурно, холодный ветер с моря",
        "scene_state": "мокрый асфальт, остывающий автобус, редкие машины, город кажется знакомым и чужим",
        "player_character_id": protagonist_id,
        "active_character_ids": [protagonist_id],
        "nearby_character_ids": [],
        "scene_goal": "Начать историю с возвращения героини и дать игроку почувствовать место.",
        "last_player_input": "",
        "outfit": "старая тёмная куртка, свитер, дорожные ботинки",
        "inventory": ["телефон", "сумка", "билет", "ключи"],
        "nearby_items": ["старое табло", "закрытый цветочный киоск", "остановившийся автобус"],
        "environment": {
            "light": "пасмурный вечер",
            "sound": "остывающий автобус, чайки, редкие машины",
            "air": "соль, мокрый асфальт, холодный ветер",
            "details": ["старое табло", "закрытый цветочный киоск", "море между домами"]
        },
        "status": {
            "hunger": "лёгкий голод",
            "fatigue": "средняя после дороги",
            "injuries": [],
            "emotional_state": "собранная, закрытая",
            "skills": ["наблюдательность", "самоконтроль"],
            "custom": [
                {"id": "story_slot_1", "label": "Репутация в городе", "value": "нейтрально, но слухи могут всплыть"},
                {"id": "story_slot_2", "label": "Давление старой тайны", "value": "низкое"}
            ]
        }
    }

    return {
        "session": {
            "session_id": session_id,
            "title": user_request.get("title") or "Untitled novella",
            "status": "active",
            "engine_version": "novella-generator-starter-v4",
            "created_at": now_iso(),
            "updated_at": now_iso()
        },
        "user_request": user_request,
        "protagonist": protagonist,
        "characters": characters,
        "relationships": relationships,
        "knowledge": knowledge,
        "story_plan": story_plan,
        "current_state": current_state,
        "npc_state": {},
        "future_locks": {
            "hidden_character_seeds": [
                {
                    "id": "future_major_character_1",
                    "role": "possible major character",
                    "known_to_player": False,
                    "introduced": False,
                    "generate_full_card_on_first_appearance": True,
                    "notes_for_engine": "Не раскрывать заранее. Полная анкета создаётся только при сценическом входе."
                }
            ],
            "do_not_reveal_yet": [
                "полная причина старого разрыва",
                "скрытая роль матери в прошлом конфликте"
            ]
        },
        "continuity": {
            "locked_facts": [
                "Базовые анкеты персонажей locked после bootstrap.",
                "Отношения меняются через relationships, а не переписыванием анкеты.",
                "Знания NPC меняются через knowledge, только если есть сценический источник."
            ],
            "style": {
                "player_agency": "не делать важный выбор за игрока",
                "scene_length": "средняя, без воды",
                "dialogue": "живой, не объяснять всё напрямую"
            }
        },
        "scene_history": [],
        "turns": []
    }
