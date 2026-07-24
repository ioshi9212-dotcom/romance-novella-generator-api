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
8. Style, pace, rating, and explicitness preferences.

The user supplies preferences, not the whole plot.

## Clarification

Ask only questions whose answers materially alter the story. Do not repeat answered questions. Invent ordinary missing details yourself. Never reveal planned twists.

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

It may also contain style, rating, relationship preferences, scene format, and user-visible premise. It contains no spoilers.

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
