# Novella Generator Runtime

Railway-runtime для интерактивной визуальной новеллы в Custom GPT.

Custom GPT пишет сцены. Railway ничего не генерирует и не вызывает OpenAI API: он
хранит изолированное состояние каждой новеллы, выдаёт обязательный пакет перед
сценой и атомарно сохраняет результат хода.

## Зафиксированный контракт

- API-ключ и OpenAI API не используются.
- В GPT Actions выбирается `Authentication: None`; в `openapi.yaml` стоит
  `security: []`.
- До явного «подтверждаю» Railway не вызывается; `createSession` дополнительно
  отклоняет запрос без положительного сообщения игрока в `player_confirmation`.
- `session_id` создаёт Railway после подтверждения; этот ID обязателен во всех
  последующих Actions.
- Нет `latestSession`, общей активной сессии и списка чужих сессий.
- Перед каждой сценой GPT получает актуальные rules, builder, state, хронологию,
  полные ходы текущего цикла и полные досье только POV и текущих участников.
- Commit физически заблокирован, пока Railway не выдал по порядку все chunks пакета.
  Для известного отсутствующего персонажа, который входит в новую сцену, отдельно
  выдаётся только его полное досье; его chunks также обязательны.
- Заданные игроком и важные персонажи проходят структурную проверку полной карточки;
  повышение NPC сохраняет прежний ID и установленные факты.
- Значимые локации хранят постоянный визуальный canon отдельно от временных
  изменений, а автономные планы персонажей — в отдельном director_plan.
- После каждого 15-го хода следующая сцена блокируется до полной сверки последних
  15 ходов.
- Один commit сохраняет сцену, хронологию и все изменения state одной транзакцией.
- Каждый ход обязан сохранить хотя бы один компактный факт и полный scene_state
  финального кадра; номер хода, scene_id, время и присутствие POV проверяет сервер.
- Переписывание последней сцены создаёт новую редакцию того же хода. Если ход уже
  проверен, соответствующий audit аннулируется и должен быть проведён снова.

## Главные файлы режиссуры

- [`rules/rules.md`](rules/rules.md) — короткая модель поведения персонажей,
  границы знаний, постоянство карточных персонажей и жизнь NPC.
- [`rules/scene_builder.md`](rules/scene_builder.md) — единственный builder внешнего
  вида сцены, верхнего/нижнего блока, вариантов и footer.
- [`gpt/custom_gpt_instructions.md`](gpt/custom_gpt_instructions.md) — короткий
  runtime-порядок Actions для редактора Custom GPT.

Правила поведения и формат сцены не размножаются по отдельным prompt-файлам.

## Игровой цикл

```text
«начнём»
  → вопросы и одно превью без Railway
  → «подтверждаю»
  → createSession
  → getTurnPacket (+ все chunks)
  → при входе известного персонажа: getSceneCharacterBundle (+ все chunks)
  → GPT собирает сцену
  → commitTurn
  → игрок видит только сцену
```

После 15-го сохранённого хода:

```text
getTurnPacket → AUDIT_REQUIRED
  → getAuditPacket (+ все chunks)
  → сверка 15 полных ходов, state и всей компактной хронологии
  → commitAudit
  → audit_complete: true
  → getTurnPacket
  → следующая сцена
```

Backend не полагается на обещание в prompt: `getTurnPacket` физически возвращает
ошибку, пока audit-шлюз не закрыт, а оба commit отклоняются, пока сервер не выдал
все chunks соответствующего пакета.

## Счётчики в сцене

Внизу каждого игрового ответа builder требует:

```text
Ход 56 · цикл 1/15
↻ Перед следующим ходом: прочитать актуальный state. На 15/15 — сверить последние
15 ходов с Railway, дописать пропущенное, удалить устаревшее и сжать завершённое;
только после успешной сверки писать следующую сцену.
```

Общий номер и позиция цикла хранятся отдельно. Runtime передаёт оба значения в turn
packet и отклоняет commit с неправильным footer.

