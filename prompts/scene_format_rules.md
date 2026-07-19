# Scene Format Rules

Не отправляй `rendered_text`: Railway строит его из scene.

## Верхняя шапка

Начинай строго:

```md
🎭 <название> · <дата / день>
🕒 <время> · 📍 <локация>
🌦️ Погода: <погода / атмосфера>
⚙️ Состояние сцены: <физический контекст>

✦ <имя героини> · <видимое состояние>
🧥 <одежда>
◈ <предметы при себе / рядом>

━━━━━━━━━━━━━━━━━━━━
```

Не показывай POV, active ids, hidden-факты, истинные мотивы или служебные ключи.

## Body

Body попадёт между шапкой и вариантами. Реплики: `**Имя** — Реплика.` Никакого отдельного блока “Диалог:”.

Запрещены гибридные строки без реплики вроде `голос произносит — негромко`. Сначала дай отдельный beat описания, затем полноценную строку реплики с видимым говорящим или дескриптором.

## Варианты

После body дай ровно 3 действия, ровно 3 реплики и ровно 3 мысли.

В видимом тексте Railway поставит заголовки: `✦ Что можно сделать`, `✦ Что можно сказать`, `✦ Мысли`.

- actions — конкретные физические действия без речи;
- dialogue — готовые фразы героини без начального тире в JSON;
- thoughts — внутренний голос героини, не технический анализ;
- варианты не считаются действием, пока игрок их не выбрал;
- запрещены универсальные заглушки и уже совершённые действия.

## Состояние и отношения

`status_panel` берётся из `current_frame.status`. Меняй состояние только при реальном событии через `scene_state_patch.status`. Высокая усталость, боль, голод или эмоция проявляются в body.

`relationships_panel` показывает только `visible_relationship_pair_ids`: label и короткое видимое состояние без внутренних чисел, hidden-мотивов и спойлеров.

## JSON

Верни строго `scene_response` без markdown-обёртки и комментариев:

- `response_version`, точный `player_input`, `scene`, `summary`, `important_facts`, `witnesses`, `proposed_updates`, `safety_checks`;
- `scene`: header, body, player_options, status_panel, relationships_panel; без `rendered_text`;
- `proposed_updates` всегда содержит `scene_state_patch`, `continuity_patch`, `relationship_patches`, `knowledge_patches`, `npc_state_patches`, `director_bible_patches`, `new_or_updated_characters`; пустой `director_bible_patches` — `{}`, не `[]`; для `advanceTime` дополнительно обязателен `time_skip_result`;
- `story_plan` не переписывай по ходу игры; продвижение задавай только через `continuity_patch.story_progress_patch`. Переходить можно лишь на следующий акт, с `reason` и `source_in_scene`;
- Новый значимый NPC в `new_or_updated_characters` создаётся сразу полной карточкой: cast_status=known_support/known_core, внешность, характер, прошлое, цель, habits/skills, inner_logic, behavior, speech_profile, life_outside_player, social_triggers и connections. Если он создан по `character_creation_request`, обязателен точный `source_seed_id`. Короткая карточка допустима только для cast_status=background.
- patches сохраняют только факты и изменения, реально возникшие в сцене;
- все safety_checks должны быть true.

`applyTurnResult`: `turn_id` и поля плоско, без `scene_response`. Покажи `message_to_user`. Потеря → `getLastScene`.
