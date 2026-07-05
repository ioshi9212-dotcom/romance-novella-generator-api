# Novella Generator v9 cumulative patch

Этот ZIP собран под фактическое состояние текущей репы `ioshi9212-dotcom/romance-novella-generator-api` после проверки.

## Что заменить

Скопируй файлы из ZIP поверх файлов в корне репы:

- app/bootstrap_normalizer.py
- app/main.py
- app/models.py
- app/scene_contract_builder.py
- app/scene_response_normalizer.py
- app/session_manager.py
- app/turn_processor.py
- app/validators.py
- openapi.yaml

## Что исправляет

- createBootstrapPreview возвращает `message_to_user` первым полем; GPT должен показать именно его.
- bootstrap нормализует кривые поля: appearance string, status_slots strings, character_arcs list, relationship_focus string, from/to relationships.
- Кириллица в видимых именах сохраняется как `display_name`, техническое `name` транслитерируется в латиницу.
- processTurn больше не должен показывать JSON пользователю: prompt требует вызвать applyTurnResult и затем показать только `scene.rendered_text`.
- applyTurnResult нормализует кривой scene_response перед валидацией: inventory list, relationships_panel name/status, knowledge_patches who/add/source.
- /memory, /scene-contract, /bootstrap-result скрыты из OpenAPI, старый bootstrap-result отключён.

## После заливки

1. Railway redeploy.
2. В Custom GPT Actions заново импортировать `https://web-production-4310e.up.railway.app/openapi.json`.
3. В инструкцию GPT добавить две строки:

```txt
После createBootstrapPreview финальный ответ пользователю = response.message_to_user целиком.
После processTurn не показывай scene_response JSON; сначала вызови applyTurnResult, потом покажи только scene.rendered_text.
```