## Actions

| operationId | Назначение |
|---|---|
| `createSession` | Создать сессию только после подтверждения превью |
| `getTurnPacket` | Получить обязательный state-пакет перед сценой |
| `getTurnPacketChunk` | Дочитать большой turn packet по порядку |
| `getSceneCharacterBundle` | Получить досье одного известного персонажа, который входит в сцену |
| `getSceneCharacterBundleChunk` | Дочитать досье входящего персонажа по порядку |
| `commitTurn` | Атомарно сохранить сцену и все изменения хода |
| `getAuditPacket` | Получить 15 полных ходов и state для обязательной сверки |
| `getAuditPacketChunk` | Дочитать большой audit packet по порядку |
| `commitAudit` | Сохранить исправления/сжатие и снять audit-шлюз |
| `getChronologyPage` | Прочитать хронологию с начала до конца страницами |

Схема для импорта в GPT Actions: [`openapi.yaml`](openapi.yaml).

## Хранение на Railway

Живые данные находятся только в volume:

```text
/data/sessions/{session_id}/
├── session.json
├── manifest.json
├── state/
│   ├── novel.json
│   ├── hidden_lore.json
│   ├── plot_state.json
│   ├── director_plan.json
│   ├── world_state.json
│   └── scene_state.json
├── characters/{character_id}/
│   ├── card.json
│   ├── current_state.json
│   ├── relationships.json
│   └── knowledge.json
├── chronology/
│   ├── manifest.json
│   └── chronology_0001.json
├── turns/turn_000001.json
├── audits/{audit_id}.json
├── locations/{location_id}.json
└── objects/{object_id}.json
```

Хронология хранит компактные факты, а не копию сцены. Полный ввод игрока и полный
игровой ответ остаются в файле хода. Шаблоны всех документов находятся в
[`state_templates/`](state_templates/).

Во время audit повторяющиеся записи можно заменить одной активной компактной
сводкой. Исходные события не удаляются с диска: обычные packets их больше не тянут,
а диагностический `getChronologyPage?include_inactive=true` по-прежнему их видит.
Если audit аннулирован исправлением хода, его сводка становится неактивной и исходные
события автоматически возвращаются в рабочую хронологию.

Каждый документ привязан к `session_id`. Идентификаторы и пути проверяются; кэш и
транзакционные блокировки также сессионные. Незавершённая файловая транзакция при
следующем обращении откатывается целиком.

## Локальный запуск

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
DATA_DIR=./data .venv/bin/uvicorn app.main:app --reload
```

Проверки:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python scripts/export_openapi.py
```

## Railway

1. Подключить этот репозиторий к Railway.
2. Подключить persistent volume к `/data`.
3. Задать `DATA_DIR=/data`.
4. Оставить один worker: файловые транзакции рассчитаны на один Railway service.
5. Проверить `GET /health`.

`railway.json` и `Procfile` уже содержат команду запуска. Текущий production server
в Action-схеме: `https://web-production-4310e.up.railway.app`. Если Railway выдаст
другой домен, изменить `PUBLIC_BASE_URL` и заново выполнить export.

## Подключение Custom GPT

1. Вставить содержимое `gpt/custom_gpt_instructions.md` в Instructions.
2. В Actions импортировать `openapi.yaml`.
3. Выбрать `Authentication: None`.
4. Убедиться, что среди доступных Actions появились `getSceneCharacterBundle` и
   `getSceneCharacterBundleChunk`, затем нажать Test у каждой новой операции.
5. Не добавлять API key и не включать методы списка/последней сессии.
6. Начать новый чат словом «начнём», проверить превью и только затем написать
   «подтверждаю».

Endpoint публичный, поэтому `session_id` генерируется как длинное случайное значение
и фактически является единственным способом адресовать конкретную историю. Его нельзя
показывать другим пользователям или подменять ID из другого чата.
