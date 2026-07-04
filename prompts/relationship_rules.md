# Relationship Rules

Отношения меняются только от видимых действий, сказанных слов, сохранённых событий, повторяющегося поведения или доказанного знания.

## Где хранится

В v8 отношения сохраняются отдельно по парам:

```txt
state/relationship_pairs/<a>__<b>.json
```

`a` и `b` — `character_id`, созданные внутри конкретной сессии. Готовых персонажей в репозитории нет.

## Pair id

`pair_id` строится из двух character_id, отсортированных по алфавиту:

```txt
<character_a_id>__<character_b_id>
```

## Структура пары

Пара должна хранить не только общий уровень, но и направленные взгляды:

```json
{
  "pair_id": "character_a__character_b",
  "character_a": "character_a",
  "character_b": "character_b",
  "type": "string",
  "status": "short status",
  "scores": {
    "trust": 50,
    "tension": 20,
    "attachment": 40,
    "respect": 30,
    "fear": 0,
    "curiosity": 35
  },
  "a_view_of_b": {
    "summary": "как a воспринимает b",
    "current_assumption": "что a думает сейчас"
  },
  "b_view_of_a": {
    "summary": "как b воспринимает a",
    "current_assumption": "что b думает сейчас"
  },
  "shared_history": [],
  "recent_changes": [],
  "open_threads": []
}
```

## Relationship patch

Каждый relationship patch обязан иметь:

- `pair_id`;
- `change_type`;
- `entry`;
- `reason`;
- `source_in_scene`.

Желательно добавлять `trigger_source`, если изменение связано с `likes_in_people` / `dislikes_in_people` одного из персонажей.

```json
{
  "pair_id": "character_a__character_b",
  "change_type": "trust / tension / respect / attachment / fear / curiosity",
  "entry": "короткое описание изменения",
  "reason": "почему отношение изменилось",
  "source_in_scene": "конкретная реплика/действие в сцене",
  "trigger_source": {
    "character_id": "whose reaction changed",
    "matched_like": "какое like сработало или null",
    "matched_dislike": "какое dislike сработало или null",
    "visible_behavior": "что персонаж увидел"
  }
}
```

## Не завышать изменения

Один ход редко полностью меняет отношения. Лучше маленький точный сдвиг, чем резкий скачок без основания.

## Реакции разные

Одно и то же действие игрока может по-разному повлиять на разных NPC:

- один уважает прямоту;
- другой считает её грубостью;
- один ценит спокойствие;
- другой принимает его за холодность;
- один любит риск;
- другой видит в нём безответственность.

## Не показывать лишнее

В нижнем блоке отношений показываются только персонажи, которые:

- физически есть в текущей сцене;
- или прямо затронуты текущим ходом.

Не показывай скрытые отношения и персонажей вне сцены.
