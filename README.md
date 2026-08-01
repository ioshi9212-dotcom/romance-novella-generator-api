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
- questionnaire answers are stored idempotently and may be incomplete;
- ordinary questionnaire gaps are director repairs, not mandatory user questions;
- bootstrap repairs can be deep-merged without erasing saved fields;
- normalized explicit questionnaire facts must be represented in generated state;
- every prepared turn has an immutable `turn_id`;
- context chunks read the same frozen packet;
- required scene context is never silently truncated: overflow blocks preparation;
- chronology, full lore, full hidden canon, every scene card, and its knowledge are loaded;
- commits require the exact `base_state_version`;
- repeated prepare and commit calls are idempotent;
- per-session file locks prevent concurrent writers;
- multi-file commits use a recovery journal;
- a scene is canonical only after `commitTurn`;
- standard scene presentation and stored body-length limits are validated before commit;
- every tenth play turn requires a persisted continuity audit;
- character renames refresh the name/alias index;
- technical corrections do not advance story time or turn number;
- committed transaction payload copies are compacted after recovery is no longer needed;
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
    questionnaire_source.json
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

Required variable:

```text
DATA_DIR=/data
```

Recommended variable:

```text
ENVIRONMENT=production
```

No API or Action key is required. In keyless mode each novel is protected by its
random session ID and private resume code, and `listSessions` is disabled to
prevent session enumeration.

An optional shared secret can be enabled with `ACTION_TOKEN`. For compatibility,
the previous name `API_KEY` is also accepted. Requests may then authenticate with
either `X-API-Key: <secret>` or `Authorization: Bearer <secret>`, and
`listSessions` becomes available.

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

5. Select no authentication.
6. Test `createSession`, `saveQuestionnaire`, and `resumeSession` in Preview.

Repository deployment updates the hosted Action schema, but it does not replace
the text already pasted into an existing Custom GPT. After deploying a version
that changes `gpt/custom_gpt_instructions.md`, paste that file into the GPT editor
again and re-import the hosted Action schema before testing in Preview.

This token is a private secret between the Custom GPT and this Railway service. It is not an OpenAI API key.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
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
saveQuestionnaire(clarification) only for material contradictions
saveBootstrapPart x N
validateBootstrap
saveBootstrapPart(merge=true) until next_action=show_review
show public review
confirmBootstrap
```

### Story turn

```text
prepareTurn
getTurnChunk until has_more=false
verify context_complete=true and read every returned section
write scene and structured result
include audit_updates when audit_due=true
commitTurn
show the committed scene
```

### Failed request

Retry the same `turn_id`. Do not generate a second turn. A repeated commit returns the original receipt without applying changes twice.

For questionnaire saves, retry with the exact same raw answer; identical
requests are idempotent. If only normalization is malformed, retry with
`normalized: {}`. Do not ask the user to retype visible answers. Validation
items in `director_repairs` must be invented by the Custom GPT and written with
`merge: true`; only `user_questions` may be returned to the user.

## Deliberate non-goals

The first version has no PostgreSQL, Redis, vector database, web frontend, OAuth, background worker, multi-replica deployment, generated ZIP files, or OpenAI API integration.

PostgreSQL becomes appropriate when the generator is shared among unrelated users, needs OAuth accounts, requires multiple Railway replicas, or receives concurrent writes to the same session.
