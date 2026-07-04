# Romance Novella Generator API — GPT Actions v8

Генератор интерактивных новелл для связки:

```txt
Custom GPT = писатель сцены
Railway API = память, state, проверки, сборка контекста
GitHub = код, правила, схемы, промпты, шаблоны
```

В репозитории нет готового канона, готовых персонажей, готового лора или готовой истории. Всё конкретное создаётся при старте новой сессии и сохраняется в Railway volume.

## Что изменилось в v8

- Убраны готовые имена/персонажи из примеров и debug-данных.
- Каждый персонаж создаётся внутри конкретной сессии и получает свой `character_id`.
- Карточка персонажа хранится как `characters/<character_id>.json`.
- Знания хранятся как `state/knowledge/<character_id>.json`.
- Отношения хранятся как `state/relationship_pairs/<a>__<b>.json`.
- Knowledge теперь субъективный: saw/heard/remembered_quote/interpreted_as/assumptions/wrong_beliefs.
- Relationship pair хранит направленные взгляды: `a_view_of_b` и `b_view_of_a`.
- Builder грузит только нужные карточки, знания и пары в scene_contract.
- Updater сохраняет только затронутые файлы знаний/отношений/персонажей.

## Railway variables

```env
DATA_DIR=/app/runtime
ENGINE_VERSION=novella-generator-gpt-actions-v8
DEFAULT_LANGUAGE=ru
API_KEY=your-long-random-secret
```

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
      story_plan.json
      current_state.json
      npc_state.json
      future_locks.json
      continuity.json
      scene_history.json
      turns.json
```

Один персонаж = одна короткая анкета. Никаких `main.yaml / character.yaml / knowledge.yaml / past.yaml`.

## Dynamic IDs

Нельзя заранее создавать файлы персонажей, потому что генератор не знает персонажей до bootstrap. GPT создаёт персонажей, выдаёт им id, и уже по этим id Railway создаёт файлы.

Пример формата id:

```txt
pc_01
friend_01
family_01
npc_<shortid>
love_interest_01
```

Это не готовые персонажи, а только формат id.

## Knowledge

Знание — не объективная истина, а память конкретного персонажа.

Файл:

```txt
state/knowledge/<character_id>.json
```

Хранит:

```txt
known_facts
observations: saw / heard / remembered_quote / interpreted_as / emotional_marker
assumptions
wrong_beliefs
does_not_know
must_not_assume
recent_memories
open_questions
```

## Relationships

Отношения — парный файл:

```txt
state/relationship_pairs/<a>__<b>.json
```

Хранит:

```txt
scores: trust/tension/attachment/respect/fear/curiosity
a_view_of_b
b_view_of_a
shared_history
recent_changes
open_threads
```

В нижнем блоке сцены показываются только пары, где оба персонажа в сцене или прямо затронуты текущим ходом.

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

В шапке нельзя: `POV`, `Фокус`, `В сцене`, active ids, скрытые отношения, будущие роли.

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

## Startup flow

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
