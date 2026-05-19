# Railway deploy with persistent Volume

This backend can run on Railway without an OpenAI API key. In the MVP mode it stores session memory and builds prompts for regular ChatGPT.

## Why Volume is required

Session memory is stored in JSON files. If Railway redeploys the service without a persistent volume, runtime files may disappear.

Use a Railway Volume for:

```text
sessions
current_state
knowledge_map
npc_life_state
scene_history
turns
```

## 1. Create Railway project

1. Open Railway.
2. Click **New Project**.
3. Choose **Deploy from GitHub repo**.
4. Select:

```text
ioshi9212-dotcom/romance-novella-generator-api
```

5. Deploy the `main` branch.

## 2. Add variables

In Railway service → **Variables**, add:

```env
DATA_DIR=/app/data
```

Optional:

```env
OPENAI_MODEL=gpt-5.1-mini
```

Do not add `OPENAI_API_KEY` if you do not have one. The project works in manual GPT mode.

## 3. Add Volume

In Railway project:

1. Open your backend service.
2. Find **Volumes**.
3. Click **Add Volume**.
4. Set mount path:

```text
/app/data
```

5. Save changes.
6. Redeploy the service.

The environment variable and the volume mount must match:

```text
DATA_DIR=/app/data
Volume mount path=/app/data
```

## 4. Check deploy

Open the generated Railway domain.

Health check:

```text
https://YOUR-RAILWAY-DOMAIN/health
```

Expected response:

```json
{
  "status": "ok",
  "mode": "manual_gpt_without_required_api_key"
}
```

Docs:

```text
https://YOUR-RAILWAY-DOMAIN/docs
```

## 5. Create first session

Use:

```http
POST /api/v1/sessions
```

Body:

```json
{
  "title": "Railway Test Session",
  "genre": "urban mystery romance",
  "player_name": "Noa Hart"
}
```

Copy `session.session_id`.

## 6. Generate prompt for regular ChatGPT

Use:

```http
POST /api/v1/sessions/{session_id}/turns
```

Body:

```json
{
  "player_input": "stay silent and look around",
  "mode": "manual_gpt"
}
```

Copy the returned `prompt` into regular ChatGPT.

## 7. Save ChatGPT result back to Railway

Use:

```http
POST /api/v1/sessions/{session_id}/manual-results
```

Paste the scene and JSON updates from ChatGPT.

## 8. Test that Volume works

1. Create a session.
2. Save at least one manual result.
3. Redeploy or restart Railway service.
4. Open:

```http
GET /api/v1/sessions
```

If the session still appears, the Volume works.

## 9. Common mistakes

### Sessions disappear after redeploy

Most likely Volume is missing or mounted to the wrong path.

Correct setup:

```text
DATA_DIR=/app/data
Volume mount path=/app/data
```

### Health check fails

Check Railway logs. The start command should be:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

This is already configured in `railway.json` and `Procfile`.

### Missing template error

The file must exist in the repo:

```text
data/templates/session_template.json
```

### Prompt works but memory does not update

After using `/turns` with `manual_gpt`, you must also send the generated result to:

```http
POST /api/v1/sessions/{session_id}/manual-results
```

The `/turns` endpoint only builds the prompt. It does not save a generated scene in manual mode.
