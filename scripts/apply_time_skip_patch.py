from __future__ import annotations

from pathlib import Path
import json


ROOT = Path(__file__).resolve().parent.parent


def replace_once(path: str, old: str, new: str) -> None:
    file_path = ROOT / path
    text = file_path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Pattern not found in {path}: {old[:140]!r}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


def insert_after(path: str, anchor: str, addition: str) -> None:
    replace_once(path, anchor, anchor + addition)


# app/director_bible.py
insert_after(
    "app/director_bible.py",
    'CONFLICT_STATUSES = {"active", "escalated", "cooling", "resolved", "dormant"}\n',
    'TIME_SKIP_UNITS = {"hours", "days", "weeks", "months"}\n',
)
insert_after(
    "app/director_bible.py",
    "def _integer(value: Any, fallback: int, minimum: int = 0, maximum: int = 9999) -> int:\n    try:\n        number = int(value)\n    except (TypeError, ValueError):\n        number = fallback\n    return max(minimum, min(maximum, number))\n",
    '''\n\ndef _normalise_time_flow(value: Any, story_plan: dict[str, Any]) -> dict[str, Any]:\n    source = deepcopy(value) if isinstance(value, dict) else {}\n    allowed_units = [unit for unit in _string_list(source.get("allowed_units"), 4) if unit in TIME_SKIP_UNITS]\n    if not allowed_units:\n        allowed_units = ["hours", "days", "weeks"]\n    maxima = source.get("max_amounts") if isinstance(source.get("max_amounts"), dict) else {}\n    return {\n        **source,\n        "current_period": _text(source.get("current_period") or story_plan.get("current_story_position"), "early_story"),\n        "default_mode": _text(source.get("default_mode"), "nearest_event"),\n        "allow_nearest_event": source.get("allow_nearest_event") is not False,\n        "allowed_units": allowed_units,\n        "max_amounts": {\n            "hours": _integer(maxima.get("hours"), 24, 1, 365),\n            "days": _integer(maxima.get("days"), 14, 1, 365),\n            "weeks": _integer(maxima.get("weeks"), 4, 1, 52),\n            "months": _integer(maxima.get("months"), 1, 1, 12),\n        },\n        "last_skip": source.get("last_skip") if isinstance(source.get("last_skip"), dict) else None,\n    }\n''',
)
replace_once(
    "app/director_bible.py",
    '            "time_hint": "в текущей или ближайшей сцене",\n',
    '            "time_hint": "в текущей или ближайшей сцене",\n            "skip_unit": "hours",\n            "skip_amount": 1,\n',
)
replace_once(
    "app/director_bible.py",
    '            "time_hint": "через несколько сцен или после естественной паузы",\n',
    '            "time_hint": "через несколько сцен или после естественной паузы",\n            "skip_unit": "days",\n            "skip_amount": 2,\n',
)
replace_once(
    "app/director_bible.py",
    '            "time_hint": "когда текущая сцена достигнет естественной точки перехода",\n',
    '            "time_hint": "когда текущая сцена достигнет естественной точки перехода",\n            "skip_unit": "weeks",\n            "skip_amount": 1,\n',
)
replace_once(
    "app/director_bible.py",
    '''def _normalise_event(item: dict[str, Any], item_id: str, index: int) -> dict[str, Any]:\n    status = _text(item.get("status"), "planned")\n    return {\n''',
    '''def _normalise_event(item: dict[str, Any], item_id: str, index: int) -> dict[str, Any]:\n    status = _text(item.get("status"), "planned")\n    skip_unit = _text(item.get("skip_unit"), "days")\n    if skip_unit not in TIME_SKIP_UNITS:\n        skip_unit = "days"\n    return {\n''',
)
replace_once(
    "app/director_bible.py",
    '        "time_hint": _text(item.get("time_hint"), "при первой естественной возможности"),\n',
    '        "time_hint": _text(item.get("time_hint"), "при первой естественной возможности"),\n        "skip_unit": skip_unit,\n        "skip_amount": _integer(item.get("skip_amount"), max(1, index), 0, 365),\n',
)
replace_once(
    "app/director_bible.py",
    '        "time_anchors": _list(source.get("time_anchors")),\n',
    '        "time_anchors": _list(source.get("time_anchors")),\n        "time_flow": _normalise_time_flow(source.get("time_flow"), story_plan),\n',
)
replace_once(
    "app/director_bible.py",
    '        "pacing": bible.get("pacing", {}),\n',
    '        "pacing": bible.get("pacing", {}),\n        "time_flow": bible.get("time_flow", {}),\n',
)
replace_once(
    "app/director_bible.py",
    '("id", "title", "status", "priority", "earliest_turn", "latest_turn", "conditions", "participants", "purpose", "scene_pressure", "next_if_ignored", "time_hint")',
    '("id", "title", "status", "priority", "earliest_turn", "latest_turn", "conditions", "participants", "purpose", "scene_pressure", "next_if_ignored", "time_hint", "skip_unit", "skip_amount")',
)

