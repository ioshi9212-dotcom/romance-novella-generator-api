# romance-novella-generator-api — hotfix v3

Пакет предназначен для распаковки **поверх текущего репозитория** с заменой файлов.

## Постоянное правило для будущих правок

Не плодить новые runtime patch / locks / rules / hotfix-модули без крайней необходимости.

Перед любой новой правкой:
1. Сначала чинить существующие файлы (`main.py`, `models.py`, `scene_response_normalizer.py`, `validators.py`, `novella_openapi_actions.py`, тесты).
2. Не добавлять новый слой `*_runtime_patch.py`, `*_rules.py`, `*_locks.py`, если проблему можно решить в текущем v9 flow.
3. Не делать “зоопарк” параллельных контрактов.
4. Один источник Actions-схемы: `/openapi-actions.json`.
5. Ручной `openapi.yaml` — только fallback/static copy, не главный источник.
6. Любой фикс обязан иметь тест на реальный payload из лога, а не только на идеальный JSON.

## Что чинит v3

В реальном логе `applyTurnResult` падал с 422:

- `scene.body must be a real scene body, at least 500 characters`
- `safety_checks.* must be true`

При этом полная художественная сцена была внутри `rendered_text`, но `scene.body` был коротким пересказом, а `safety_checks` отсутствовали.

v3 исправляет это без добавления новых runtime-слоёв:

1. `scene_response_normalizer.py`
   - если `scene.body` короткий, но `rendered_text` полный, body извлекается из `rendered_text`;
   - top-level `rendered_text` переносится в `scene.rendered_text`;
   - missing `safety_checks` автозаполняются только после восстановления полной сцены;
   - `status_panel.custom` строками вида `Лейбл: значение` переводится в нормальные object-слоты.

2. `models.py`
   - `ApplyTurnResultRequest` стал совместимее с грязными Action payload;
   - top-level `rendered_text`, `proposed_updates`, `safety_checks`, `metadata`, `diagnostics` больше не режутся моделью.

3. `main.py`
   - top-level compatibility fields перекладываются внутрь `scene_response` до нормализации;
   - сохранён fallback для `turn_id`.

4. `novella_openapi_actions.py`
   - `ApplyTurnResultRequest` теперь явно описывает `SceneResponse`;
   - top-level compatibility fields разрешены;
   - `additionalProperties=true` для `ApplyTurnResultRequest`, чтобы Action не падал на попытке GPT исправить payload.

5. `tests/test_smoke.py`
   - добавлен тест на грязный реальный формат:
     - полный `rendered_text`;
     - короткий `scene.body`;
     - отсутствуют `safety_checks`;
     - отсутствует `proposed_updates`.

## Файлы на замену

```txt
app/main.py
app/models.py
app/scene_response_normalizer.py
app/novella_openapi_actions.py
tests/test_smoke.py
openapi.yaml
PATCH_README.md
```

## Файлы на удаление

```txt
Ничего удалять не нужно.
```

## Проверка после распаковки

```bash
pytest -q
```

Ожидаемо:

```txt
6 passed
```

## Что подключать в Custom GPT Actions

Основной URL:

```txt
https://<твоя-railway-ссылка>/openapi-actions.json
```

После деплоя проверь:

```txt
GET /health
GET /openapi-actions.json
```

В `/openapi-actions.json` у `applyTurnResult` должны быть:

```txt
turn_id
scene_response
rendered_text
proposed_updates
safety_checks
metadata
```

## Важно для старых сессий

Если сессия уже застряла после `processTurn`, лучше начать новую тестовую сессию после деплоя. Старый pending turn может быть в промежуточном состоянии.
