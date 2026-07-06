# romance-novella-generator-api — fixed files pack

Пакет исправляет основные технические проблемы v9 flow:

1. Добавляет динамический `/openapi-actions.json` для Custom GPT Actions.
2. Перестаёт полагаться на ручной почти пустой `openapi.yaml`.
3. Добавляет защиту от пустого `player_input`.
4. Добавляет `turn_id` / pending-turn защиту между `processTurn` и `applyTurnResult`.
5. Ужесточает `scene_response` validation:
   - пустые/короткие сцены не сохраняются;
   - safety_checks больше нельзя молча автозаполнить `true`;
   - `POV`, `Фокус`, `В сцене` не должны попадать в шапку.
6. Убирает опасную автоподстановку knowledge patch к героине при неоднозначности.
7. Обновляет smoke tests под v9 preview-confirm flow.

## Как применить

Распаковать ZIP в корень репозитория `ioshi9212-dotcom/romance-novella-generator-api` с заменой файлов.

Внутри ZIP пути уже совпадают с путями репы:

```txt
app/main.py
app/models.py
app/validators.py
app/scene_response_normalizer.py
app/novella_openapi_actions.py
tests/test_smoke.py
openapi.yaml
```

## Что подключать в Custom GPT Actions

Лучше использовать не статический `openapi.yaml`, а URL:

```txt
https://<твоя-railway-ссылка>/openapi-actions.json
```

Если Railway env содержит `PUBLIC_BASE_URL` или `RAILWAY_PUBLIC_DOMAIN`, схема сама подставит правильный server URL.

## Важно

После деплоя проверь:

```txt
GET /health
GET /openapi-actions.json
GET /api/v1/start-questionnaire
```

Потом нормальный flow:

```txt
getStartQuestionnaire
createSession
createBootstrapPreview
confirmBootstrapPreview
processTurn
applyTurnResult
```

`applyTurnResult` теперь ждёт `turn_id`, который вернул `processTurn`.
