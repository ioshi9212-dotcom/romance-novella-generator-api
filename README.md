# Novel Runtime API

File-backed runtime for a literary Custom GPT novella generator.

The Custom GPT writes all prose. This service does not call the OpenAI API and does not require an OpenAI API key. It creates isolated novel sessions, freezes context for each turn, validates structured changes, and persists canon on a Railway Volume.

## Architecture

```text
User -> Custom GPT -> GPT Actions -> FastAPI on Railway -> Railway Volume
                                      ^
                                      |
                              GitHub code and rules
```

GitHub contains only universal code, rules, schemas, and blank templates. Generated lore and characters are stored under `/data/sessions/<session_id>` and never fall back to repository story content.

## Runtime guarantees

- one independent directory per session;
- draft bootstrap is separate from confirmed state;
- optional bootstrap omissions are warnings, not fatal errors;
- every prepared turn has an immutable `turn_id`;
- context chunks read the same frozen packet;
- commits require the exact `base_state_version`;
- repeated prepare and commit calls are idempotent;
- per-session file locks prevent concurrent writers;
- multi-file commits use a recovery journal;
- a scene is canonical only after `commitTurn`;
- technical corrections do not advance story time or turn number;
- action responses stay below conservative size budgets.

## Repository layout

```text
app/                    FastAPI and runtime services
gpt/                    instruction pasted into the Custom GPT
rules/                  universal literary and state rules
schemas/                JSON contracts
templates/              blank bootstrap examples
tests/                  API and persistence tests
openapi-actions.yaml    minimal GPT Action schema
railway.json            Railway deployment configuration
```

## Session layout

```text
/data/sessions/<session_id>/
  session.json
  bootstrap/
    questionnaire.json
    draft/
      profile.json
      lore.json
      hidden_canon.json
      plot.json
      current.json
      review.json
      characters/<character_id>.json
  state/
    profile.json
    lore.json
    hidden_canon.json
    plot.json
    current.json
    relationships.json
    chronology.jsonl
    scene_history.jsonl
    characters/index.json
    characters/<character_id>.json
    knowledge/<character_id>.json
  scenes/000001.md
  transactions/
    pending/<turn_id>/
    receipts/<turn_id>.json
  journal.jsonl
```

There is no stored `canon_canvas`: the context builder derives a frozen scene packet from canonical files. There is no ZIP continuation flow because session state persists on the Volume.

## Railway configuration

Use one service, one replica, one Uvicorn worker, and one Volume mounted at `/data`.

Required variables:

```text
DATA_DIR=/data
ENVIRONMENT=production
ACTION_TOKEN=<long random secret>
```

The production URL currently used by the Action schema is:

```text
https://web-production-4310e.up.railway.app
```

After deployment, verify:

```text
GET /health
GET /openapi-actions.yaml
```

Enable Railway Volume backups. Create a manual backup before future state-schema migrations.

## Custom GPT setup

1. Open the GPT editor.
2. Paste [`gpt/custom_gpt_instructions.md`](gpt/custom_gpt_instructions.md) into Instructions.
3. Add an Action.
4. Import:

   ```text
   https://web-production-4310e.up.railway.app/openapi-actions.yaml
   ```

5. Select API key authentication using Bearer.
6. Enter the same value as Railway `ACTION_TOKEN`.
7. Test `createSession`, `saveQuestionnaire`, and `listSessions` in Preview.

This token is a private secret between the Custom GPT and this Railway service. It is not an OpenAI API key.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
export ACTION_TOKEN=test-token
export DATA_DIR="$PWD/.data"
uvicorn app.main:app --reload
```

Run tests:

```bash
pytest
```

## Main Action flow

### New novel

```text
createSession
saveQuestionnaire(initial)
saveQuestionnaire(clarification)
saveBootstrapPart x N
validateBootstrap
show public review
confirmBootstrap
```

### Story turn

```text
prepareTurn
getTurnChunk until has_more=false
write scene and structured result
commitTurn
show the committed scene
```

### Failed request

Retry the same `turn_id`. Do not generate a second turn. A repeated commit returns the original receipt without applying changes twice.

## Deliberate non-goals

The first version has no PostgreSQL, Redis, vector database, web frontend, OAuth, background worker, multi-replica deployment, generated ZIP files, or OpenAI API integration.

PostgreSQL becomes appropriate when the generator is shared among unrelated users, needs OAuth accounts, requires multiple Railway replicas, or receives concurrent writes to the same session.
