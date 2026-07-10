# v9 footer-state-debug patch

## Что чинит

1. `debugSessionDump`
- Новый Action: `GET /api/v1/sessions/{session_id}/debug-dump`
- operationId: `debugSessionDump`
- Позволяет смотреть current_state, story_plan, characters, knowledge, relationships, history, memory_chunks и pending_turn без нового игрового хода.

2. Нижняя панель / footer
- `actions` больше не должны содержать речевые действия: попросить/сказать/спросить/передать/предупредить переносятся в dialogue.
- Убирается двойное тире `— —` в вариантах реплик.
- `status_panel` теперь state-backed: берёт значения из current_state.status и story_plan.status_slots, а не доверяет случайным footer-числам GPT.
- `Поле истории 1/2` заменяется на реальные labels из story_plan.status_slots или нормальные fallback labels.
- Травмы учитывают боль/штамп/руку/жжение.
- relationships_panel теперь строится от relationship state, а не от случайного пересказа события вроде “избавилась от пакета”.

3. Relationship scores
- Значения отношений не прыгают резко: обычный ход максимум +/-8, major_shift максимум +/-15.
- Добавлена поддержка scores.overall / romantic_interest / presence_pull.

4. State status merge
- `scene_state_patch.status` теперь merge, а не replace всего status.

## Файлы на замену

```txt
app/main.py
app/models.py
app/novella_openapi_actions.py
app/scene_response_normalizer.py
app/state_updater.py
app/turn_processor.py
gpt/custom_gpt_instructions.md
openapi.yaml
tests/test_smoke.py
PATCH_README.md
DELETE_LIST.txt
```

## Проверка

```bash
python -m pytest -q
```

Ожидаемо:

```txt
14 passed
```

## После деплоя

1. В Custom GPT Actions переимпортировать актуальную OpenAPI schema.
2. Проверить, что доступны:
   - `getTurnPromptChunk`
   - `debugSessionDump`
3. Для диагностики писать технический запрос с `debugSessionDump`, не через processTurn.
