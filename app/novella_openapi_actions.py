from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request


DEFAULT_PUBLIC_URL = "https://web-production-4310e.up.railway.app"
SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"


def _schema_obj(
    properties: dict[str, Any] | None = None,
    *,
    required: list[str] | None = None,
    additional_properties: bool = False,
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties or {},
        "additionalProperties": additional_properties,
    }
    if required:
        schema["required"] = required
    return schema


def _loose_obj(properties: dict[str, Any] | None = None) -> dict[str, Any]:
    return _schema_obj(properties, additional_properties=True)


def _string_array() -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}}


def _json_response(description: str, schema: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "description": description,
        "content": {
            "application/json": {
                "schema": schema or _loose_obj()
            }
        },
    }


def _request_body(schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "required": True,
        "content": {
            "application/json": {
                "schema": schema
            }
        },
    }


def _session_id_param() -> dict[str, Any]:
    return {
        "name": "session_id",
        "in": "path",
        "required": True,
        "schema": {"type": "string", "minLength": 1},
    }


def _public_base_url(request: Request | None = None) -> str:
    for key in ("PUBLIC_BASE_URL", "RAILWAY_PUBLIC_DOMAIN"):
        value = (os.getenv(key) or "").strip().rstrip("/")
        if value:
            if not value.startswith(("http://", "https://")):
                value = "https://" + value
            return value
    if request is not None:
        return str(request.base_url).rstrip("/")
    return DEFAULT_PUBLIC_URL


def _load_component_schema(filename: str) -> dict[str, Any]:
    schema = json.loads((SCHEMAS_DIR / filename).read_text(encoding="utf-8"))
    schema = deepcopy(schema)
    schema.pop("$schema", None)
    schema.pop("$id", None)
    return schema


CREATE_SESSION_SCHEMA = _schema_obj(
    {
        "title": {"type": ["string", "null"]},
        "genre": {"type": "string", "default": ""},
        "language": {"type": "string", "default": "ru"},
        "tone": {"type": ["string", "null"]},
        "setting_request": {"type": "string", "default": ""},
        "protagonist_request": {"type": "string", "default": ""},
        "romance_request": {"type": ["string", "null"]},
        "rating": {"type": ["string", "null"]},
        "avoid": _string_array(),
        "extra": _loose_obj(),
        "raw_start_text": {"type": ["string", "null"]},
        "mode": {
            "type": "string",
            "enum": ["gpt_actions", "debug_stub"],
            "default": "gpt_actions",
        },
    },
    additional_properties=True,
)

BOOTSTRAP_PREVIEW_SCHEMA = _schema_obj(
    {
        "bootstrap_json": {"$ref": "#/components/schemas/BootstrapPayload"},
    },
    required=["bootstrap_json"],
)

BOOTSTRAP_CONFIRM_SCHEMA = _schema_obj(
    {
        "confirmation_text": {
            "type": "string",
            "minLength": 1,
            "description": "Exact latest user confirmation message.",
        },
    },
    required=["confirmation_text"],
)

TURN_SCHEMA = _schema_obj(
    {
        "player_input": {
            "type": "string",
            "minLength": 1,
            "description": (
                "Exact latest player input. Use '(начать первую сцену)' only "
                "immediately after bootstrap confirmation."
            ),
        },
        "mode": {
            "type": "string",
            "enum": ["gpt_actions", "debug_stub"],
            "default": "gpt_actions",
        },
    },
    required=["player_input"],
)

APPLY_TURN_RESULT_SCHEMA = _schema_obj(
    {
        "turn_id": {
            "type": "string",
            "minLength": 1,
            "description": "Exact turn_id returned by processTurn.",
        },
        "scene_response": {"$ref": "#/components/schemas/SceneResponse"},
        "rendered_text": {
            "type": ["string", "null"],
            "description": "Compatibility fallback for older imported Actions.",
        },
        "proposed_updates": _loose_obj(),
        "safety_checks": _loose_obj(),
        "metadata": _loose_obj({"turn_id": {"type": ["string", "null"]}}),
        "diagnostics": _loose_obj(),
    },
    required=["turn_id", "scene_response"],
    additional_properties=True,
)

