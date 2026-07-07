# romance-novella-generator-api — v8 response-size/chunking fix

## Причина фикса

`processTurn` мог падать с `ResponseTooLargeError`, потому что runtime-пакет раздувался:
- `scene_history.json` хранил полный `visible_scene_text`;
- `turns.json` хранил полный `scene_response`;
- старые сцены и turn payload могли снова попадать в сборщик контекста;
- большой `scene_prompt` возвращался одним ответом Action.

## Что меняет v8

### 1. Компактная runtime-память
Теперь после каждого applyTurnResult:
- в `scene_history.json` сохраняется короткая запись: turn, summary, facts, witnesses, body_excerpt;
- в `turns.json` сохраняется короткая запись без полного scene_response;
- старые записи уходят в `continuity.memory_chunks`.

### 2. 10/15 шагов
- Каждый 10-й ход выставляет `state_recovery_audit_due`.
- Каждый 15-й ход выставляет `state_compaction_cleanup_due`.
- Старые сцены/ходы сжимаются в `memory_chunks`, а не тащатся целиком.

### 3. Чанки scene_prompt
`processTurn` теперь безопасно возвращает первый chunk.
Если prompt большой:
- response содержит `prompt_chunk_count > 1`;
- надо вызвать `getTurnPromptChunk` для остальных индексов;
- потом склеить chunks по порядку и только после этого генерировать scene_response.

### 4. Защита от старых сохранений
Даже если в старой сессии уже есть огромные `visible_scene_text` или полные `scene_response`, `read_session_bundle` не отдаёт их в Action context.

## Файлы на замену

```txt
app/main.py
app/models.py
app/novella_openapi_actions.py
app/storage.py
app/state_updater.py
app/scene_contract_builder.py
app/turn_processor.py
gpt/custom_gpt_instructions.md
openapi.yaml
tests/test_smoke.py
PATCH_README.md
DELETE_LIST.txt
```

## Важная правка инструкции Custom GPT

Добавь в текущую инструкцию:

```txt
Если processTurn вернул prompt_chunk_count > 1 или has_more_prompt_chunks=true:
1. не пиши сцену сразу;
2. вызови getTurnPromptChunk для chunk_index=1, затем 2 и дальше, пока has_more=false;
3. склей scene_prompt + все scene_prompt_chunk строго по порядку;
4. только после этого создай scene_response и вызови applyTurnResult.
Не проси пользователя сократить ход из-за ResponseTooLargeError.
```

## Проверка

```bash
python -m pytest -q
```

Ожидаемо:

```txt
11 passed
```
