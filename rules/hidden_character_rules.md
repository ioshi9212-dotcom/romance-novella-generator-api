# Hidden Character Rules

Новый bootstrap хранит неизвестных будущих людей как короткие `hidden_character_seeds`: id, сюжетная роль, условие входа и заметка — без имени, внешности и готовой личности. `hidden_core` остаётся только для старых сессий; там полная карточка уже создана.

## Seed

`character_creation_request` — необязательное разрешение, а не присутствующий персонаж. Если вход причинно произошёл в тексте сцены, создай ровно одну полную карточку в `new_or_updated_characters` и укажи точный `source_seed_id`. Если входа нет, не создавай карточку: seed сохранится.

До фактического появления человек не входит в active/nearby или witnesses, ничего о сцене не знает и не имеет отношений. Не раскрывай его имя, внешность, романтическую функцию или тайну заранее.

## Legacy hidden_core

У legacy `hidden_core` есть полная карточка, но до раскрытия действуют `introduced=false`, `known_to_player=false`, `show_in_preview=false`, `available_to_scene=false`. Карточка и runtime не попадают в видимый preview.

`candidate_not_present_yet` — только допустимый кандидат, не свидетель. Вводить его необязательно; в первой сцене разрешён максимум один новый значимый персонаж.

Для фактического раскрытия верни существующие id/name/role, а также `reveal_id`, `reason`, `source_in_scene` и matching `director_bible_patches.reveal_updates` со `status=revealed`. Только атомарный reveal разрешает active/nearby/witnesses; полную карточку заново не переписывай.

Фоновый NPC может возникнуть по месту, но не становится автоматически seed или hidden_core.
