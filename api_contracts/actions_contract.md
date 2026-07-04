# GPT Actions Contract

Этот API не вызывает LLM изнутри. Custom GPT сам является писателем и вызывает Railway как action/tool.

## Roles

```text
Custom GPT = writer + JSON producer
Railway API = memory + context builder + validator + state storage
GitHub = code + schemas + prompts + rules
```

## New session flow

```text
User setup
↓
createSession(mode="gpt_actions")
↓
if needs_questionnaire: show questionnaire
↓
if bootstrap_pending: GPT uses bootstrap_prompt
↓
GPT creates bootstrap_json
↓
applyBootstrapResult
↓
session status active
```

## Turn flow

```text
player_input
↓
processTurn(mode="gpt_actions")
↓
Railway returns scene_prompt with rules + SCENE_CONTRACT_JSON
↓
GPT writes scene_response JSON
↓
applyTurnResult
↓
Railway validates and saves updates
↓
GPT shows only scene.rendered_text to user
```

## No internal LLM mode

Do not use an internal `llm` mode in Railway for this project version. The GPT connected through Actions is the creative model.

## Modes

- `gpt_actions`: real intended mode for Custom GPT + Railway Actions.
- `debug_stub`: local technical testing without a creative model.

## Hard requirements

- Never write a scene without a scene prompt or scene contract.
- Never expose tool JSON/status to the user unless in technical/debug mode.
- `applyTurnResult` must be called after every meaningful GPT-written scene.
- Basic character cards are locked; update relationships/knowledge/current_state, not core identity.
- Visible header must not include POV, Focus, active character list, technical ids.
