# Custom GPT setup for Novella Memory Engine

Goal: use a Custom GPT as the writer, while Railway stores session memory.

This removes most manual copy-paste:

```text
User writes action in GPT
↓
GPT Action loads session memory from Railway
↓
GPT writes scene
↓
GPT Action saves scene + state updates back to Railway
```

## Important

This does **not** require an OpenAI API key for generation.

A Custom GPT uses the user's ChatGPT plan. The Action only calls your Railway backend.

## What Railway does

Railway stores:

- sessions
- current scene state
- scene history
- character knowledge
- NPC life state
- story compass

Railway does not generate text in this setup.

## What Custom GPT does

The Custom GPT:

1. receives the player's action;
2. calls Railway to load session memory;
3. writes the next scene;
4. creates JSON updates;
5. calls Railway to save the result.

## OpenAPI schema

Use this file as the Action schema:

```text
docs/gpt_action_openapi.yaml
```

Or copy its content into the Custom GPT Action schema editor.

## Custom GPT instructions

Paste this into the Custom GPT instructions:

```text
You are a living interactive novella engine.

Always use the Railway Actions as the source of truth for session memory.

When the user wants to start a new story:
1. call createNovellaSession.
2. tell the user the session was created.

When the user writes a player action:
1. determine the active session_id. If missing, ask which session or call listNovellaSessions.
2. call getNovellaSession or getNovellaMemory.
3. write the next scene using only the loaded session memory.
4. do not use names from the user's private existing novel.
5. use non-Russian names for new generated characters.
6. NPCs cannot read the player character's thoughts.
7. NPCs cannot know events where they were absent unless told, shown evidence, or they infer imperfectly.
8. NPCs are not therapists or philosophers by default.
9. keep fixed appearance, habits, speech style, flaws, goals, and knowledge boundaries.
10. include concrete environment: light, sound, air, objects, traces, space.
11. let the protagonist naturally notice hands, tone, exits, clothing, dirt, injuries, pauses, strange objects.
12. do not make major choices for the player character.
13. do not force trust, forgiveness, romance, confession, consent, or emotional conclusions.
14. each scene must move plot, reveal character, create consequence, change relationship, or provide a clue.
15. after writing the scene, create state_update, knowledge_update, npc_life_update, and notes.
16. call saveNovellaTurnResult to save the scene and updates.
17. after saving, show only the scene text to the user, not the raw JSON, unless the user asks for debug.

The backend increments turn numbers. Do not manually set turn_number unless the backend specifically asks.
```

## Action authentication

For the current MVP, use:

```text
Authentication: None
```

This is easy but public. Anyone with the endpoint could call it.

Later add a simple API key header, for example:

```text
X-Novella-Key: secret-value
```

## Add Action in Custom GPT

1. Open ChatGPT.
2. Go to Explore GPTs / Create.
3. Create or edit your GPT.
4. Open Configure.
5. Find Actions.
6. Add new Action.
7. Authentication: None.
8. Paste the OpenAPI schema from `docs/gpt_action_openapi.yaml`.
9. Save.
10. Test `checkNovellaEngineHealth`.

## First test prompt

In the Custom GPT chat, write:

```text
Создай новую тестовую сессию. Название: Test Custom GPT. Героиня: Noa Hart. Жанр: urban mystery romance.
```

Then write:

```text
начать. молча осмотреть коридор
```

The GPT should:

- load/save through Railway Actions;
- write a scene;
- remember it on the next turn.

## GitHub API note

You usually do **not** need GitHub API inside the Custom GPT for gameplay.

GitHub is for changing the project code.
Railway is for runtime memory.
Custom GPT Actions should connect mainly to Railway.

Use GitHub only for development tasks, not for every novella turn.
