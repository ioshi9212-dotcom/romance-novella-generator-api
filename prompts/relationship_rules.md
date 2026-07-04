# Relationship Rules

Отношения хранятся отдельно от анкет.

Персонаж не меняется каждый ход. Меняется связь между персонажами.

## Формат

```json
{
  "protagonist__ex_partner": {
    "type": "exes",
    "trust": 20,
    "tension": 80,
    "attachment": 55,
    "status": "unfinished",
    "known_history": "short",
    "open_threads": [],
    "history": []
  }
}
```

## Правила

- Не чинить конфликт слишком быстро.
- Не делать резкие скачки без действия/реплики.
- Любой сдвиг должен иметь source_in_scene.
