# Romance Novella Generator API — GPT Actions Starter v5

Стартовая болванка под генератор интерактивных новелл, где **Custom GPT пишет сцену**, а **Railway API хранит память, собирает контекст и сохраняет state**.

## Архитектура

```text
Custom GPT / ChatGPT Actions = писатель сцены и генератор JSON
Railway API = state, context builder, validation, save/apply
GitHub = код, правила, схемы, промпты, шаблоны
```

В репозитории **нет готовых персонажей, готового лора, готовой истории или канона**.

GitHub хранит только:

- FastAPI-движок;
- OpenAPI-схему для GPT Actions;
- инструкции для Custom GPT;
- prompt builder;
- схемы JSON;
- правила сцены, NPC, знаний, отношений и agency;
- шаблоны пустых state-файлов;
- сохранение и применение patches.

Вся конкретная история создаётся при старте новой сессии и хранится в Railway volume:

```txt
DATA_DIR/
  sessions/
    <session_id>/
      session.json
      user_request.json
      protagonist.json
      characters.json
      relationships.json
      knowledge.json
      story_plan.json
      current_state.json
      npc_state.json
      future_locks.json
      continuity.json
      scene_history.json
      turns.json
```

## Главное правило персонажей

Один персонаж = одна короткая анкета внутри `characters.json`.

Не используется структура готового канона:

```txt
characters/<id>/main.yaml
characters/<id>/character.yaml
characters/<id>/knowledge.yaml
characters/<id>/past.yaml
```

Это был формат готовых историй. Здесь — генератор.

## Режимы

### `gpt_actions`

Основной режим.

Railway не вызывает LLM сам. Custom GPT вызывает Railway как Action:

```text
player input
↓
Railway builds scene_prompt / scene_contract
↓
GPT writes scene_response JSON
↓
Railway validates and saves proposed_updates
↓
GPT shows scene.rendered_text to user
```

### `debug_stub`

Технический режим без творческой модели. Нужен только для проверки API, файлов, scene_contract и сохранения.

Внутри debug_stub нет канона — только нейтральные placeholder-данные.

## Что изменилось в v5

- Убран внутренний `llm`-режим.
- `manual_gpt` переименован в `gpt_actions`.
- `local_stub` переименован в `debug_stub`.
- Добавлен `openapi.yaml` для подключения GPT Actions.
- Добавлены `gpt/custom_gpt_instructions.md` и `api_contracts/actions_contract.md`.
- README очищен от старого v2-формата шапки.
- Версия обновлена до `novella-generator-gpt-actions-v5`.
- `StateUpdater` теперь сохраняет `weather`, `scene_state`, `outfit`, `inventory`, `nearby_items`.
- `validators.py` теперь использует `jsonschema` для проверки schema-файлов.
- Добавлена авто-логика: если данных мало, API возвращает `needs_questionnaire`.
- Добавлены тесты на создание сессии, questionnaire, turn, state patch.

## Видимая шапка сцены

Сцена начинается строго так:

```md
🎭 <Название истории> · <дата / день>
🕒 <время> · 📍 <локация>
🌦️ Погода: <погода / атмосфера>
⚙️ Состояние сцены: <физический контекст>

✦ <имя персонажа игрока> · <видимое состояние>
🧥 <одежда>
◈ <инвентарь / предметы при себе / рядом>

━━━━━━━━━━━━━━━━━━━━
```

В шапке нельзя показывать:

- `POV`;
- `Фокус`;
- `В сцене`;
- active character list;
- technical ids;
- скрытые отношения;
- будущие роли;
- авторские подсказки.

## Формат диалогов

```md
**Имя или видимый дескриптор** — Реплика. *(короткая ремарка)* Продолжение реплики.
```

Короткое отдельное действие:

```md
*Дверь закрывается слишком тихо.*
```

## Ввод игрока

```txt
Я не вернулась. (посмотреть на дверь) Просто забрала вещи.
```

Означает:

1. персонаж игрока говорит первую фразу;
2. потом смотрит на дверь;
3. потом говорит вторую фразу.

Порядок нельзя переставлять.

Текст в скобках не произносится вслух, если там нет явной прямой речи. NPC не читают мысли и скрытые мотивы.

## Нижний блок сцены

В конце всегда:

```md
━━━━━━━━━━━━━━━━━━━━

✦ Что можно сделать
◈ ...
◈ ...
◈ ...

✦ Что можно сказать
— ...
— ...
— ...

✦ Мысли
— ...
— ...
— ...

✦ Состояние
Голод: ...
Усталость: ...
Травмы: ...
Эмоциональное состояние: ...
Навыки / ресурс: ...
<story slot 1>: ...
<story slot 2>: ...

✦ Отношения
<только персонажи текущей сцены или прямо затронутые текущим ходом>

━━━━━━━━━━━━━━━━━━━━
```

## Стартовая анкета

Если пользователь написал только «начнем» или дал слишком мало данных, API вернёт `needs_questionnaire` или можно вызвать:

```txt
GET /api/v1/start-questionnaire
```

Анкета лежит в:

```txt
prompts/start_questionnaire.md
```

## Быстрый запуск локально

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Проверка:

```bash
curl http://localhost:8000/health
```

## Создание debug-сессии

```bash
curl -X POST http://localhost:8000/api/v1/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "genre": "debug",
    "setting_request": "debug",
    "protagonist_request": "debug",
    "mode": "debug_stub"
  }'
```

## Создание GPT Actions-сессии

```bash
curl -X POST http://localhost:8000/api/v1/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "genre": "modern slow-burn romance",
    "language": "ru",
    "tone": "grounded, tense, emotional",
    "setting_request": "маленький город у моря, бывшие, без магии",
    "protagonist_request": "взрослая героиня, сдержанная, вернулась домой",
    "avoid": ["магия", "война", "слишком сладкий тон"],
    "mode": "gpt_actions"
  }'
```

Ответ вернёт `bootstrap_prompt`. Custom GPT должен сгенерировать bootstrap JSON и отправить его в:

```txt
POST /api/v1/sessions/{session_id}/bootstrap-result
```

## Обычный ход

```text
POST /api/v1/sessions/{session_id}/turn
```

Тело:

```json
{
  "player_input": "(посмотреть на дверь и прислушаться)",
  "mode": "gpt_actions"
}
```

Railway вернёт `scene_prompt`. GPT пишет `scene_response`, затем вызывает:

```text
POST /api/v1/sessions/{session_id}/apply-turn-result
```

Пользователю показывается только `scene.rendered_text`.

## Основные endpoints

```txt
GET  /health
GET  /api/v1/start-questionnaire
POST /api/v1/sessions
GET  /api/v1/sessions
GET  /api/v1/sessions/{session_id}
GET  /api/v1/sessions/{session_id}/memory
GET  /api/v1/sessions/{session_id}/scene-contract
POST /api/v1/sessions/{session_id}/bootstrap-result
POST /api/v1/sessions/{session_id}/turn
POST /api/v1/sessions/{session_id}/apply-turn-result
```

## Файлы для Custom GPT

```text
openapi.yaml
gpt/custom_gpt_instructions.md
api_contracts/actions_contract.md
```

## Тесты

```bash
pytest
```

Проверяются:

- `/health`;
- `needs_questionnaire` при пустом старте;
- создание `debug_stub` сессии;
- сборка `scene_contract`;
- debug turn;
- сохранение `weather/outfit/inventory` через `apply-turn-result`.
