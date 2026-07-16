from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one marker in {path}, found {count}: {old[:140]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "app/novella_openapi_actions.py",
    '''BOOTSTRAP_PREVIEW_RESPONSE_SCHEMA = _schema_obj(
    {
        "message_to_user": {"type": "string"},
        "session_id": {"type": "string"},
        "status": {"type": "string"},
        "must_show_to_user": {"type": "boolean"},
        "wait_for_confirmation": {"type": "boolean"},
        "next_user_action": {"type": "string"},
        "preview": {"type": "string"},
        "user_visible_preview": {"type": "string"},
        "can_confirm": {"type": "boolean"},
        "diagnostics": _loose_obj(),
    },
    required=[
        "message_to_user",
        "session_id",
        "status",
        "must_show_to_user",
        "wait_for_confirmation",
        "next_user_action",
        "preview",
        "user_visible_preview",
        "can_confirm",
    ],
    additional_properties=True,
)
''',
    '''BOOTSTRAP_PREVIEW_RESPONSE_SCHEMA = _schema_obj(
    {
        "message_to_user": {
            "type": "string",
            "description": "Full preview for inline responses; chunk 0 when has_more_preview_chunks=true. Do not show chunk 0 alone.",
        },
        "session_id": {"type": "string"},
        "status": {"type": "string"},
        "must_show_to_user": {"type": "boolean"},
        "wait_for_confirmation": {"type": "boolean"},
        "next_user_action": {"type": "string"},
        "preview": {"type": "string"},
        "user_visible_preview": {"type": "string"},
        "can_confirm": {"type": "boolean"},
        "preview_id": {"type": "string", "minLength": 1},
        "preview_chars": {"type": "integer", "minimum": 0},
        "preview_chunk_index": {"type": "integer", "minimum": 0},
        "preview_chunk_count": {"type": "integer", "minimum": 1},
        "has_more_preview_chunks": {"type": "boolean"},
        "next_preview_chunk_index": {"type": ["integer", "null"], "minimum": 0},
        "diagnostics": _loose_obj(),
    },
    required=[
        "message_to_user",
        "session_id",
        "status",
        "must_show_to_user",
        "wait_for_confirmation",
        "next_user_action",
        "preview",
        "user_visible_preview",
        "can_confirm",
        "preview_id",
        "preview_chars",
        "preview_chunk_index",
        "preview_chunk_count",
        "has_more_preview_chunks",
        "next_preview_chunk_index",
    ],
    additional_properties=True,
)

BOOTSTRAP_PREVIEW_CHUNK_RESPONSE_SCHEMA = _schema_obj(
    {
        "session_id": {"type": "string"},
        "status": {"type": "string"},
        "preview_id": {"type": "string", "minLength": 1},
        "preview_chars": {"type": "integer", "minimum": 0},
        "chunk_index": {"type": "integer", "minimum": 0},
        "chunk_count": {"type": "integer", "minimum": 1},
        "preview_chunk": {
            "type": "string",
            "description": "One ordered fragment. Concatenate with chunk 0 and every other fragment before showing the preview.",
        },
        "has_more": {"type": "boolean"},
        "next_chunk_index": {"type": ["integer", "null"], "minimum": 0},
        "must_show_to_user": {"type": "boolean"},
        "ready_to_show_full_preview": {"type": "boolean"},
        "can_confirm": {"type": "boolean"},
        "diagnostics": _loose_obj(),
    },
    required=[
        "session_id",
        "status",
        "preview_id",
        "preview_chars",
        "chunk_index",
        "chunk_count",
        "preview_chunk",
        "has_more",
        "next_chunk_index",
        "must_show_to_user",
        "ready_to_show_full_preview",
        "can_confirm",
    ],
    additional_properties=True,
)
''',
)

replace_once(
    "app/novella_openapi_actions.py",
    '                "BootstrapPreviewResponse": BOOTSTRAP_PREVIEW_RESPONSE_SCHEMA,\n',
    '                "BootstrapPreviewResponse": BOOTSTRAP_PREVIEW_RESPONSE_SCHEMA,\n                "BootstrapPreviewChunkResponse": BOOTSTRAP_PREVIEW_CHUNK_RESPONSE_SCHEMA,\n',
)

replace_once(
    "app/novella_openapi_actions.py",
    '                "Use questionnaire, staged bootstrap parts, preview-confirm launch flow, chunked processTurn, "\n',
    '                "Use questionnaire, staged bootstrap parts, chunked preview-confirm launch flow, chunked processTurn, "\n',
)

replace_once(
    "app/novella_openapi_actions.py",
    '''            "/api/v1/sessions/{session_id}/bootstrap-confirm": {
''',
    '''            "/api/v1/sessions/{session_id}/bootstrap-preview-chunk": {
                "get": {
                    "operationId": "getBootstrapPreviewChunk",
                    "summary": (
                        "Get one stored bootstrap preview fragment. Start at chunk_index=1 because preview creation already returned chunk 0. "
                        "Concatenate every fragment before showing anything to the user."
                    ),
                    "parameters": [
                        _session_id_param(),
                        {
                            "name": "chunk_index",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "integer", "minimum": 1},
                            "description": "Next zero-based preview chunk index; start at 1.",
                        },
                        {
                            "name": "preview_id",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string", "minLength": 1},
                            "description": "Exact preview_id returned by the latest preview response.",
                        },
                    ],
                    "responses": {
                        "200": _json_response(
                            "Bootstrap preview chunk",
                            {"$ref": "#/components/schemas/BootstrapPreviewChunkResponse"},
                        ),
                        "404": _json_response("Stored preview not found", _loose_obj()),
                        "409": _json_response("Stale preview_id or preview no longer awaiting review", _loose_obj()),
                        "416": _json_response("Chunk index out of range", _loose_obj()),
                    },
                }
            },
            "/api/v1/sessions/{session_id}/bootstrap-confirm": {
''',
)

for temporary_path in [
    ROOT / "scripts" / "apply_bootstrap_preview_openapi_patch.py",
    ROOT / ".github" / "workflows" / "debug-bootstrap-preview-chunks.yml",
    ROOT / "ci-debug-bootstrap-preview-chunks.txt",
]:
    if temporary_path.exists():
        temporary_path.unlink()
