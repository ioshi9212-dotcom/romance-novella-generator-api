# Romance Novella Generator API — Starter v1

Первый чистый ZIP под генератор новелл.

## Главная идея

В репозитории **нет готовых персонажей, лора, истории или канона**.

GitHub хранит только:

- FastAPI-движок;
- шаблоны пустых state-файлов;
- схемы;
- промпты;
- правила генерации;
- сборщик контекста;
- валидатор;
- сохранение сессий.

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

## Важно

Один персонаж = одна короткая анкета внутри `characters.json`.

Не используется структура:

```txt
characters/<id>/main.yaml
characters/<id>/character.yaml
characters/<id>/knowledge.yaml
```

Это был формат готовой истории. Здесь — генератор.

## Быстрый запуск локально

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Проверка:

```bash
curl http://localhost:8000/health
```

Создание сессии:

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
    "mode": "local_stub"
  }'
```

`local_stub` создаёт тестовую болванку без LLM, чтобы проверить файловую структуру.

## Режимы

### `local_stub`

Создаёт простую тестовую историю без внешнего ИИ. Нужен только для проверки API и сохранения.

### `manual_gpt`

Создаёт пустую сессию и возвращает `bootstrap_prompt`, который можно вручную вставить в ChatGPT. Потом результат можно отправить в `/api/v1/sessions/{session_id}/bootstrap-result`.

### `llm`

Зарезервировано под подключение реального LLM-клиента. В этом ZIP оставлен интерфейс, но без жёсткой привязки к конкретному провайдеру.

## Основные endpoints

```txt
GET  /health
POST /api/v1/sessions
GET  /api/v1/sessions
GET  /api/v1/sessions/{session_id}
GET  /api/v1/sessions/{session_id}/memory
GET  /api/v1/sessions/{session_id}/scene-contract
POST /api/v1/sessions/{session_id}/bootstrap-result
POST /api/v1/sessions/{session_id}/turn
POST /api/v1/sessions/{session_id}/apply-turn-result
```

## Что сохраняется

- `protagonist.json` — главная героиня/герой.
- `characters.json` — все известные и введённые персонажи с короткими анкетами.
- `relationships.json` — связи и динамика.
- `knowledge.json` — кто что знает / не знает.
- `story_plan.json` — сюжетный компас: жанр, тон, А-Б-В, запреты дрейфа.
- `current_state.json` — текущий кадр сцены.
- `scene_history.json` — история сцен кратко.
- `turns.json` — все ходы игрока и ответы.
- `future_locks.json` — скрытые будущие ограничения и роли.
- `continuity.json` — факты, которые нельзя ломать.

## Принцип поведения

1. На старте сессии генерируется база истории.
2. Всё сгенерированное сохраняется в state.
3. Дальше сцены строятся только по сохранённым state-файлам.
4. Базовая анкета персонажа считается locked.
5. Изменяются не анкеты, а relationships / knowledge / memory / current_state.
