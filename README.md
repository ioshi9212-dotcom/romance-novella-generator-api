# Romance Novella Generator API — GPT Actions v9

Генератор интерактивных новелл для связки:

```txt
Custom GPT = писатель и сборщик bootstrap-preview
Railway API = память, state, проверки, preview gate, сборка контекста
GitHub = код, правила, схемы, промпты, шаблоны
```

В репозитории нет готового канона, персонажей, лора или истории. Всё конкретное создаётся при старте новой сессии и сохраняется в Railway volume только после подтверждения пользователем.

## Что изменилось в v9

- Добавлен обязательный launch-flow с preview перед первой сценой.
- `createBootstrapPreview` валидирует и сохраняет `pending_bootstrap.json`, но не активирует игру.
- `confirmBootstrapPreview` после явного подтверждения пользователя раскладывает персонажей/знания/отношения по state-файлам и активирует сессию.
- Первая сцена пишется только после подтверждения preview.
- `story_plan.json` усилен: цель новеллы, цель героини, центральный конфликт, центральный вопрос, opening intent, character_arcs, relationship_focus, open_threads.
- Сохранена архитектура v8: персонажи и их state создаются динамически внутри каждой сессии по generated `character_id`.

## Railway variables

```env
DATA_DIR=/app/runtime
ENGINE_VERSION=novella-generator-gpt-actions-v9
DEFAULT_LANGUAGE=ru
API_KEY=your-long-random-secret
```

`DATA_DIR` должен указывать на Railway Volume mount path. Если volume примонтирован в `/app/runtime`, оставляй `DATA_DIR=/app/runtime`.

Если `API_KEY` задан, все endpoints кроме `/health` требуют header:

```txt
X-API-Key: your-long-random-secret
```

## Launch flow

```txt
User: начнем
↓
GPT calls GET /api/v1/start-questionnaire
↓
User answers questionnaire in one message
↓
GPT calls POST /api/v1/sessions
↓
API returns bootstrap_prompt, session remains bootstrap_pending
↓
GPT creates bootstrap JSON but DOES NOT save active state
↓
GPT calls POST /api/v1/sessions/{session_id}/bootstrap-preview
↓
API validates JSON and returns human-readable preview
↓
User confirms or asks edits
↓
If edits: GPT creates revised bootstrap JSON and calls bootstrap-preview again
↓
If confirmed: GPT calls POST /api/v1/sessions/{session_id}/bootstrap-confirm
↓
API writes state files and session becomes active
↓
GPT calls POST /api/v1/sessions/{session_id}/turn with player_input="(начать первую сцену)"
↓
GPT writes scene_response, calls apply-turn-result, shows scene.rendered_text
```

## Session state layout

```txt
DATA_DIR/
  sessions/
    <session_id>/
      session.json
      user_request.json
      protagonist.json
      story_plan.json
      current_state.json
      npc_state.json
      future_locks.json
      continuity.json
      scene_history.json
      turns.json
      characters_index.json
      characters/
        <character_id>.json
      state/
        knowledge_index.json
        relationship_index.json
        knowledge/
          <character_id>.json
        relationship_pairs/
          <a>__<b>.json
```

Один персонаж = одна короткая карточка в `characters/<character_id>.json`.

Знания = субъективная память конкретного персонажа в `state/knowledge/<character_id>.json`: что видел, слышал, как понял, что запомнил, где может ошибаться.

Отношения = парный файл `state/relationship_pairs/<a>__<b>.json` с общими scores и направленными взглядами `a_view_of_b` / `b_view_of_a`.

## Visible scene format

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

## Main endpoints

```txt
GET  /health
GET  /api/v1/start-questionnaire
POST /api/v1/sessions
GET  /api/v1/sessions
GET  /api/v1/sessions/latest
GET  /api/v1/sessions/{session_id}
GET  /api/v1/sessions/{session_id}/memory
POST /api/v1/sessions/{session_id}/bootstrap-preview
POST /api/v1/sessions/{session_id}/bootstrap-confirm
POST /api/v1/sessions/{session_id}/bootstrap-result   # legacy/direct save, не основной GPT-flow
GET  /api/v1/sessions/{session_id}/scene-contract
POST /api/v1/sessions/{session_id}/turn
POST /api/v1/sessions/{session_id}/apply-turn-result
```

## Local run

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```