# app/bootstrap_normalizer.py
replace_once(
    "app/bootstrap_normalizer.py",
    "from app.director_bible import prepare_director_bible\n",
    "from app.director_bible import prepare_director_bible\nfrom app.time_skip import prepare_time_skip_state\n",
)
replace_once(
    "app/bootstrap_normalizer.py",
    "    prepare_director_bible(normalized)\n    return normalized\n",
    "    prepare_director_bible(normalized)\n    prepare_time_skip_state(normalized)\n    return normalized\n",
)

# app/bootstrap_setup.py
replace_once(
    "app/bootstrap_setup.py",
    "- event_queue: минимум три ближайших события с priority, earliest/latest turn, conditions, participants, purpose, scene_pressure, next_if_ignored и time_hint;\n- time_anchors, continuity_truths, future_consequences и pacing.\n",
    "- event_queue: минимум три ближайших события с priority, earliest/latest turn, conditions, participants, purpose, scene_pressure, next_if_ignored, time_hint, skip_unit и skip_amount;\n- time_anchors, continuity_truths, future_consequences, pacing и time_flow с allowed_units/max_amounts.\n",
)
replace_once(
    "app/bootstrap_setup.py",
    "Заполни конкретно date, time, location, weather, scene_state, outfit, inventory, nearby_items, environment и status. В active/nearby только реально доступные стартовые персонажи.\n",
    "Заполни конкретно date, time, location, weather, scene_state, outfit, inventory, nearby_items, environment и status. В active/nearby только реально доступные стартовые персонажи. time_skip_control на старте: allowed=false, blockers=[\"opening_scene_not_played\"].\n",
)

# app/models.py
replace_once(
    "app/models.py",
    'SessionMode = Literal["debug_stub", "gpt_actions"]\n',
    'SessionMode = Literal["debug_stub", "gpt_actions"]\nTimeSkipMode = Literal["nearest_event", "duration"]\nTimeSkipUnit = Literal["hours", "days", "weeks", "months"]\n',
)
insert_after(
    "app/models.py",
    '''class TurnRequest(BaseModel):\n    player_input: str = Field(..., min_length=1, description="Exact latest player input. Whitespace-only values are rejected by the route.")\n    mode: SessionMode = "gpt_actions"\n''',
    '''\n\nclass AdvanceTimeRequest(BaseModel):\n    player_input: str = Field(..., min_length=1, description="Exact latest user request that selected time skip.")\n    skip_mode: TimeSkipMode = "nearest_event"\n    unit: TimeSkipUnit | None = None\n    amount: int | None = Field(default=None, ge=1, le=365)\n''',
)

# app/scene_contract_builder.py
replace_once(
    "app/scene_contract_builder.py",
    '            "environment": current_state.get("environment", {}),\n            "status": status,\n',
    '            "environment": current_state.get("environment", {}),\n            "time_skip_control": current_state.get("time_skip_control", {}),\n            "status": status,\n',
)

# app/state_updater.py
replace_once(
    "app/state_updater.py",
    'for key in ["date", "time", "location", "weather", "scene_state", "outfit", "inventory", "nearby_items", "scene_goal", "active_character_ids", "nearby_character_ids", "environment"]:',
    'for key in ["date", "time", "location", "weather", "scene_state", "outfit", "inventory", "nearby_items", "scene_goal", "active_character_ids", "nearby_character_ids", "environment", "time_skip_control"]:',
)

