# Manual test: GPT without API key

This guide is for the current MVP mode where there is **no OpenAI API key**.

The backend stores session memory and builds a full prompt. You paste that prompt into regular ChatGPT, then save the generated scene back into the backend.

## 1. Run the backend locally

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
```

macOS/Linux:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Start server:

```bash
uvicorn app.main:app --reload
```

Open Swagger UI:

```text
http://127.0.0.1:8000/docs
```

## 2. Check server health

Open endpoint:

```http
GET /health
```

Expected response:

```json
{
  "status": "ok",
  "mode": "manual_gpt_without_required_api_key"
}
```

## 3. Create a new story session

Open endpoint:

```http
POST /api/v1/sessions
```

Example body:

```json
{
  "title": "Test Session 1",
  "genre": "urban mystery romance",
  "player_name": "Noa Hart"
}
```

After sending, copy the returned `session.session_id`.

Example:

```text
session_20260516_183000_ab12cd34
```

Every new session is a separate playthrough. It has its own memory, NPC state, knowledge map, story compass, and scene history.

## 4. Read session memory

Open endpoint:

```http
GET /api/v1/sessions/{session_id}/memory
```

Use your real `session_id`.

Check that memory contains:

- `current_state`
- `player_character`
- `characters`
- `relationships`
- `knowledge_map`
- `npc_life_state`
- `story_compass`

## 5. Generate a prompt for regular ChatGPT

Open endpoint:

```http
POST /api/v1/sessions/{session_id}/turns
```

Example body:

```json
{
  "player_input": "stay silent and look around",
  "mode": "manual_gpt"
}
```

The backend returns:

```json
{
  "mode": "manual_gpt",
  "instruction": "Copy this prompt into ChatGPT. Then paste the generated scene and JSON updates into /manual-results.",
  "prompt": "..."
}
```

Copy the full `prompt` value and paste it into regular ChatGPT.

## 6. Get scene from ChatGPT

ChatGPT should return sections like this:

```text
## SCENE
*Scene text here...*

## STATE_UPDATE_JSON
```json
{}
```

## KNOWLEDGE_UPDATE_JSON
```json
{}
```

## NPC_LIFE_UPDATE_JSON
```json
{}
```

## LOGIC_NOTES
Checked presence, knowledge, environment, and player control.
```

Important: if ChatGPT returns invalid JSON, fix only the JSON blocks before saving.

## 7. Save the generated scene back to the backend

Open endpoint:

```http
POST /api/v1/sessions/{session_id}/manual-results
```

Example body:

```json
{
  "player_input": "stay silent and look around",
  "scene_text": "*The corridor smelled of rain and dust...*\n\n**Elias Voss** — Don't touch the door yet.",
  "state_update": {
    "time": "21:20",
    "location": "old hotel corridor",
    "active_characters": ["player", "elias_voss"],
    "scene_goal": "Noa must decide whether to inspect the scratched lock or question Elias."
  },
  "knowledge_update": {
    "player": {
      "add_knows": ["Elias warned her not to touch the scratched lock"],
      "remove_does_not_know": []
    },
    "elias_voss": {
      "add_knows": ["Noa stayed silent and observed the corridor"],
      "remove_does_not_know": []
    }
  },
  "npc_life_update": {
    "elias_voss": {
      "current_location": "old hotel corridor",
      "current_activity": "watching Noa and the locked room",
      "mood": "alert and guarded"
    }
  },
  "notes": [
    "Manual GPT result saved."
  ]
}
```

The backend will:

- increment `turn_number`,
- save the scene into `scene_history.json`,
- save the full turn into `turns.json`,
- update `current_state.json`,
- update `knowledge_map.json`,
- update `npc_life_state.json`.

## 8. Continue the story

Repeat:

```text
POST /turns
↓
copy prompt into ChatGPT
↓
copy scene and JSON updates
↓
POST /manual-results
```

Each session stays isolated.

## 9. Local stub mode

For a quick test without ChatGPT, use:

```http
POST /api/v1/sessions/{session_id}/turns
```

Body:

```json
{
  "player_input": "check the wet footprints",
  "mode": "local_stub"
}
```

This creates a placeholder scene and saves it immediately. It is only for testing storage and session flow.

## 10. Common problems

### Session not found

Check that you copied `session_id` correctly.

### Missing template

Make sure this file exists:

```text
data/templates/session_template.json
```

### ChatGPT invented knowledge for absent NPCs

Edit the scene before saving or regenerate with a reminder:

```text
Mara is not in this scene. She cannot know what happened in the hotel corridor.
```

### ChatGPT wrote the player's decision

Regenerate or edit it. The model may write observations and short thoughts, but not major choices.

### JSON does not save

Make sure the JSON blocks contain valid JSON: double quotes, no trailing commas, no comments.

## 11. What to test first

Good first action:

```text
stay silent and look around
```

Second action:

```text
look at the scratched lock but do not touch it
```

Third action:

```text
ask Elias why he stopped me
```

These actions test:

- automatic observations,
- environment details,
- NPC knowledge boundaries,
- player control,
- relationship tension,
- story compass.
