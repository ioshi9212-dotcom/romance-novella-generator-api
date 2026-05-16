# Romance Novella Generator API

Backend for a living interactive novella generator: **one new chat = one isolated story session**.

The project is built for later deployment on **Railway** and connection to the **OpenAI API**. The model is not treated as the source of truth: session JSON files store canon, character memory, NPC offscreen life, relationships, and story goals.

## Core idea

```text
Player input
↓
Load session state
↓
Load canon, knowledge map, NPC life, story compass
↓
Generate next scene
↓
Check logic
↓
Apply only allowed state updates
↓
Save turn into this session only
```

## What is already included

- FastAPI backend.
- JSON-based storage for MVP.
- Separate session folder for every new chat/playthrough.
- Fixed character canon: appearance, habits, speech style, goals, flaws.
- Knowledge map: characters only know what they saw, heard, were told, or logically inferred.
- NPC offscreen life state: NPCs have location, plans, private events, and are not always conveniently available.
- Story compass: main goal, active threads, forbidden drift.
- Prompt files for scene writing, logic checking, state updating, and NPC creation.
- Optional OpenAI Responses API integration.
- Local fallback generator when `OPENAI_API_KEY` is not set.

## Run locally

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open:

```text
http://127.0.0.1:8000/docs
```

## Environment variables

```env
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-5.1-mini
DATA_DIR=data/runtime
```

For Railway, set:

```env
DATA_DIR=/app/data
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-5.1-mini
```

Mount a Railway volume to `/app/data` so sessions survive restarts.

## API

### Health

```http
GET /health
```

### Create new story session

```http
POST /api/v1/sessions
```

Body:

```json
{
  "player_name": "Noa Hart",
  "genre": "urban mystery romance",
  "title": "New Session"
}
```

### Read session

```http
GET /api/v1/sessions/{session_id}
```

### Play one turn

```http
POST /api/v1/sessions/{session_id}/turns
```

Body:

```json
{
  "player_input": "stay silent and look around",
  "use_llm": true
}
```

### Read memory files

```http
GET /api/v1/sessions/{session_id}/memory
```

## Important writing rules

- Do not use names from an existing user novel.
- Use non-Russian names for generated characters.
- NPCs cannot read the player character's thoughts.
- NPCs cannot know events from scenes where they were absent unless someone tells them or evidence exists.
- NPCs must not all be equally convenient or equally hostile.
- NPCs are not default therapists or philosophers.
- The environment must be concrete: light, air, sound, objects, traces, spatial details.
- The protagonist may automatically notice natural details: hands, voice, clothing, pauses, dirt, injuries, exits, unusual objects.
- The model may write short physical reactions and intrusive thoughts, but must not make major choices for the player.

## Project structure

```text
app/
  main.py
  config.py
  engine.py
  llm.py
  models.py
  session_manager.py
  storage.py

data/
  templates/
    session_template.json

prompts/
  scene_writer.md
  logic_checker.md
  state_updater.md
  character_creator.md
```