# app/turn_processor.py
replace_once(
    "app/turn_processor.py",
    "from app.scene_rules_compiler import compile_scene_rules, scene_rules_diagnostics\n",
    "from app.scene_rules_compiler import compile_scene_rules, scene_rules_diagnostics\nfrom app.time_skip import build_time_skip_contract\n",
)
replace_once(
    "app/turn_processor.py",
    '        "director_guidance": _compact_dict(contract.get("director_guidance", {}) if isinstance(contract.get("director_guidance"), dict) else {}, 900),\n',
    '        "director_guidance": _compact_dict(contract.get("director_guidance", {}) if isinstance(contract.get("director_guidance"), dict) else {}, 900),\n        "time_skip_request": _compact_dict(contract.get("time_skip_request", {}) if isinstance(contract.get("time_skip_request"), dict) else {}, 900),\n',
)
insert_after(
    "app/turn_processor.py",
    '''def process_turn_gpt_actions(bundle: dict[str, Any], player_input: str) -> dict[str, Any]:\n    contract = build_scene_contract(bundle, player_input=player_input)\n    prompt = build_scene_prompt(contract)\n    rules_diagnostics = scene_rules_diagnostics()\n    return {\n        "status": "gpt_actions_prompt_ready",\n        "scene": None,\n        "scene_prompt": prompt,\n        "diagnostics": {\n            "loaded_character_count": len(contract.get("loaded_characters", [])),\n            "loaded_relationship_count": len(contract.get("loaded_relationships", [])),\n            "visible_relationship_pair_ids": contract.get("visible_relationship_pair_ids", []),\n            "compact_prompt_chars": len(prompt),\n            "scene_rules": rules_diagnostics,\n            "next_required_action": "generate scene_response internally, call applyTurnResult, then show response.message_to_user",\n        },\n    }\n''',
    '''\n\ndef process_time_skip_gpt_actions(\n    bundle: dict[str, Any],\n    player_input: str,\n    *,\n    skip_mode: str,\n    unit: str | None = None,\n    amount: int | None = None,\n) -> dict[str, Any]:\n    contract, assessment = build_time_skip_contract(\n        bundle,\n        player_input=player_input,\n        mode=skip_mode,\n        unit=unit,\n        amount=amount,\n    )\n    prompt = build_scene_prompt(contract)\n    return {\n        "status": "time_skip_prompt_ready",\n        "scene": None,\n        "scene_prompt": prompt,\n        "time_skip_request": {\n            "mode": skip_mode,\n            "unit": assessment.get("unit"),\n            "amount": assessment.get("amount"),\n            "target_event": assessment.get("target_event"),\n            "from_frame": {\n                "date": (bundle.get("current_state") or {}).get("date"),\n                "time": (bundle.get("current_state") or {}).get("time"),\n                "location": (bundle.get("current_state") or {}).get("location"),\n            },\n        },\n        "diagnostics": {\n            "turn_kind": "time_skip",\n            "target_event_id": (assessment.get("target_event") or {}).get("id"),\n            "compact_prompt_chars": len(prompt),\n            "scene_rules": scene_rules_diagnostics(),\n            "next_required_action": "generate time-skip scene_response, call applyTurnResult, then show response.message_to_user",\n        },\n    }\n''',
)

# app/scene_rules_compiler.py
replace_once(
    "app/scene_rules_compiler.py",
    '''    RuleSource(\n        "SCENE_FORMAT",\n        "prompts/scene_format_rules.md",\n        ("rendered_text", "ровно 3", "relationships_panel", "proposed_updates"),\n    ),\n''',
    '''    RuleSource(\n        "TIME_SKIP",\n        "rules/time_skip_rules.md",\n        ("time_skip_control", "advanceTime", "time_skip_result", "event_queue"),\n    ),\n    RuleSource(\n        "SCENE_FORMAT",\n        "prompts/scene_format_rules.md",\n        ("rendered_text", "ровно 3", "relationships_panel", "proposed_updates"),\n    ),\n''',
)