CREATE_SESSION_RESPONSE_SCHEMA = _schema_obj(
    {
        "session_id": {"type": ["string", "null"]},
        "status": {"type": "string"},
        "mode": {"type": "string"},
        "bootstrap_prompt": {"type": ["string", "null"]},
        "questionnaire": {"type": ["string", "null"]},
        "files_created": _string_array(),
    },
    required=[
        "session_id",
        "status",
        "mode",
        "bootstrap_prompt",
        "questionnaire",
        "files_created",
    ],
    additional_properties=True,
)

BOOTSTRAP_PREVIEW_RESPONSE_SCHEMA = _schema_obj(
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

BOOTSTRAP_CONFIRM_RESPONSE_SCHEMA = _schema_obj(
    {
        "session_id": {"type": "string"},
        "status": {"type": "string"},
        "committed": {"type": "boolean"},
        "files_created": _string_array(),
    },
    required=["session_id", "status", "committed", "files_created"],
    additional_properties=True,
)

TURN_RESPONSE_SCHEMA = _schema_obj(
    {
        "session_id": {"type": "string"},
        "status": {"type": "string"},
        "scene": {"type": ["string", "null"]},
        "scene_prompt": {"type": ["string", "null"]},
        "scene_prompt_chunk": {"type": ["string", "null"]},
        "prompt_chunk_index": {"type": "integer"},
        "prompt_chunk_count": {"type": "integer", "minimum": 1},
        "has_more_prompt_chunks": {"type": "boolean"},
        "next_prompt_chunk_index": {"type": ["integer", "null"]},
        "turn_id": {"type": ["string", "null"]},
        "expected_turn_number": {"type": ["integer", "null"]},
        "diagnostics": _loose_obj(),
    },
    required=[
        "session_id",
        "status",
        "scene",
        "scene_prompt",
        "scene_prompt_chunk",
        "prompt_chunk_index",
        "prompt_chunk_count",
        "has_more_prompt_chunks",
        "next_prompt_chunk_index",
        "turn_id",
        "expected_turn_number",
        "diagnostics",
    ],
    additional_properties=True,
)

TURN_PROMPT_CHUNK_RESPONSE_SCHEMA = _schema_obj(
    {
        "session_id": {"type": "string"},
        "turn_id": {"type": "string"},
        "chunk_index": {"type": "integer"},
        "chunk_count": {"type": "integer"},
        "scene_prompt_chunk": {"type": "string"},
        "has_more": {"type": "boolean"},
        "next_chunk_index": {"type": ["integer", "null"]},
        "diagnostics": _loose_obj(),
    },
    required=[
        "session_id",
        "turn_id",
        "chunk_index",
        "chunk_count",
        "scene_prompt_chunk",
        "has_more",
    ],
)

DEBUG_SESSION_DUMP_RESPONSE_SCHEMA = _schema_obj(
    {
        "session_id": {"type": "string"},
        "status": {"type": "string"},
        "server": _loose_obj(),
        "session": _loose_obj(),
        "current_state": _loose_obj(),
        "story_plan": _loose_obj(),
        "characters": _loose_obj(),
        "knowledge": _loose_obj(),
        "relationships": _loose_obj(),
        "history": _loose_obj(),
        "pending_turn": _loose_obj(),
        "diagnostics": _loose_obj(),
    },
    required=[
        "session_id",
        "status",
        "server",
        "session",
        "current_state",
        "story_plan",
        "characters",
        "knowledge",
        "relationships",
        "history",
        "pending_turn",
    ],
)

APPLY_TURN_RESULT_RESPONSE_SCHEMA = _schema_obj(
    {
        "session_id": {"type": "string"},
        "status": {"type": "string"},
        "message_to_user": {"type": "string"},
        "rendered_text": {"type": "string"},
        "must_show_to_user": {"type": "boolean"},
        "applied": _loose_obj(),
        "rejected": {"type": "array", "items": _loose_obj()},
        "next_builder_hints": _loose_obj(),
    },
    required=[
        "session_id",
        "status",
        "message_to_user",
        "rendered_text",
        "must_show_to_user",
        "applied",
        "rejected",
        "next_builder_hints",
    ],
    additional_properties=True,
)


def build_openapi_actions(server_url: str | None = None) -> dict[str, Any]:
    url = (server_url or _public_base_url()).rstrip("/")
    generic = _json_response("OK", _loose_obj())
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Romance Novella Generator API",
            "version": "gpt-actions-v9-strict-contract",
            "description": (
                "Custom GPT Actions schema for generated novella sessions. "
                "Use questionnaire, preview-confirm launch flow, chunked processTurn, "
                "then applyTurnResult with the exact turn_id."
            ),
        },
        "servers": [{"url": url}],
        "security": [{"ApiKeyAuth": []}],
        "components": {
            "securitySchemes": {
                "ApiKeyAuth": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-API-Key",
                }
            },
            "schemas": {
                "BootstrapPayload": _load_component_schema(
                    "bootstrap_output.schema.json"
                ),
                "SceneResponse": _load_component_schema(
                    "scene_response.schema.json"
                ),
                "CreateSessionRequest": CREATE_SESSION_SCHEMA,
                "CreateSessionResponse": CREATE_SESSION_RESPONSE_SCHEMA,
                "BootstrapPreviewRequest": BOOTSTRAP_PREVIEW_SCHEMA,
                "BootstrapPreviewResponse": BOOTSTRAP_PREVIEW_RESPONSE_SCHEMA,
                "BootstrapConfirmRequest": BOOTSTRAP_CONFIRM_SCHEMA,
                "BootstrapConfirmResponse": BOOTSTRAP_CONFIRM_RESPONSE_SCHEMA,
                "TurnRequest": TURN_SCHEMA,
                "TurnResponse": TURN_RESPONSE_SCHEMA,
                "TurnPromptChunkResponse": TURN_PROMPT_CHUNK_RESPONSE_SCHEMA,
                "DebugSessionDumpResponse": DEBUG_SESSION_DUMP_RESPONSE_SCHEMA,
                "ApplyTurnResultRequest": APPLY_TURN_RESULT_SCHEMA,
                "ApplyTurnResultResponse": APPLY_TURN_RESULT_RESPONSE_SCHEMA,
            },
        },
        "paths": {
            "/health": {
                "get": {
                    "operationId": "health",
                    "summary": (
                        "Check API health. This is a technical check only; "
                        "do not continue a scene."
                    ),
                    "security": [],
                    "responses": {"200": generic},
                }
            },
            "/api/v1/start-questionnaire": {
                "get": {
                    "operationId": "getStartQuestionnaire",
                    "summary": (
                        "Get the visible start questionnaire when the user "
                        "gave too little setup."
                    ),
                    "responses": {"200": generic},
                }
            },
            "/api/v1/sessions": {
                "post": {
                    "operationId": "createSession",
                    "summary": (
                        "Create a new novella session or return questionnaire "
                        "if setup is too small."
                    ),
                    "requestBody": _request_body(
                        {"$ref": "#/components/schemas/CreateSessionRequest"}
                    ),
                    "responses": {
                        "200": _json_response(
                            "Session created or questionnaire required.",
                            {"$ref": "#/components/schemas/CreateSessionResponse"},
                        )
                    },
                }
            },
            "/api/v1/sessions/{session_id}": {
                "get": {
                    "operationId": "getSession",
                    "summary": "Get one session status by session_id.",
                    "parameters": [_session_id_param()],
                    "responses": {
                        "200": generic,
                        "404": _json_response(
                            "Session not found",
                            _loose_obj(),
                        ),
                    },
                }
            },
            "/api/v1/sessions/{session_id}/debug-dump": {
                "get": {
                    "operationId": "debugSessionDump",
                    "summary": (
                        "Compact technical debug dump. Do not use it for "
                        "normal scene continuation."
                    ),
                    "parameters": [_session_id_param()],
                    "responses": {
                        "200": _json_response(
                            "Debug session dump",
                            {"$ref": "#/components/schemas/DebugSessionDumpResponse"},
                        ),
                        "404": _json_response("Session not found", _loose_obj()),
                        "409": _json_response("Session not active", _loose_obj()),
                    },
                }
            },
            "/api/v1/sessions/{session_id}/bootstrap-preview": {
                "post": {
                    "operationId": "createBootstrapPreview",
                    "summary": (
                        "Validate and save pending bootstrap JSON as a visible "
                        "preview. Do not start the scene."
                    ),
                    "parameters": [_session_id_param()],
                    "requestBody": _request_body(
                        {"$ref": "#/components/schemas/BootstrapPreviewRequest"}
                    ),
                    "responses": {
                        "200": _json_response(
                            "Bootstrap preview created.",
                            {"$ref": "#/components/schemas/BootstrapPreviewResponse"},
                        ),
                        "422": _json_response("Invalid bootstrap JSON", _loose_obj()),
                    },
                }
            },
            "/api/v1/sessions/{session_id}/bootstrap-confirm": {
                "post": {
                    "operationId": "confirmBootstrapPreview",
                    "summary": "Commit pending bootstrap after explicit user confirmation.",
                    "parameters": [_session_id_param()],
                    "requestBody": _request_body(
                        {"$ref": "#/components/schemas/BootstrapConfirmRequest"}
                    ),
                    "responses": {
                        "200": _json_response(
                            "Bootstrap committed.",
                            {"$ref": "#/components/schemas/BootstrapConfirmResponse"},
                        ),
                        "409": _json_response(
                            "Preview not confirmed or wrong session status",
                            _loose_obj(),
                        ),
                    },
                }
            },
            "/api/v1/sessions/{session_id}/turn": {
                "post": {
                    "operationId": "processTurn",
                    "summary": (
                        "Build one compact/chunked scene prompt. Returns the "
                        "pending turn_id; applyTurnResult must use that exact id."
                    ),
                    "parameters": [_session_id_param()],
                    "requestBody": _request_body(
                        {"$ref": "#/components/schemas/TurnRequest"}
                    ),
                    "responses": {
                        "200": _json_response(
                            "Pending turn and first prompt chunk.",
                            {"$ref": "#/components/schemas/TurnResponse"},
                        ),
                        "409": _json_response(
                            "Session inactive or another different turn is pending.",
                            _loose_obj(),
                        ),
                        "422": _json_response("Empty input", _loose_obj()),
                    },
                }
            },
            "/api/v1/sessions/{session_id}/turn-prompt-chunk": {
                "get": {
                    "operationId": "getTurnPromptChunk",
                    "summary": (
                        "Get one stored prompt chunk after processTurn returns "
                        "more than one chunk."
                    ),
                    "parameters": [
                        _session_id_param(),
                        {
                            "name": "turn_id",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string", "minLength": 1},
                            "description": "Exact turn_id returned by processTurn.",
                        },
                        {
                            "name": "chunk_index",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "integer", "minimum": 1},
                            "description": (
                                "Start at 1 because processTurn already returned chunk 0."
                            ),
                        },
                    ],
                    "responses": {
                        "200": _json_response(
                            "Prompt chunk",
                            {"$ref": "#/components/schemas/TurnPromptChunkResponse"},
                        ),
                        "409": _json_response("Missing/stale pending turn", _loose_obj()),
                        "416": _json_response("Chunk index out of range", _loose_obj()),
                    },
                }
            },
            "/api/v1/sessions/{session_id}/apply-turn-result": {
                "post": {
                    "operationId": "applyTurnResult",
                    "summary": (
                        "Validate and atomically save scene_response. Final "
                        "assistant answer must be response.message_to_user only."
                    ),
                    "parameters": [_session_id_param()],
                    "requestBody": _request_body(
                        {"$ref": "#/components/schemas/ApplyTurnResultRequest"}
                    ),
                    "responses": {
                        "200": _json_response(
                            "Turn saved.",
                            {"$ref": "#/components/schemas/ApplyTurnResultResponse"},
                        ),
                        "409": _json_response(
                            "Missing, stale, duplicate or mismatched turn_id",
                            _loose_obj(),
                        ),
                        "422": _json_response("Invalid scene_response", _loose_obj()),
                    },
                }
            },
        },
    }


def install_openapi_actions(app: FastAPI) -> None:
    app.router.routes = [
        route
        for route in app.router.routes
        if getattr(route, "path", None) != "/openapi-actions.json"
    ]

    @app.get("/openapi-actions.json", include_in_schema=False)
    def openapi_actions_route(request: Request) -> dict[str, Any]:
        return build_openapi_actions(_public_base_url(request))

    def custom_openapi() -> dict[str, Any]:
        return build_openapi_actions(_public_base_url(None))

    app.openapi_schema = None
    app.openapi = custom_openapi  # type: ignore[method-assign]
