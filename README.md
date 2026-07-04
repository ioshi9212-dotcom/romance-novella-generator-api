# Romance Novella Generator API — GPT Actions v6

Генератор интерактивных новелл для связки:

```txt
Custom GPT = писатель сцены
Railway API = память, state, проверки, сборка контекста
GitHub = код, правила, схемы, промпты, шаблоны
```

В репозитории нет готового канона, персонажей, лора или истории. Всё конкретное создаётся при старте новой сессии и сохраняется в Railway volume.

## Что изменилось в v6

- Добавлены усиленные правила сцены и NPC.
- Добавлены жёсткие naming rules: имена и фамилии не русские, не славянские, только латиницей.
- Предпочтительный стиль имён: западный / японский / англо-японский / японо-западный.
- Добавлена optional API key protection через `API_KEY` и header `X-API-Key`.
- Добавлен endpoint `GET /api/v1/sessions/latest`.
- Добавлены session gates: scene-contract, turn и apply-turn-result работают только для `active` session.
- Усилена валидация knowledge/relationship patches: нужен `reason` и `source_in_scene`.
- Усилен locked-character guard: locked анкеты нельзя менять через обычный scene patch.
- Обновлён `openapi.yaml` под Custom GPT Actions.

## Railway variables

Минимум:

```env
DATA_DIR=/app/runtime
ENGINE_VERSION=novella-generator-gpt-actions-v6
DEFAULT_LANGUAGE=ru
API_KEY=your-long-random-secret
```

`DATA_DIR` должен указывать на Railway Volume mount path. Если volume примонтирован в `/app/runtime`, оставляй `DATA_DIR=/app/runtime`.

Если `API_KEY` задан, все endpoints кроме `/health` требуют header:

```txt
X-API-Key: your-long-random-secret
```

## Session state layout

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

Один персонаж = одна короткая анкета внутри `characters.json`.

Не используется структура готового канона:

```txt
characters/<id>/main.yaml
characters/<id>/character.yaml
characters/<id>/knowledge.yaml
characters/<id>/past.yaml
```

## Visible scene format

Шапка как в академическом формате, но универсальная и без `POV`, `Фокус`, `В сцене`:

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

Диалог:

```md
**Name** — Реплика. *(короткая ремарка)* Продолжение реплики.
```

Низ сцены:

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

## Naming rules

По умолчанию запрещены русские имена и фамилии. Все `name` — латиницей.

Хорошо:

```txt
Akira Vale
Raiden Sterling
Haru Foster
Livia Hart
Mika Lawson
Noah Akiyama
Yuna Cross
Ren Carter
Elias Kurogane
```

Плохо:

```txt
Марина Мор
Данил Кросс
Иван Петров
Анастасия Волкова
Сергей Морозов
```

## Player input rules

```txt
Я не вернулась. (посмотреть на дверь) Просто забрала вещи.
```

Это значит:

1. персонаж игрока говорит первую фразу;
2. потом смотрит на дверь;
3. потом говорит вторую фразу.

Текст в скобках не произносится вслух, если там нет явной прямой речи в кавычках. NPC не читают мысли в скобках.

## Main endpoints

```txt
GET  /health
GET  /api/v1/start-questionnaire
POST /api/v1/sessions
GET  /api/v1/sessions
GET  /api/v1/sessions/latest
GET  /api/v1/sessions/{session_id}
GET  /api/v1/sessions/{session_id}/memory
POST /api/v1/sessions/{session_id}/bootstrap-result
GET  /api/v1/sessions/{session_id}/scene-contract
POST /api/v1/sessions/{session_id}/turn
POST /api/v1/sessions/{session_id}/apply-turn-result
```

## Startup flow for Custom GPT

```txt
User gives setup / says начнем
↓
GPT calls POST /api/v1/sessions
↓
If status = needs_questionnaire, show questionnaire
↓
If status = bootstrap_pending, GPT generates bootstrap JSON from bootstrap_prompt
↓
GPT calls POST /bootstrap-result
↓
Session becomes active
↓
For each player turn:
  POST /turn → get scene_prompt
  GPT writes scene_response JSON
  POST /apply-turn-result → save state
  show final scene text to user
```

## Local run

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Health:

```bash
curl http://localhost:8000/health
```

Debug session:

```bash
curl -X POST http://localhost:8000/api/v1/sessions \
  -H "Content-Type: application/json" \
  -d '{"genre":"debug","setting_request":"debug","protagonist_request":"debug","mode":"debug_stub"}'
```

## Tests

```bash
pytest -q
```
