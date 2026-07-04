# API Contracts

Контракты для генератора новелл.

Этот слой не содержит готового лора или персонажей.

## Основной поток

```txt
create_session
  -> bootstrap state
  -> scene_contract
  -> scene_response with proposed_updates
  -> apply_turn_result
  -> save state
```

## Файлы

- `schemas/bootstrap_output.schema.json`
- `schemas/scene_contract.schema.json`
- `schemas/scene_response.schema.json`
- `schemas/apply_turn_result.schema.json`