# app/main.py
replace_once(
    "app/main.py",
    "from app.models import ApplyTurnResultRequest, ApplyTurnResultResponse, BootstrapPreviewRequest, BootstrapPreviewResponse, BootstrapConfirmRequest, BootstrapConfirmResponse, CreateSessionRequest, CreateSessionResponse, DebugSessionDumpResponse, TurnPromptChunkResponse, TurnRequest, TurnResponse\n",
    "from app.models import AdvanceTimeRequest, ApplyTurnResultRequest, ApplyTurnResultResponse, BootstrapPreviewRequest, BootstrapPreviewResponse, BootstrapConfirmRequest, BootstrapConfirmResponse, CreateSessionRequest, CreateSessionResponse, DebugSessionDumpResponse, TurnPromptChunkResponse, TurnRequest, TurnResponse\n",
)
replace_once(
    "app/main.py",
    "from app.turn_processor import process_turn_debug_stub, process_turn_gpt_actions\n",
    "from app.turn_processor import process_time_skip_gpt_actions, process_turn_debug_stub, process_turn_gpt_actions\nfrom app.time_skip import assess_time_skip, record_time_skip_result, validate_time_skip_scene_response\n",
)
replace_once(
    "app/main.py",
    'def _save_pending_turn(manager: SessionManager, session_id: str, player_input: str, expected_turn_number: int) -> dict[str, Any]:\n',
    'def _save_pending_turn(manager: SessionManager, session_id: str, player_input: str, expected_turn_number: int, *, turn_kind: str = "normal", metadata: dict[str, Any] | None = None) -> dict[str, Any]:\n',
)
replace_once(
    "app/main.py",
    '        "created_at": now_iso(),\n    }\n',
    '        "created_at": now_iso(),\n        "turn_kind": turn_kind,\n        **(metadata or {}),\n    }\n',
)
replace_once(
    "app/main.py",
    '            "expected_turn_number": pending.get("expected_turn_number"),\n',
    '            "expected_turn_number": pending.get("expected_turn_number"),\n            "turn_kind": pending.get("turn_kind", "normal"),\n',
)
insert_after(
    "app/main.py",
    '''def _process_turn_locked(manager: SessionManager, session_id: str, request: TurnRequest, player_input: str, bundle: dict[str, Any]) -> dict:\n''',
    '',
)
# Add advance helper immediately before health route.
replace_once(
    "app/main.py",
    '''    return _pending_turn_response(pending, session_id)\n\n\n@app.get("/health", operation_id="health")\n''',
    '''    return _pending_turn_response(pending, session_id)\n\n\ndef _advance_time_locked(manager: SessionManager, session_id: str, request: AdvanceTimeRequest, player_input: str, bundle: dict[str, Any]) -> dict:\n    expected_turn_number = int(((bundle.get("current_state") or {}).get("turn_number", 0)) or 0) + 1\n    assessment = assess_time_skip(\n        bundle,\n        mode=request.skip_mode,\n        unit=request.unit,\n        amount=request.amount,\n    )\n    if not assessment["allowed"]:\n        control = assessment.get("control") or {}\n        raise HTTPException(\n            status_code=409,\n            detail={\n                "code": "time_skip_blocked",\n                "reason": control.get("reason"),\n                "blockers": assessment.get("blockers", []),\n            },\n        )\n\n    request_fingerprint = _hash_text(json.dumps({\n        "player_input": player_input,\n        "skip_mode": request.skip_mode,\n        "unit": request.unit,\n        "amount": request.amount,\n    }, ensure_ascii=False, sort_keys=True))\n    existing_pending = _load_pending_turn(manager, session_id)\n    if existing_pending.get("status") == "pending":\n        same_request = existing_pending.get("time_skip_request_sha256") == request_fingerprint\n        same_turn = int(existing_pending.get("expected_turn_number") or 0) == expected_turn_number\n        if same_request and same_turn and existing_pending.get("turn_kind") == "time_skip":\n            if isinstance(existing_pending.get("prompt_chunks"), list) and existing_pending.get("prompt_chunks"):\n                return _pending_turn_response(existing_pending, session_id)\n        raise HTTPException(status_code=409, detail="Another turn is still pending. Apply it before advancing time.")\n\n    generated = process_time_skip_gpt_actions(\n        bundle,\n        player_input,\n        skip_mode=request.skip_mode,\n        unit=request.unit,\n        amount=request.amount,\n    )\n    pending = _save_pending_turn(\n        manager,\n        session_id,\n        player_input,\n        expected_turn_number,\n        turn_kind="time_skip",\n        metadata={\n            "time_skip_request_sha256": request_fingerprint,\n            "time_skip_request": generated.get("time_skip_request", {}),\n        },\n    )\n    pending = _store_prompt_chunks(\n        manager,\n        session_id,\n        pending,\n        generated["scene_prompt"],\n        turn_status=generated["status"],\n        turn_diagnostics=generated["diagnostics"],\n    )\n    return _pending_turn_response(pending, session_id)\n\n\n@app.get("/health", operation_id="health")\n''',
)
replace_once(
    "app/main.py",
    '''@app.get("/api/v1/sessions/{session_id}/turn-prompt-chunk", response_model=TurnPromptChunkResponse, dependencies=[Depends(require_api_key)], operation_id="getTurnPromptChunk")\n''',
    '''@app.post("/api/v1/sessions/{session_id}/advance-time", response_model=TurnResponse, dependencies=[Depends(require_api_key)], operation_id="advanceTime")\ndef advance_time(session_id: str, request: AdvanceTimeRequest) -> dict:\n    player_input = (request.player_input or "").strip()\n    if not player_input:\n        raise HTTPException(status_code=422, detail="player_input is empty; time skip must come from the latest user request.")\n    if request.skip_mode == "duration" and (request.unit is None or request.amount is None):\n        raise HTTPException(status_code=422, detail="duration time skip requires unit and amount.")\n\n    manager = SessionManager()\n    try:\n        with _session_request_context(manager, session_id):\n            bundle = manager.get_memory(session_id)\n            _require_active_session(bundle, "advancing time")\n            return _advance_time_locked(manager, session_id, request, player_input, bundle)\n    except FileNotFoundError as exc:\n        raise HTTPException(status_code=404, detail=str(exc))\n\n\n@app.get("/api/v1/sessions/{session_id}/turn-prompt-chunk", response_model=TurnPromptChunkResponse, dependencies=[Depends(require_api_key)], operation_id="getTurnPromptChunk")\n''',
)
replace_once(
    "app/main.py",
    '            errors = validate_scene_response(normalized_scene_response)\n',
    '            errors = validate_scene_response(normalized_scene_response)\n            errors.extend(validate_time_skip_scene_response(pending, normalized_scene_response, bundle))\n',
)
replace_once(
    "app/main.py",
    '''            result = apply_director_bible_patches(\n                manager.storage,\n                session_id,\n                normalized_scene_response,\n                bundle,\n                result,\n            )\n            _mark_pending_turn_applied(manager, session_id, pending)\n''',
    '''            result = apply_director_bible_patches(\n                manager.storage,\n                session_id,\n                normalized_scene_response,\n                bundle,\n                result,\n            )\n            result = record_time_skip_result(\n                manager.storage,\n                session_id,\n                pending,\n                normalized_scene_response,\n                bundle,\n                result,\n            )\n            _mark_pending_turn_applied(manager, session_id, pending)\n''',
)
replace_once(
    "app/main.py",
    'detail="No pending turn. Call processTurn before applyTurnResult."',
    'detail="No pending turn. Call processTurn or advanceTime before applyTurnResult."',
)

