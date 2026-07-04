# Actions Contract — v8

Custom GPT вызывает Railway API как Actions. Railway не пишет художественный текст самостоятельно, кроме debug_stub. Railway хранит state, собирает scene_contract, валидирует JSON и применяет патчи.

## Auth

Если в Railway задан `API_KEY`, GPT Action должен отправлять header:

```txt
X-API-Key: <secret>
```

`/health` открыт без ключа.

## Required flow

### 1. Create session

```txt
POST /api/v1/sessions
```

Если ответ:

```json
{"status":"needs_questionnaire"}
```

показать пользователю `questionnaire` и не создавать историю.

Если ответ:

```json
{"status":"bootstrap_pending"}
```

GPT должен сгенерировать bootstrap JSON из `bootstrap_prompt`.

### 2. Apply bootstrap

```txt
POST /api/v1/sessions/{session_id}/bootstrap-result
```

После успеха session becomes `active`.

### 3. Turn

```txt
POST /api/v1/sessions/{session_id}/turn
```

Возвращает `scene_prompt`. GPT пишет `scene_response` JSON.

### 4. Apply turn result

```txt
POST /api/v1/sessions/{session_id}/apply-turn-result
```

Railway валидирует и сохраняет state. Пользователю показывается только `scene.rendered_text`.

## Gates

`scene-contract`, `turn`, `apply-turn-result` работают только если session status = `active`.

## Validation rules

Bootstrap and scene responses are validated by JSON Schema plus semantic validators:

- names must be Latin script and non-Russian;
- knowledge patches require `reason` and `source_in_scene`;
- relationship patches require `pair_id`, `change_type`, `entry`, `reason`, `source_in_scene`;
- locked character cards cannot change immutable fields.

## Visible scene header

No `POV`, no `Фокус`, no `В сцене`, no active_character_ids.

## Naming

All generated character `name` values must use Latin script and non-Russian naming style.
