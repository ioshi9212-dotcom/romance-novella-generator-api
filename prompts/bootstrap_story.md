# Bootstrap Story Prompt

Ты создаёшь новую интерактивную новеллу с нуля.

## Главное

В этой системе нет готового канона. Всё, что ты создаёшь, будет сохранено в state конкретной сессии.

GitHub хранит только правила и шаблоны. Конкретные персонажи, отношения, знания и сюжет создаются здесь.

## Нельзя

- Не используй персонажей из 1206, Академии, Акиры, Райдена, Хару и любых других готовых историй.
- Не создавай огромные анкеты.
- Не создавай три файла на персонажа.
- Не раскрывай заранее полные анкеты будущих важных персонажей, если персонаж игрока их ещё не знает.
- Не делай сюжет полностью закрытым романом. Нужны направляющие, а не весь финал.

## Нужно создать

Верни СТРОГО JSON:

```json
{
  "protagonist": {},
  "characters": {},
  "relationships": {},
  "knowledge": {},
  "story_plan": {},
  "current_state": {},
  "npc_state": {},
  "future_locks": {},
  "continuity": {},
  "scene_history": [],
  "turns": []
}
```

## Персонаж

Один персонаж = одна короткая анкета:

```json
{
  "id": "string",
  "name": "string",
  "role": "protagonist | mother | friend | ex | etc",
  "age": 25,
  "introduced": true,
  "known_to_player": true,
  "locked": true,
  "appearance": {
    "height": "string",
    "build": "string",
    "hair": "string",
    "eyes": "string",
    "face": "string",
    "style": "string"
  },
  "personality": {
    "core": ["string"],
    "flaws": ["string"],
    "speech": "string"
  },
  "past_short": "short but useful",
  "habits": ["string"],
  "skills": ["короткие практические навыки / ресурс персонажа"],
  "connections": [
    {
      "character_id": "string",
      "relation": "string",
      "summary": "string"
    }
  ]
}
```

## characters

`characters` — объект по id:

```json
{
  "protagonist": { "...": "..." },
  "mother": { "...": "..." },
  "ex_partner": { "...": "..." }
}
```

## relationships

```json
{
  "protagonist__ex_partner": {
    "type": "exes",
    "trust": 20,
    "tension": 80,
    "attachment": 55,
    "status": "unfinished",
    "known_history": "short",
    "open_threads": ["string"]
  }
}
```

## knowledge

```json
{
  "protagonist": {
    "knows": ["string"],
    "does_not_know": ["string"],
    "must_not_assume": ["string"]
  }
}
```

## story_plan

```json
{
  "genre": "string",
  "language": "ru",
  "tone": "string",
  "main_premise": "string",
  "act_structure": [
    {
      "act": 1,
      "goal": "string",
      "must_happen": ["string"]
    }
  ],
  "status_slots": [
    {
      "id": "story_slot_1",
      "label": "Репутация / Магия / Риск / etc",
      "description": "Что отслеживает это поле в конкретной истории",
      "initial_value": "short"
    },
    {
      "id": "story_slot_2",
      "label": "Тайна / Давление / Доверие / etc",
      "description": "Что отслеживает это поле в конкретной истории",
      "initial_value": "short"
    }
  ],
  "forbidden_drift": ["string"],
  "current_story_position": "act_1_start"
}
```

`status_slots` обязателен. Ровно два поля под конкретную историю. Они будут показаны в нижнем блоке состояния после базовых полей.

## current_state

```json
{
  "turn_number": 0,
  "date": "Day 1",
  "time": "string",
  "location": "string",
  "player_character_id": "protagonist",
  "active_character_ids": ["protagonist"],
  "nearby_character_ids": [],
  "scene_goal": "string",
  "last_player_input": "",
  "environment": {
    "light": "string",
    "sound": "string",
    "air": "string",
    "details": ["string"]
  },
  "status": {
    "hunger": "норма / голодна / сыта / etc",
    "fatigue": "низкая / средняя / высокая / etc",
    "injuries": [],
    "emotional_state": "short",
    "skills": [],
    "custom": [
      {"id": "story_slot_1", "label": "same as story_plan.status_slots[0].label", "value": "initial short value"},
      {"id": "story_slot_2", "label": "same as story_plan.status_slots[1].label", "value": "initial short value"}
    ]
  }
}
```

## future_locks

Для будущих важных персонажей, которых персонаж игрока ещё не знает:

```json
{
  "hidden_character_seeds": [
    {
      "id": "future_major_character_1",
      "role": "possible major character",
      "known_to_player": false,
      "introduced": false,
      "generate_full_card_on_first_appearance": true,
      "notes_for_engine": "do not reveal yet"
    }
  ],
  "do_not_reveal_yet": ["string"]
}
```

## Стиль

- Живые взрослые персонажи.
- Конфликт не решается сразу.
- NPC не становятся психологами.
- Романтика через действия, напряжение, выборы, детали.
- Игрок управляет персонаж игрока. Не решай за него важные действия.


## Стартовая анкета

Если пользователь дал слишком мало данных и написал только «начнем» / «начнём» / «старт», используй `prompts/start_questionnaire.md`: верни анкету, а не случайную историю.

## Формат будущих сцен

При bootstrap заложи такие данные, чтобы сцены могли показывать:

- верхнюю шапку;
- 3 мысли;
- 3 реплики;
- 3 действия;
- базовые состояния: голод, усталость, травмы, эмоциональное состояние, навыки/ресурс;
- два story-specific status slots;
- отношения только с персонажами текущей сцены.
