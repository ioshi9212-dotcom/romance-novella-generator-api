from __future__ import annotations

from copy import deepcopy
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


def _load_actions_component_schemas() -> dict[str, Any]:
    # The strict repository schemas remain the backend validator. Custom GPT
    # only needs a small authoring contract; embedding the complete bootstrap
    # and every patch subtype made the imported Action nearly 100 KB and caused
    # malformed/flattened kwargs before requests reached Railway.
    return {"SceneResponse": deepcopy(ACTION_SCENE_RESPONSE_SCHEMA)}


CREATE_SESSION_SCHEMA = _schema_obj(
    {
        "raw_start_text": {
            "type": "string",
            "minLength": 1,
            "description": (
                "The one canonical setup field. Copy the user's complete questionnaire answer verbatim into this string; "
                "do not split it into title, genre, protagonist or other Action kwargs. Partial answers are valid and "
                "the bootstrap generator fills every unspecified detail."
            ),
        },
        "mode": {
            "type": "string",
            "enum": ["gpt_actions", "debug_stub"],
            "default": "gpt_actions",
        },
    },
    required=["raw_start_text"],
    additional_properties=False,
)

SAVE_BOOTSTRAP_PART_SCHEMA = _schema_obj(
    {
        "section": {
            "type": "string",
            "enum": [
                "protagonist", "characters", "relationships", "knowledge",
                "story_plan", "director_bible", "current_state", "npc_state",
                "future_locks", "continuity",
            ],
            "description": "Bootstrap root section to stage.",
        },
        "item_id": {
            "type": ["string", "null"],
            "description": "For map sections, send one entry id. Normal setup uses it once per characters card.",
        },
        "value": {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
            "description": "One complete character card, story_plan, current_state, or authored director_bible matching the same-named BootstrapPayload section. Do not send the full bootstrap here.",
        },
        "delete_fields": {
            "type": "array",
            "items": {"type": "string"},
            "default": [],
            "description": "Explicit dotted field paths to delete after deep merge.",
        },
        "replace": {
            "type": "boolean",
            "default": False,
            "description": "Replace instead of deep merge. Use only for an intentional full replacement.",
        },
    },
    required=["section", "value"],
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


ADVANCE_TIME_SCHEMA = _schema_obj(
    {
        "player_input": {"type": "string", "minLength": 1, "description": "Exact latest user request selecting time skip."},
        "skip_mode": {"type": "string", "enum": ["nearest_event", "duration"], "default": "nearest_event"},
        "unit": {"type": ["string", "null"], "enum": ["hours", "days", "weeks", "months", None]},
        "amount": {"type": ["integer", "null"], "minimum": 1, "maximum": 365},
    },
    required=["player_input"],
)

SCENE_HEADER_INPUT_SCHEMA = _schema_obj(
    {
        key: {"type": "string", "minLength": 1}
        for key in (
            "story_title",
            "date",
            "time",
            "location",
            "weather",
            "scene_state",
            "player_name",
            "visible_state",
            "outfit",
            "inventory",
        )
    },
    required=[
        "story_title",
        "date",
        "time",
        "location",
        "weather",
        "scene_state",
        "player_name",
        "visible_state",
        "outfit",
        "inventory",
    ],
)

SCENE_OPTIONS_INPUT_SCHEMA = _schema_obj(
    {
        key: {
            "type": "array",
            "minItems": 3,
            "maxItems": 3,
            "items": {"type": "string", "minLength": 1},
        }
        for key in ("actions", "dialogue", "thoughts")
    },
    required=["actions", "dialogue", "thoughts"],
)

SCENE_STATUS_INPUT_SCHEMA = _schema_obj(
    {
        "hunger": {"type": "string"},
        "fatigue": {"type": "string"},
        "injuries": {"type": "string"},
        "emotional_state": {"type": "string"},
        "skills": {"type": "string"},
        "custom": {
            "type": "array",
            "minItems": 2,
            "maxItems": 2,
            "items": _schema_obj(
                {
                    "id": {"type": "string", "enum": ["story_slot_1", "story_slot_2"]},
                    "label": {"type": "string"},
                    "value": {"type": "string"},
                },
                required=["id", "label", "value"],
            ),
        },
    },
    required=["hunger", "fatigue", "injuries", "emotional_state", "skills", "custom"],
)

SCENE_INPUT_SCHEMA = _schema_obj(
    {
        "header": SCENE_HEADER_INPUT_SCHEMA,
        "body": {
            "type": "string",
            "minLength": 500,
            "description": "Complete prose and dialogue. Railway builds the visible rendered scene from this body; do not send rendered_text.",
        },
        "player_options": SCENE_OPTIONS_INPUT_SCHEMA,
        "status_panel": SCENE_STATUS_INPUT_SCHEMA,
        "relationships_panel": {
            "type": "array",
            "items": _schema_obj(
                {
                    "pair_id": {"type": ["string", "null"]},
                    "label": {"type": "string"},
                    "value": {"type": "string"},
                },
                required=["label", "value"],
            ),
        },
    },
    required=["header", "body", "player_options", "status_panel", "relationships_panel"],
)

PROPOSED_UPDATES_INPUT_SCHEMA = _schema_obj(
    {
        "scene_state_patch": _loose_obj(),
        "continuity_patch": _loose_obj(),
        "relationship_patches": {"type": "array", "items": _loose_obj()},
        "knowledge_patches": {"type": "array", "items": _loose_obj()},
        "npc_state_patches": {"type": "array", "items": _loose_obj()},
        "director_bible_patches": {
            "oneOf": [
                _loose_obj(),
                {"type": "array", "maxItems": 0, "items": _loose_obj()},
            ],
            "description": "Use an object; use {} when there are no director updates. Legacy empty [] is tolerated.",
        },
        "new_or_updated_characters": {"type": "array", "items": _loose_obj()},
    },
    required=[
        "scene_state_patch",
        "continuity_patch",
        "relationship_patches",
        "knowledge_patches",
        "npc_state_patches",
        "director_bible_patches",
        "new_or_updated_characters",
    ],
)

SAFETY_CHECKS_INPUT_SCHEMA = _schema_obj(
    {
        key: {"const": True}
        for key in (
            "used_only_loaded_characters",
            "respected_knowledge_boundaries",
            "no_hidden_future_reveal",
            "no_major_player_character_choice",
            "respected_player_input_order",
            "showed_only_scene_relationships",
            "header_has_no_focus_or_active_list",
        )
    }
    | {"notes": {"type": "array", "items": {"type": "string"}}},
    required=[
        "used_only_loaded_characters",
        "respected_knowledge_boundaries",
        "no_hidden_future_reveal",
        "no_major_player_character_choice",
        "respected_player_input_order",
        "showed_only_scene_relationships",
        "header_has_no_focus_or_active_list",
    ],
)

ACTION_SCENE_RESPONSE_SCHEMA = _schema_obj(
    {
        "response_version": {"const": "novella.scene_response.v1"},
        "player_input": {"type": "string", "minLength": 1},
        "scene": SCENE_INPUT_SCHEMA,
        "summary": {"type": "string", "minLength": 1},
        "important_facts": {"type": "array", "items": {"type": "string"}},
        "witnesses": {"type": "array", "items": {"oneOf": [{"type": "string"}, _loose_obj()]}},
        "proposed_updates": PROPOSED_UPDATES_INPUT_SCHEMA,
        "safety_checks": SAFETY_CHECKS_INPUT_SCHEMA,
        "time_skip_result": _loose_obj(),
    },
    required=[
        "response_version",
        "player_input",
        "scene",
        "summary",
        "important_facts",
        "witnesses",
        "proposed_updates",
        "safety_checks",
    ],
)

APPLY_TURN_RESULT_SCHEMA = _schema_obj(
    {
        "turn_id": {
            "type": "string",
            "minLength": 1,
            "description": "Exact turn_id returned by processTurn.",
        },
        **deepcopy(ACTION_SCENE_RESPONSE_SCHEMA["properties"]),
    },
    required=["turn_id", *ACTION_SCENE_RESPONSE_SCHEMA["required"]],
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
        "repair_required": {
            "type": "boolean",
            "description": "When true, do not show message_to_user. Apply repair_plan and retry the action in diagnostics.retry_action.",
        },
        "repair_errors": {"type": "array", "items": {"type": "string"}},
        "repair_plan": _loose_obj(),
        "repair_prompt": {"type": ["string", "null"]},
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
        "repair_required",
        "repair_errors",
        "repair_plan",
        "repair_prompt",
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

SAVE_BOOTSTRAP_PART_RESPONSE_SCHEMA = _schema_obj(
    {
        "session_id": {"type": "string"},
        "status": {"type": "string"},
        "section": {"type": "string"},
        "item_id": {"type": ["string", "null"]},
        "stored": {"type": "boolean"},
        "progress": _loose_obj(),
    },
    required=["session_id", "status", "section", "item_id", "stored", "progress"],
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
        "turn_id": {"type": "string"},
        "message_to_user": {"type": "string"},
        "must_show_to_user": {"type": "boolean"},
        "replayed": {"type": "boolean"},
        "saved_turn_number": {"type": "integer", "minimum": 0},
        "applied": _loose_obj(),
        "rejected": {"type": "array", "items": _loose_obj()},
        "next_builder_hints": _loose_obj(),
    },
    required=[
        "session_id",
        "status",
        "turn_id",
        "message_to_user",
        "must_show_to_user",
        "replayed",
        "saved_turn_number",
        "applied",
        "rejected",
        "next_builder_hints",
    ],
    additional_properties=True,
)

LAST_SCENE_RESPONSE_SCHEMA = _schema_obj(
    {
        "session_id": {"type": "string"},
        "available": {"type": "boolean"},
        "turn_id": {"type": ["string", "null"]},
        "saved_turn_number": {"type": ["integer", "null"], "minimum": 0},
        "message_to_user": {"type": "string"},
        "must_show_to_user": {"type": "boolean"},
        "recovered_from": {"type": "string"},
        "summary": {"type": ["string", "null"]},
        "body_excerpt": {"type": ["string", "null"]},
    },
    required=[
        "session_id",
        "available",
        "message_to_user",
        "must_show_to_user",
        "recovered_from",
    ],
)


def build_openapi_actions(server_url: str | None = None) -> dict[str, Any]:
    url = (server_url or _public_base_url()).rstrip("/")
    generic = _json_response("OK", _loose_obj())
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Romance Novella Generator API",
            "version": "gpt-actions-v9.1-resilient-turn-delivery",
            "description": (
                "Custom GPT Actions schema for generated novella sessions. "
                "Use questionnaire, staged bootstrap parts, chunked preview-confirm launch flow, chunked processTurn, "
                "then flat applyTurnResult with the exact turn_id. Railway renders and retains the visible scene; "
                "getLastScene recovers a lost Action response without creating a new turn."
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
                **_load_actions_component_schemas(),
                "CreateSessionRequest": CREATE_SESSION_SCHEMA,
                "CreateSessionResponse": CREATE_SESSION_RESPONSE_SCHEMA,
                "BootstrapPreviewResponse": BOOTSTRAP_PREVIEW_RESPONSE_SCHEMA,
                "BootstrapPreviewChunkResponse": BOOTSTRAP_PREVIEW_CHUNK_RESPONSE_SCHEMA,
                "SaveBootstrapPartRequest": SAVE_BOOTSTRAP_PART_SCHEMA,
                "SaveBootstrapPartResponse": SAVE_BOOTSTRAP_PART_RESPONSE_SCHEMA,
                "BootstrapConfirmRequest": BOOTSTRAP_CONFIRM_SCHEMA,
                "BootstrapConfirmResponse": BOOTSTRAP_CONFIRM_RESPONSE_SCHEMA,
                "TurnRequest": TURN_SCHEMA,
                "AdvanceTimeRequest": ADVANCE_TIME_SCHEMA,
                "TurnResponse": TURN_RESPONSE_SCHEMA,
                "TurnPromptChunkResponse": TURN_PROMPT_CHUNK_RESPONSE_SCHEMA,
                "DebugSessionDumpResponse": DEBUG_SESSION_DUMP_RESPONSE_SCHEMA,
                "ApplyTurnResultRequest": APPLY_TURN_RESULT_SCHEMA,
                "ApplyTurnResultResponse": APPLY_TURN_RESULT_RESPONSE_SCHEMA,
                "LastSceneResponse": LAST_SCENE_RESPONSE_SCHEMA,
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
                        "Create a session from exactly raw_start_text plus optional mode. "
                        "Never split the questionnaire into title/genre/character kwargs."
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
                        "Compact technical debug dump for bootstrap_pending, "
                        "bootstrap_review_pending or active. Do not use it for normal scene continuation."
                    ),
                    "parameters": [_session_id_param()],
                    "responses": {
                        "200": _json_response(
                            "Debug session dump",
                            {"$ref": "#/components/schemas/DebugSessionDumpResponse"},
                        ),
                        "404": _json_response("Session not found", _loose_obj()),
                        "409": _json_response("Session status is not debuggable", _loose_obj()),
                    },
                }
            },
            "/api/v1/sessions/{session_id}/bootstrap-part": {
                "post": {
                    "operationId": "saveBootstrapPart",
                    "summary": "Stage one complete character card or one authorial section. Normal flow writes characters, story_plan, current_state and director_bible; technical runtime sections are derived.",
                    "parameters": [_session_id_param()],
                    "requestBody": _request_body({"$ref": "#/components/schemas/SaveBootstrapPartRequest"}),
                    "responses": {
                        "200": _json_response("Bootstrap part stored.", {"$ref": "#/components/schemas/SaveBootstrapPartResponse"}),
                        "409": _json_response("Session cannot accept bootstrap parts.", _loose_obj()),
                        "422": _json_response("Invalid bootstrap part.", _loose_obj()),
                    },
                }
            },
            "/api/v1/sessions/{session_id}/bootstrap-preview-finalize": {
                "post": {
                    "operationId": "finalizeBootstrapPreview",
                    "summary": (
                        "Preserve authored characters/story/director state, build missing technical runtime state, then create the visible preview. "
                        "If status=bootstrap_repair_required, "
                        "do not show the response or ask the user again: apply repair_plan with saveBootstrapPart and retry."
                    ),
                    "parameters": [_session_id_param()],
                    "responses": {
                        "200": _json_response("Bootstrap preview created from staged parts.", {"$ref": "#/components/schemas/BootstrapPreviewResponse"}),
                        "409": _json_response("Staged bootstrap is incomplete or session status is wrong.", _loose_obj()),
                        "422": _json_response("Assembled bootstrap is invalid.", _loose_obj()),
                    },
                }
            },
            "/api/v1/sessions/{session_id}/bootstrap-preview-chunk": {
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
            "/api/v1/sessions/{session_id}/advance-time": {
                "post": {
                    "operationId": "advanceTime",
                    "summary": "Create a guarded time-skip prompt only after the scene saved a natural pause.",
                    "parameters": [_session_id_param()],
                    "requestBody": _request_body({"$ref": "#/components/schemas/AdvanceTimeRequest"}),
                    "responses": {
                        "200": _json_response("Pending time-skip turn and first prompt chunk.", {"$ref": "#/components/schemas/TurnResponse"}),
                        "409": _json_response("Time skip blocked or another turn is pending.", _loose_obj()),
                        "422": _json_response("Invalid time skip request.", _loose_obj()),
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
                        "Validate and atomically save flat scene fields. Do not send rendered_text: Railway builds it. "
                        "Repeating the same turn_id safely replays the saved response; final assistant answer is message_to_user."
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
            "/api/v1/sessions/{session_id}/last-scene": {
                "get": {
                    "operationId": "getLastScene",
                    "summary": (
                        "Recover the most recently saved visible scene after a missing/oversized Action response. "
                        "This never creates a turn or changes state. Show message_to_user only when available=true."
                    ),
                    "parameters": [_session_id_param()],
                    "responses": {
                        "200": _json_response(
                            "Last saved visible scene or compact legacy recovery information.",
                            {"$ref": "#/components/schemas/LastSceneResponse"},
                        ),
                        "404": _json_response("Session not found", _loose_obj()),
                        "409": _json_response("Session is not active", _loose_obj()),
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
