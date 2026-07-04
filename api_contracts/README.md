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

## v2 scene layer

`scene_response` now carries a full visible scene structure:

- `scene.header`
- `scene.body`
- `scene.player_options.thoughts[3]`
- `scene.player_options.dialogue[3]`
- `scene.player_options.actions[3]`
- `scene.status_panel`
- `scene.relationships_panel`
- `scene.rendered_text`

The API saves `rendered_text` into `scene_history.visible_scene_text`.

Relationships shown in the visible footer must be limited to `visible_relationship_pair_ids` from `scene_contract`, unless the current turn directly affected another pair.
