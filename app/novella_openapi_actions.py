from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, Request


DEFAULT_PUBLIC_URL = "https://web-production-4310e.up.railway.app"


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


def _string_array(description: str = "") -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "array", "items": {"type": "string"}}
    if description:
        schema["description"] = description
    return schema


def _json_response(description: str, schema: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "description": description,
        "content": {
            "application/json": {
                "schema": schema or _loose_obj()
            }
        },
    }


def _request_body(schema: dict[str, Any], required: bool = True) -> dict[str, Any]:
    return {
        "required": required,
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
        "schema": {"type": "string"},
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
        "mode": {"type": "string", "enum": ["gpt_actions", "debug_stub"], "default": "gpt_actions"},
    },
    additional_properties=True,
)

BOOTSTRAP_PREVIEW_SCHEMA = _schema_obj(
    {
        "bootstrap_json": _loose_obj(),
    },
    required=["bootstrap_json"],
)

BOOTSTRAP_CONFIRM_SCHEMA = _schema_obj(
    {
        "confirmation_text": {
            "type": "string",
            "description": "Exact latest user confirmation, e.g. подтверждаю / ок / сохраняй / запускай / начинаем.",
        },
    },
    required=["confirmation_text"],
)

TURN_SCHEMA = _schema_obj(
    {
        "player_input": {
            "type": "string",
            "minLength": 1,
            "description": "Exact latest user/player input. Must not be empty. Use '(начать первую сцену)' only after bootstrap confirmation.",
        },
        "mode": {"type": "string", "enum": ["gpt_actions", "debug_stub"], "default": "gpt_actions"},
    },
    required=["player_input"],
)

APPLY_TURN_RESULT_SCHEMA = _schema_obj(
    {
        "turn_id": {
            "type": ["string", "null"],
            "description": "The turn_id returned by processTurn. Preferred top-level field. If an old Actions import cannot send it here, backend can also bind to the single pending turn after player_input check.",
        },
        "scene_response": _loose_obj(),
    },
    required=["scene_response"],
)


def build_openapi_actions(server_url: str | None = None) -> dict[str, Any]:
    url = (server_url or _public_base_url()).rstrip("/")
    generic = _json_response("OK", _loose_obj())
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Romance Novella Generator API",
            "version": "gpt-actions-v9-openapi-actions",
            "description": (
                "Custom GPT Actions schema for generated novella sessions. "
                "Use preview-confirm launch flow, then processTurn and applyTurnResult."
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
                "CreateSessionRequest": CREATE_SESSION_SCHEMA,
                "BootstrapPreviewRequest": BOOTSTRAP_PREVIEW_SCHEMA,
                "BootstrapConfirmRequest": BOOTSTRAP_CONFIRM_SCHEMA,
                "TurnRequest": TURN_SCHEMA,
                "ApplyTurnResultRequest": APPLY_TURN_RESULT_SCHEMA,
            },
        },
        "paths": {
            "/health": {
                "get": {
                    "operationId": "health",
                    "summary": "Check API health.",
                    "security": [],
                    "responses": {"200": generic},
                }
            },
            "/api/v1/start-questionnaire": {
                "get": {
                    "operationId": "getStartQuestionnaire",
                    "summary": "Get the visible start questionnaire when the user gave too little setup.",
                    "responses": {"200": generic},
                }
            },
            "/api/v1/sessions": {
                "post": {
                    "operationId": "createSession",
                    "summary": "Create a new generated novella session or return questionnaire if setup is too small.",
                    "requestBody": _request_body({"$ref": "#/components/schemas/CreateSessionRequest"}, required=True),
                    "responses": {"200": generic},
                }
            },
            "/api/v1/sessions/{session_id}": {
                "get": {
                    "operationId": "getSession",
                    "summary": "Get one session status by session_id.",
                    "parameters": [_session_id_param()],
                    "responses": {"200": generic, "404": _json_response("Session not found", _loose_obj())},
                }
            },
            "/api/v1/sessions/{session_id}/bootstrap-preview": {
                "post": {
                    "operationId": "createBootstrapPreview",
                    "summary": "Validate and save pending bootstrap JSON as a user-visible preview. Do not start the scene yet.",
                    "parameters": [_session_id_param()],
                    "requestBody": _request_body({"$ref": "#/components/schemas/BootstrapPreviewRequest"}, required=True),
                    "responses": {"200": generic, "422": _json_response("Invalid bootstrap JSON", _loose_obj())},
                }
            },
            "/api/v1/sessions/{session_id}/bootstrap-confirm": {
                "post": {
                    "operationId": "confirmBootstrapPreview",
                    "summary": "Commit pending bootstrap after explicit user confirmation.",
                    "parameters": [_session_id_param()],
                    "requestBody": _request_body({"$ref": "#/components/schemas/BootstrapConfirmRequest"}, required=True),
                    "responses": {"200": generic, "409": _json_response("Preview not confirmed or wrong session status", _loose_obj())},
                }
            },
            "/api/v1/sessions/{session_id}/turn": {
                "post": {
                    "operationId": "processTurn",
                    "summary": "Build compact scene prompt for one player turn. Returns turn_id; applyTurnResult must use it.",
                    "parameters": [_session_id_param()],
                    "requestBody": _request_body({"$ref": "#/components/schemas/TurnRequest"}, required=True),
                    "responses": {"200": generic, "409": _json_response("Session not active", _loose_obj()), "422": _json_response("Empty input", _loose_obj())},
                }
            },
            "/api/v1/sessions/{session_id}/apply-turn-result": {
                "post": {
                    "operationId": "applyTurnResult",
                    "summary": "Validate and save scene_response. Final assistant answer must be response.message_to_user.",
                    "parameters": [_session_id_param()],
                    "requestBody": _request_body({"$ref": "#/components/schemas/ApplyTurnResultRequest"}, required=True),
                    "responses": {"200": generic, "409": _json_response("Missing, stale, duplicate or mismatched turn_id", _loose_obj()), "422": _json_response("Invalid scene_response", _loose_obj())},
                }
            },
        },
    }


def install_openapi_actions(app: FastAPI) -> None:
    app.router.routes = [
        route for route in app.router.routes
        if getattr(route, "path", None) != "/openapi-actions.json"
    ]

    @app.get("/openapi-actions.json", include_in_schema=False)
    def openapi_actions_route(request: Request) -> dict[str, Any]:
        return build_openapi_actions(_public_base_url(request))

    def custom_openapi() -> dict[str, Any]:
        return build_openapi_actions(_public_base_url(None))

    app.openapi_schema = None
    app.openapi = custom_openapi  # type: ignore[method-assign]