# app/novella_openapi_actions.py
insert_after(
    "app/novella_openapi_actions.py",
    '''TURN_SCHEMA = _schema_obj(\n    {\n        "player_input": {\n            "type": "string",\n            "minLength": 1,\n            "description": (\n                "Exact latest player input. Use '(начать первую сцену)' only "\n                "immediately after bootstrap confirmation."\n            ),\n        },\n        "mode": {\n            "type": "string",\n            "enum": ["gpt_actions", "debug_stub"],\n            "default": "gpt_actions",\n        },\n    },\n    required=["player_input"],\n)\n''',
    '''\n\nADVANCE_TIME_SCHEMA = _schema_obj(\n    {\n        "player_input": {"type": "string", "minLength": 1, "description": "Exact latest user request selecting time skip."},\n        "skip_mode": {"type": "string", "enum": ["nearest_event", "duration"], "default": "nearest_event"},\n        "unit": {"type": ["string", "null"], "enum": ["hours", "days", "weeks", "months", None]},\n        "amount": {"type": ["integer", "null"], "minimum": 1, "maximum": 365},\n    },\n    required=["player_input"],\n)\n''',
)
replace_once(
    "app/novella_openapi_actions.py",
    '                "TurnRequest": TURN_SCHEMA,\n                "TurnResponse": TURN_RESPONSE_SCHEMA,\n',
    '                "TurnRequest": TURN_SCHEMA,\n                "AdvanceTimeRequest": ADVANCE_TIME_SCHEMA,\n                "TurnResponse": TURN_RESPONSE_SCHEMA,\n',
)
replace_once(
    "app/novella_openapi_actions.py",
    '''            "/api/v1/sessions/{session_id}/turn-prompt-chunk": {\n''',
    '''            "/api/v1/sessions/{session_id}/advance-time": {\n                "post": {\n                    "operationId": "advanceTime",\n                    "summary": "Create a guarded time-skip prompt only after the scene saved a natural pause.",\n                    "parameters": [_session_id_param()],\n                    "requestBody": _request_body({"$ref": "#/components/schemas/AdvanceTimeRequest"}),\n                    "responses": {\n                        "200": _json_response("Pending time-skip turn and first prompt chunk.", {"$ref": "#/components/schemas/TurnResponse"}),\n                        "409": _json_response("Time skip blocked or another turn is pending.", _loose_obj()),\n                        "422": _json_response("Invalid time skip request.", _loose_obj()),\n                    },\n                }\n            },\n            "/api/v1/sessions/{session_id}/turn-prompt-chunk": {\n''',
)
replace_once(
    "app/novella_openapi_actions.py",
    '                "then applyTurnResult with the exact turn_id."\n',
    '                "then applyTurnResult with the exact turn_id. Use advanceTime only for a user-selected natural-pause skip."\n',
)

