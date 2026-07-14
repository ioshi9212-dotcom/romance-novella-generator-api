# Scene Writer

Runtime больше не использует ручную копию правил из этого файла.

`app.scene_rules_compiler.compile_scene_rules()` собирает канонический блок `RUNTIME_SCENE_RULES` из:

1. `prompts/player_input_rules.md`;
2. `rules/player_agency.md`;
3. `prompts/npc_rules.md`;
4. `prompts/knowledge_rules.md`;
5. `prompts/relationship_rules.md`;
6. `rules/hidden_character_rules.md`;
7. `rules/scene_style.md`;
8. `rules/no_micro_choice.md`;
9. `prompts/scene_format_rules.md`.

Приоритет конфликтов:

1. player agency;
2. knowledge boundaries;
3. hidden-content locks;
4. locked character cards;
5. current frame и persistent state;
6. направленные отношения и npc runtime;
7. story plan;
8. стиль и формат.

`turn_processor` добавляет только короткую tool-flow оболочку, скомпилированные правила и `SCENE_CONTRACT_JSON`. Изменение канонического файла автоматически меняет runtime prompt после деплоя; отдельную ручную копию обновлять нельзя.