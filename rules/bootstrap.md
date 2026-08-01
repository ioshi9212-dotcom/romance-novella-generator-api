# Bootstrap rules

## First questionnaire

Ask in one compact message:

1. Desired genre and emotional tone.
2. Where and when the story happens.
3. POV name, age, personality, appearance, and position.
4. Desired romantic, family, friendship, or rivalry dynamics.
5. Central theme or conflict.
6. Forbidden content and boundaries.
7. Starting situation.
8. Naming convention: cultural basis, whether names are foreign or Russian, and
   whether names and place names must be written in Cyrillic.
9. Style, pace, rating, explicitness, literary density, description detail, and
   the desired amount of directorial irony or sarcasm.
10. Presentation preferences: header, scene-body length, dialogue layout,
    guidance blocks, state, relationships, and turn number.

The user supplies preferences, not the whole plot. The user may answer freely
and is never required to fill every item.

Offer a compact prose-mode choice instead of demanding literary terminology:

- serious literary — detailed, restrained, psychologically precise;
- cinematic — visual, dynamic, with sharper scene cuts;
- intimate psychological — close attention to reactions and subtext;
- atmospheric — denser setting, sensory detail, and mood;
- light ironic — lively framing and noticeable directorial wit.

Ask for directorial irony separately: none, subtle, noticeable, or pronounced.
The selected mode is a baseline that may bend with the scene without changing
into another genre.

If the user leaves naming unspecified, use non-Russian names written in
Cyrillic. Keep one coherent naming culture within a location or social group;
do not mix unrelated Russian, English, Japanese, and invented names at random.

## Clarification

Ask only questions whose answers materially alter the story, resolve a genuine
contradiction, or establish a boundary. Do not repeat answered questions.
Unanswered ordinary fields are director work: invent concrete values and save
them in bootstrap. Never return a validation repair to the user as a new
question. Never reveal planned twists.

Save the user's complete raw questionnaire answer before building bootstrap.
Do not summarize or shorten it. A retry with identical content must not create
a second questionnaire entry. If normalization causes an Action error, retry
with the same raw answer and an empty normalized object; never ask the user to
type the answer again.

When repairing a saved bootstrap part, deep-merge only the invented or corrected
fields. Do not replace a complete part with a small patch and thereby erase
previously saved user-derived data.

## What the director creates

- exact title and starting datetime;
- place, routes, social environment, and ordinary routines;
- a complete POV card;
- 2–7 useful starting NPCs unless the user requests otherwise;
- one main causal line and 2–4 secondary lines;
- hidden truth and plausible mistaken versions;
- autonomous NPC plans and deadlines;
- a strong opening situation.

## Required bootstrap structures

### profile

Must contain:

- `title`
- `genre`
- `tone`
- `pov_id`
- `boundaries`
- `start`
- `naming`
- `presentation`
- `prose_style`

`naming` records the selected cultural basis, foreign/Russian preference,
script, and location-name convention. `presentation` records the header,
dialogue, scene-body length, guidance, state, relationship, and turn-number
settings. `prose_style` records seriousness, detail, literary density, pace,
and directorial irony. These are session canon for rendering, not global
assumptions.

It may also contain rating, relationship preferences, and user-visible
premise. It contains no spoilers.

### lore

Prefer:

- `summary`
- `world_rules`
- `locations`
- `facts`

Facts may include `id`, `character_ids`, `location_ids`, `plotline_ids`, and `always_include` so the server can select relevant context without embeddings.

### hidden_canon

Prefer:

- `core_truths`
- `facts`
- `false_versions`
- `causal_chain`
- `constraints`

Hidden truth is stable. Do not change it retroactively merely to make a twist convenient.

### plot

Prefer:

- `lines` keyed by stable plotline ID;
- `clocks`;
- `npc_plans`.

Each line may contain status, participant IDs, stakes, current stage, next window, and relevant hidden-canon references.

### current

Must contain:

- ISO `datetime`;
- `location_id`;
- `pov_state`.

It may include present, nearby, and scheduled character IDs; clothing; possessions; injuries; current occupation; obligations; last pose; unfinished movement; and continuation point.
It should also keep the current weather, season/story period, readable location
label, immediate scene condition, POV condition, clothing, and relevant
inventory whenever the presentation header needs them.

### character

Each card has stable ID and should contain:

- name and aliases;
- observable appearance;
- voice and speech habits;
- personality, values, flaws, and self-deception;
- goals and what the NPC does without the POV;
- fears and boundaries;
- skills, work, past, connections, and schedule;
- tags;
- `starting_knowledge`;
- directional `initial_relationships`.

Do not make every NPC sarcastic, emotionally articulate, attracted to the POV, or focused only on the POV.

### review

The public review contains only material safe for the user: profile, setting, POV, known starting characters, boundaries, and opening situation. It never contains hidden truths, planned betrayals, secret motives, or future twists.
