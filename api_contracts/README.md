# API Contracts — GPT Actions v5

Этот слой описывает работу Custom GPT с Railway API.

В этой версии Railway **не вызывает LLM внутри себя**. GPT подключается к Railway через Actions/OpenAPI и сам пишет:

- bootstrap JSON;
- сцену;
- proposed_updates.

Railway отвечает за:

- session state;
- scene contract;
- prompt builder;
- JSON schema validation;
- сохранение current_state, knowledge, relationships, characters, scene_history, turns.

Основные файлы:

```text
openapi.yaml
gpt/custom_gpt_instructions.md
api_contracts/actions_contract.md
schemas/*.schema.json
prompts/*.md
rules/*.md
app/scene_contract_builder.py
app/turn_processor.py
app/state_updater.py
```

Режимы:

```text
gpt_actions = основной режим для Custom GPT
debug_stub = техническая проверка без GPT
```

`llm`-режима здесь нет, чтобы не путать архитектуру.
