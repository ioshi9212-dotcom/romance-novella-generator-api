from pathlib import Path


PATH = Path("app/novella_openapi_actions.py")
text = PATH.read_text(encoding="utf-8")

old_preview_fields = '''        "message_to_user": {"type": "string"},
        "session_id": {"type": "string"},
        "status": {"type": "string"},
        "must_show_to_user": {"type": "boolean"},
        "wait_for_confirmation": {"type": "boolean"},
        "next_user_action": {"type": "string"},
        "preview": {"type": "string"},
        "user_visible_preview": {"type": "string"},
        "can_confirm": {"type": "boolean"},
        "diagnostics": _loose_obj(),
'''
new_preview_fields = '''        "message_to_user": {
            "type": "string",
            "description": "First bounded preview chunk. Load all remaining chunks before replying when has_more_preview_chunks is true.",
        },
        "session_id": {"type": "string"},
        "status": {"type": "string"},
        "must_show_to_user": {"type": "boolean"},
        "wait_for_confirmation": {"type": "boolean"},
        "next_user_action": {"type": "string"},
        "preview": {"type": "string", "description": "Compatibility alias for the first bounded preview chunk."},
        "user_visible_preview": {"type": "string", "description": "Compatibility alias for the first bounded preview chunk."},
        "preview_id": {"type": "string"},
        "preview_chunk": {"type": "string"},
        "preview_chunk_index": {"type": "integer", "minimum": 0},
        "preview_chunk_count": {"type": "integer", "minimum": 1},
        "has_more_preview_chunks": {"type": "boolean"},
        "next_preview_chunk_index": {"type": ["integer", "null"]},
        "can_confirm": {"type": "boolean"},
        "diagnostics": _loose_obj(),
'''
if text.count(old_preview_fields) != 1:
    raise RuntimeError("preview response properties block not found exactly once")
text = text.replace(old_preview_fields, new_preview_fields, 1)

old_required = '''        "preview",
        "user_visible_preview",
        "can_confirm",
'''
new_required = '''        "preview",
        "user_visible_preview",
        "preview_id",
        "preview_chunk",
        "preview_chunk_index",
        "preview_chunk_count",
        "has_more_preview_chunks",
        "next_preview_chunk_index",
        "can_confirm",
'''
if text.count(old_required) != 1:
    raise RuntimeError("preview response required block not found exactly once")
text = text.replace(old_required, new_required, 1)

preview_schema_end = '''    additional_properties=True,
)

SAVE_BOOTSTRAP_PART_RESPONSE_SCHEMA = _schema_obj(
'''
chunk_schema = '''    additional_properties=True,
)

BOOTSTRAP_PREVIEW_CHUNK_RESPONSE_SCHEMA = _schema_obj(
    {
        "session_id": {"type": "string"},
        "preview_id": {"type": "string"},
        "chunk_index": {"type": "integer", "minimum": 0},
        "chunk_count": {"type": "integer", "minimum": 1},
        "preview_chunk": {"type": "string"},
        "has_more": {"type": "boolean"},
        "next_chunk_index": {"type": ["integer", "null"]},
        "diagnostics": _loose_obj(),
    },
    required=[
        "session_id",
        "preview_id",
        "chunk_index",
        "chunk_count",
        "preview_chunk",
        "has_more",
        "next_chunk_index",
        "diagnostics",
    ],
    additional_properties=True,
)

SAVE_BOOTSTRAP_PART_RESPONSE_SCHEMA = _schema_obj(
'''
if text.count(preview_schema_end) != 1:
    raise RuntimeError("preview response schema end not found exactly once")
text = text.replace(preview_schema_end, chunk_schema, 1)

old_description = '''                "Use questionnaire, staged bootstrap parts, preview-confirm launch flow, chunked processTurn, "
                "then applyTurnResult with the exact turn_id. Use advanceTime only for a user-selected natural-pause skip."
'''
new_description = '''                "Use questionnaire, staged bootstrap parts, chunked preview-confirm launch flow, chunked processTurn, "
                "then applyTurnResult with the exact turn_id. Use advanceTime only for a user-selected natural-pause skip."
'''
if text.count(old_description) != 1:
    raise RuntimeError("OpenAPI info description not found exactly once")
text = text.replace(old_description, new_description, 1)

old_components = '''                "BootstrapPreviewRequest": BOOTSTRAP_PREVIEW_SCHEMA,
                "BootstrapPreviewResponse": BOOTSTRAP_PREVIEW_RESPONSE_SCHEMA,
                "SaveBootstrapPartRequest": SAVE_BOOTSTRAP_PART_SCHEMA,
'''
new_components = '''                "BootstrapPreviewRequest": BOOTSTRAP_PREVIEW_SCHEMA,
                "BootstrapPreviewResponse": BOOTSTRAP_PREVIEW_RESPONSE_SCHEMA,
                "BootstrapPreviewChunkResponse": BOOTSTRAP_PREVIEW_CHUNK_RESPONSE_SCHEMA,
                "SaveBootstrapPartRequest": SAVE_BOOTSTRAP_PART_SCHEMA,
'''
if text.count(old_components) != 1:
    raise RuntimeError("OpenAPI components insertion point not found exactly once")
text = text.replace(old_components, new_components, 1)

confirm_path = '''            "/api/v1/sessions/{session_id}/bootstrap-confirm": {
'''
chunk_path = '''            "/api/v1/sessions/{session_id}/bootstrap-preview-chunk": {
                "get": {
                    "operationId": "getBootstrapPreviewChunk",
                    "summary": (
                        "Get one stored preview chunk. When create/finalize preview reports more chunks, "
                        "load every remaining index and concatenate them before showing the draft or confirming it."
                    ),
                    "parameters": [
                        _session_id_param(),
                        {
                            "name": "preview_id",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string", "minLength": 1},
                            "description": "Exact preview_id returned by createBootstrapPreview or finalizeBootstrapPreview.",
                        },
                        {
                            "name": "chunk_index",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "integer", "minimum": 1},
                            "description": "Start at 1 because the preview response already returned chunk 0.",
                        },
                    ],
                    "responses": {
                        "200": _json_response(
                            "Bootstrap preview chunk",
                            {"$ref": "#/components/schemas/BootstrapPreviewChunkResponse"},
                        ),
                        "409": _json_response("Missing or stale preview id", _loose_obj()),
                        "416": _json_response("Chunk index out of range", _loose_obj()),
                    },
                }
            },
            "/api/v1/sessions/{session_id}/bootstrap-confirm": {
'''
if text.count(confirm_path) != 1:
    raise RuntimeError("bootstrap confirm path not found exactly once")
text = text.replace(confirm_path, chunk_path, 1)

PATH.write_text(text, encoding="utf-8")