# schemas/bootstrap_output.schema.json
replace_once(
    "schemas/bootstrap_output.schema.json",
    '"event_queue", "time_anchors", "do_not_resolve_early", "continuity_truths", "future_consequences", "pacing"]',
    '"event_queue", "time_anchors", "time_flow", "do_not_resolve_early", "continuity_truths", "future_consequences", "pacing"]',
)
replace_once(
    "schemas/bootstrap_output.schema.json",
    '"next_if_ignored", "time_hint"]',
    '"next_if_ignored", "time_hint", "skip_unit", "skip_amount"]',
)
replace_once(
    "schemas/bootstrap_output.schema.json",
    '"latest_turn": {"type": "integer", "minimum": 0}}}},\n        "time_anchors"',
    '"latest_turn": {"type": "integer", "minimum": 0}, "skip_unit": {"type": "string", "enum": ["hours", "days", "weeks", "months"]}, "skip_amount": {"type": "integer", "minimum": 0, "maximum": 365}}}},\n        "time_anchors"',
)
replace_once(
    "schemas/bootstrap_output.schema.json",
    '        "time_anchors": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "object", "additionalProperties": true}]}},\n',
    '        "time_anchors": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "object", "additionalProperties": true}]}},\n        "time_flow": {"type": "object", "required": ["current_period", "default_mode", "allow_nearest_event", "allowed_units", "max_amounts"], "properties": {"current_period": {"type": "string", "minLength": 1}, "default_mode": {"type": "string", "enum": ["nearest_event", "duration"]}, "allow_nearest_event": {"type": "boolean"}, "allowed_units": {"type": "array", "minItems": 1, "items": {"type": "string", "enum": ["hours", "days", "weeks", "months"]}}, "max_amounts": {"type": "object", "properties": {"hours": {"type": "integer", "minimum": 1}, "days": {"type": "integer", "minimum": 1}, "weeks": {"type": "integer", "minimum": 1}, "months": {"type": "integer", "minimum": 1}}}, "last_skip": {"type": ["object", "null"]}}},\n',
)
replace_once(
    "schemas/bootstrap_output.schema.json",
    '"nearby_items", "environment", "status"]',
    '"nearby_items", "environment", "time_skip_control", "status"]',
)
replace_once(
    "schemas/bootstrap_output.schema.json",
    '        "environment": {"type": "object"},\n        "status": {\n',
    '        "environment": {"type": "object"},\n        "time_skip_control": {"type": "object", "required": ["allowed", "reason", "blockers", "suggested_mode", "max_unit", "max_amount"], "properties": {"allowed": {"type": "boolean"}, "reason": {"type": "string", "minLength": 1}, "blockers": {"type": "array", "items": {"type": "string"}}, "suggested_mode": {"type": "string", "enum": ["nearest_event", "duration"]}, "max_unit": {"type": "string", "enum": ["hours", "days", "weeks", "months"]}, "max_amount": {"type": "integer", "minimum": 1, "maximum": 365}}},\n        "status": {\n',
)

# schemas/scene_contract.schema.json
replace_once(
    "schemas/scene_contract.schema.json",
    '    "story_compass": {\n      "type": "object"\n    },\n',
    '    "story_compass": {\n      "type": "object"\n    },\n    "time_skip_request": {\n      "type": "object"\n    },\n',
)

