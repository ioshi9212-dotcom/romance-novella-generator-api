# State Updater Rules

ChatGPT не пишет state напрямую.

Он возвращает proposed_updates, а API:

1. проверяет схему;
2. проверяет знание;
3. проверяет locked-анкету;
4. применяет разрешённое;
5. отклоняет опасное;
6. пишет apply result.

## Что можно менять

- current_state;
- relationships;
- knowledge;
- npc_state;
- scene_history;
- turns;
- future_locks только через отдельный валидируемый patch.

## Что нельзя менять напрямую

- locked base character card;
- жанр и основной тон без запроса пользователя;
- скрытую будущую правду без сценического триггера.