# schemas/scene_response.schema.json (already minified, keep minified)
scene_path = ROOT / "schemas/scene_response.schema.json"
scene_schema = json.loads(scene_path.read_text(encoding="utf-8"))
scene_schema.setdefault("properties", {})["time_skip_result"] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["elapsed", "routine_summary", "target_event_id", "opened_at_meaningful_beat", "skipped_major_player_choice"],
    "properties": {
        "elapsed": {
            "type": "object",
            "additionalProperties": False,
            "required": ["unit", "amount", "label"],
            "properties": {
                "unit": {"type": "string", "enum": ["hours", "days", "weeks", "months"]},
                "amount": {"type": "integer", "minimum": 0, "maximum": 365},
                "label": {"type": "string", "minLength": 1},
            },
        },
        "routine_summary": {"type": "array", "minItems": 1, "maxItems": 8, "items": {"type": "string", "minLength": 1}},
        "target_event_id": {"type": ["string", "null"]},
        "opened_at_meaningful_beat": {"const": True},
        "skipped_major_player_choice": {"const": False},
    },
}
scene_path.write_text(json.dumps(scene_schema, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

# prompts/scene_format_rules.md
replace_once(
    "prompts/scene_format_rules.md",
    "- `proposed_updates` всегда содержит объекты/массивы по schema; пустые обновления не выдумывай.\n",
    "- `proposed_updates` всегда содержит объекты/массивы по schema; пустые обновления не выдумывай. Для `advanceTime` дополнительно обязателен `time_skip_result`.\n",
)

# gpt/custom_gpt_instructions.md
replace_once(
    "gpt/custom_gpt_instructions.md",
    "health — сервер; getStartQuestionnaire — анкета; createSession — сессия; createBootstrapPreview — preview; confirmBootstrapPreview — подтверждение; processTurn — turn_id/первый chunk; getTurnPromptChunk — остальные chunks; applyTurnResult — сохранение; debugSessionDump — диагностика.\n",
    "health — сервер; getStartQuestionnaire — анкета; createSession — сессия; createBootstrapPreview — preview; confirmBootstrapPreview — подтверждение; processTurn — обычный ход; advanceTime — выбранный пользователем пропуск; getTurnPromptChunk — остальные chunks; applyTurnResult — сохранение; debugSessionDump — диагностика.\n",
)
replace_once(
    "gpt/custom_gpt_instructions.md",
    "Корень: protagonist, characters, relationships, knowledge, story_plan, current_state, npc_state, future_locks, continuity, scene_history=[], turns=[].\n",
    "Корень: protagonist, characters, relationships, knowledge, story_plan, director_bible, current_state, npc_state, future_locks, continuity, scene_history=[], turns=[].\n",
)
replace_once(
    "gpt/custom_gpt_instructions.md",
    "6. Показать message_to_user, иначе rendered_text.\nОдинаковый processTurn может вернуть тот же pending turn_id. Другой ввод до сохранения не отправлять. ResponseTooLargeError решается chunks/компакцией.\n",
    "6. Показать message_to_user, иначе rendered_text.\nВыбран вариант пропуска времени → advanceTime с точным player_input. nearest_event не требует unit/amount; duration требует. Дальше тот же chunk/applyTurnResult flow. При time_skip_blocked покажи причину и продолжай обычным ходом.\nОдинаковый processTurn/advanceTime может вернуть тот же pending turn_id. Другой ввод до сохранения не отправлять. ResponseTooLargeError решается chunks/компакцией.\n",
)
replace_once(
    "gpt/custom_gpt_instructions.md",
    "proposed_updates всегда: scene_state_patch{}, continuity_patch{}, relationship_patches[], knowledge_patches[], npc_state_patches[], new_or_updated_characters[].\n",
    "proposed_updates всегда: scene_state_patch{}, continuity_patch{}, relationship_patches[], knowledge_patches[], npc_state_patches[], new_or_updated_characters[]. Каждая сцена сохраняет scene_state_patch.time_skip_control; true только в естественной паузе. advanceTime также возвращает time_skip_result.\n",
)

# tests/test_openapi_actions_contract.py
replace_once(
    "tests/test_openapi_actions_contract.py",
    '        "turns",\n    }\n',
    '        "turns",\n    }\n',
)
# No semantic change above; keep this script idempotent around the existing set.
