from contextlib import nullcontext
from pathlib import Path
from typing import Any
import hashlib
import json
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.openapi.utils import get_openapi

from app.bootstrap_content_repair import repair_bootstrap_content
from app.bootstrap_preview_transport import BootstrapPreviewTransportError
from app.bootstrap_normalizer import normalize_bootstrap_json
from app.bootstrap_staging import BootstrapStageError, assemble_staged_bootstrap, save_bootstrap_part as save_staged_bootstrap_part
from app.config import get_settings
from app.directional_relationships import apply_directional_relationship_patches, prepare_directional_relationships, validate_directional_relationships
from app.director_bible import apply_director_bible_patches, prepare_director_bible, validate_director_bible
from app.id_utils import now_iso
from app.models import AdvanceTimeRequest, ApplyTurnResultRequest, ApplyTurnResultResponse, BootstrapPreviewChunkResponse, BootstrapPreviewRequest, BootstrapPreviewResponse, BootstrapConfirmRequest, BootstrapConfirmResponse, CreateSessionRequest, CreateSessionResponse, DebugSessionDumpResponse, SaveBootstrapPartRequest, SaveBootstrapPartResponse, TurnPromptChunkResponse, TurnRequest, TurnResponse
from app.npc_state_updates import apply_npc_state_patches
from app.scene_response_normalizer import normalize_scene_response
from app.session_manager import SessionManager
from app.state_updater import StateUpdater
from app.turn_maintenance import finalize_due_turn_maintenance
from app.turn_processor import process_time_skip_gpt_actions, process_turn_debug_stub, process_turn_gpt_actions
from app.time_skip import assess_time_skip, record_time_skip_result, validate_time_skip_scene_response
from app.validators import validate_bootstrap_result, validate_scene_response

RAILWAY_PUBLIC_URL = "https://web-production-4310e.up.railway.app"
app = FastAPI(title="Romance Novella Generator API", version="gpt-actions-v9", servers=[{"url": RAILWAY_PUBLIC_URL, "description": "Railway production"}])


def _ensure_object_properties(schema_part: Any) -> None:
    if isinstance(schema_part, dict):
        if schema_part.get("type") == "object" and "properties" not in schema_part:
            schema_part["properties"] = {}
        for value in schema_part.values():
            _ensure_object_properties(value)
    elif isinstance(schema_part, list):
        for item in schema_part:
            _ensure_object_properties(item)


def custom_openapi() -> dict[str, Any]:
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description="Railway API for generated novella sessions: preview gate, compact turn prompt, rendered scene response, state storage.",
        routes=app.routes,
    )
    schema["servers"] = [{"url": RAILWAY_PUBLIC_URL, "description": "Railway production"}]
    for hidden_path in [
        "/api/v1/sessions/{session_id}/memory",
        "/api/v1/sessions/{session_id}/scene-contract",
        "/api/v1/sessions/{session_id}/bootstrap-result",
        "/api/v1/sessions/latest",
        "/api/v1/sessions",
    ]:
        # listSessions is hidden by include_in_schema=False; do not remove createSession.
        if hidden_path == "/api/v1/sessions":
            continue
        schema.get("paths", {}).pop(hidden_path, None)
    _ensure_object_properties(schema)
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = get_settings().api_key
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


def _session_request_context(manager: SessionManager, session_id: str):
    """Return a same-thread transaction for an existing, safe session path."""
    try:
        session_path = manager.storage.session_dir(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not session_path.exists():
        return nullcontext()
    return manager.storage.session_transaction(session_id)


def _require_active_session(bundle: dict, action: str) -> None:
    status = (bundle.get("session") or {}).get("status")
    if status != "active":
        raise HTTPException(status_code=409, detail=f"Session must be active before {action}. Current status: {status}")


def _is_explicit_confirmation(text: str) -> bool:
    normalized = " ".join((text or "").strip().lower().replace("ё", "е").split())
    if not normalized:
        return False
    negative_markers = ["не подтверждаю", "не сохраняй", "не запускай", "нет", "стоп", "правки", "исправь", "измени"]
    if any(marker in normalized for marker in negative_markers):
        return False
    exact = {"подтверждаю", "ок", "okay", "ok", "сохраняй", "запускай", "подходит", "оставляем", "да", "начинаем", "начнем", "начнём", "поехали"}
    if normalized.strip(".!") in {item.replace("ё", "е") for item in exact}:
        return True
    phrases = ["да подтверждаю", "все подходит", "всё подходит", "можно сохранять", "можно запускать", "оставляем так", "подтверждаю все", "подтверждаю всё"]
    return any(phrase.replace("ё", "е") in normalized for phrase in phrases)


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _new_turn_id() -> str:
    return "turn_" + uuid.uuid4().hex[:12]


TURN_PROMPT_CHUNK_SIZE = 4500


def _split_prompt_chunks(text: str, chunk_size: int = TURN_PROMPT_CHUNK_SIZE) -> list[str]:
    text = text or ""
    if len(text) <= chunk_size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        # Prefer splitting on a newline so JSON/text is easier to rejoin mentally.
        if end < len(text):
            newline = text.rfind("\n", start + max(1000, chunk_size // 2), end)
            if newline > start:
                end = newline + 1
        chunks.append(text[start:end])
        start = end
    return chunks or [""]


def _store_prompt_chunks(
    manager: SessionManager,
    session_id: str,
    pending: dict[str, Any],
    scene_prompt: str,
    *,
    turn_status: str,
    turn_diagnostics: dict[str, Any],
) -> dict[str, Any]:
    chunks = _split_prompt_chunks(scene_prompt)
    updated = {
        **pending,
        "session_id": pending.get("session_id") or session_id,
        "turn_status": turn_status,
        "turn_diagnostics": turn_diagnostics,
        "scene_prompt_sha256": _hash_text(scene_prompt),
        "prompt_chunk_count": len(chunks),
        "prompt_chunk_size": TURN_PROMPT_CHUNK_SIZE,
        "prompt_chunks": chunks,
    }
    manager.storage.write_json(session_id, "pending_turn.json", updated)
    return updated


def _pending_turn_response(pending: dict[str, Any], session_id: str) -> dict[str, Any]:
    chunks = pending.get("prompt_chunks")
    if not isinstance(chunks, list) or not chunks:
        raise HTTPException(status_code=409, detail="Pending turn has no stored prompt chunks. Retry the same input to rebuild it.")

    chunk_count = int(pending.get("prompt_chunk_count") or len(chunks))
    has_more = chunk_count > 1
    next_required_action = (
        "Read all prompt chunks using getTurnPromptChunk, concatenate them in order, then generate scene_response and call applyTurnResult with this turn_id."
        if has_more
        else "Generate scene_response, then call applyTurnResult with this turn_id."
    )
    diagnostics = dict(pending.get("turn_diagnostics") or {})
    diagnostics.update({
        "turn_id": pending.get("turn_id"),
        "expected_turn_number": pending.get("expected_turn_number"),
        "next_required_action": next_required_action,
        "idempotent_pending_supported": True,
        "prompt_transport": {
            "chunked": has_more,
            "chunk_count": chunk_count,
            "returned_chunk_index": 0,
            "next_chunk_index": 1 if has_more else None,
            "scene_prompt_sha256": pending.get("scene_prompt_sha256"),
        },
    })
    first_chunk = chunks[0]
    return {
        "session_id": pending.get("session_id") or session_id,
        "status": pending.get("turn_status") or "pending",
        "scene_prompt": first_chunk,
        "prompt_chunk_index": 0,
        "prompt_chunk_count": chunk_count,
        "has_more_prompt_chunks": has_more,
        "next_prompt_chunk_index": 1 if has_more else None,
        "turn_id": pending.get("turn_id"),
        "expected_turn_number": pending.get("expected_turn_number"),
        "diagnostics": diagnostics,
    }


def _debug_clip_text(value: Any, limit: int = 900) -> str:
    text = "" if value is None else str(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


def _debug_clip_list(items: Any, limit_items: int = 12, text_limit: int = 400) -> list[Any]:
    if not isinstance(items, list):
        return []
    out: list[Any] = []
    for item in items[:limit_items]:
        if isinstance(item, str):
            out.append(_debug_clip_text(item, text_limit))
        elif isinstance(item, dict):
            out.append(_debug_clip_dict(item, max(160, text_limit // 2), 28))
        else:
            out.append(item)
    return out


def _debug_clip_dict(data: Any, text_limit: int = 700, max_items: int = 60) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    out: dict[str, Any] = {}
    for idx, (key, value) in enumerate(data.items()):
        if idx >= max_items:
            out["_truncated_keys"] = len(data) - max_items
            break
        if isinstance(value, str):
            out[str(key)] = _debug_clip_text(value, text_limit)
        elif isinstance(value, list):
            out[str(key)] = _debug_clip_list(value, 12, max(160, text_limit // 2))
        elif isinstance(value, dict):
            out[str(key)] = _debug_clip_dict(value, max(160, text_limit // 2), 30)
        else:
            out[str(key)] = value
    return out


def _raw_payload_size(data: Any) -> int:
    try:
        return len(json.dumps(data, ensure_ascii=False))
    except Exception:
        return 0


def _legacy_payload_check(raw_scene_history: Any, raw_turns: Any) -> dict[str, Any]:
    scene_has_full_text = False
    turns_have_full_response = False
    max_scene_text_len = 0
    max_turn_response_len = 0
    if isinstance(raw_scene_history, list):
        for item in raw_scene_history:
            if isinstance(item, dict):
                text = item.get("visible_scene_text")
                if isinstance(text, str) and text:
                    scene_has_full_text = True
                    max_scene_text_len = max(max_scene_text_len, len(text))
    if isinstance(raw_turns, list):
        for item in raw_turns:
            if isinstance(item, dict) and isinstance(item.get("scene_response"), dict):
                turns_have_full_response = True
                max_turn_response_len = max(max_turn_response_len, _raw_payload_size(item.get("scene_response")))
    return {
        "scene_history_has_legacy_visible_scene_text": scene_has_full_text,
        "turns_have_legacy_full_scene_response": turns_have_full_response,
        "max_legacy_visible_scene_text_len": max_scene_text_len,
        "max_legacy_scene_response_json_len": max_turn_response_len,
    }


def _debug_dump(manager: SessionManager, session_id: str) -> dict[str, Any]:
    settings = get_settings()
    bundle = manager.storage.read_session_bundle(session_id)
    raw_scene_history = manager.storage.read_json(session_id, "scene_history.json", default=[])
    raw_turns = manager.storage.read_json(session_id, "turns.json", default=[])
    session = bundle.get("session", {}) if isinstance(bundle.get("session"), dict) else {}
    current_state = bundle.get("current_state", {}) if isinstance(bundle.get("current_state"), dict) else {}
    story_plan = bundle.get("story_plan", {}) if isinstance(bundle.get("story_plan"), dict) else {}
    continuity = bundle.get("continuity", {}) if isinstance(bundle.get("continuity"), dict) else {}
    memory_chunks = continuity.get("memory_chunks", []) if isinstance(continuity.get("memory_chunks"), list) else []
    pending = _load_pending_turn(manager, session_id)

    pending_safe = {}
    if isinstance(pending, dict) and pending:
        chunk_count = int(pending.get("prompt_chunk_count") or 1)
        pending_safe = {
            "turn_id": pending.get("turn_id"),
            "status": pending.get("status"),
            "expected_turn_number": pending.get("expected_turn_number"),
            "turn_kind": pending.get("turn_kind", "normal"),
            "player_input": _debug_clip_text(pending.get("player_input"), 500),
            "prompt_chunk_count": chunk_count,
            "has_more_prompt_chunks": chunk_count > 1,
            "prompt_chunk_size": pending.get("prompt_chunk_size"),
            "scene_prompt_sha256": pending.get("scene_prompt_sha256"),
        }

    maintenance = current_state.get("maintenance") if isinstance(current_state.get("maintenance"), dict) else {}
    return {
        "session_id": session_id,
        "status": session.get("status", "unknown"),
        "server": {
            "status": "ok",
            "engine_version": settings.engine_version,
            "data_dir": str(settings.data_dir),
            "mode": "gpt_actions",
            "api_key_required": bool(settings.api_key),
            "chunk_endpoint": "getTurnPromptChunk",
            "bootstrap_preview_chunk_endpoint": "getBootstrapPreviewChunk",
            "debug_endpoint": "debugSessionDump",
        },
        "session": _debug_clip_dict(session, 700),
        "current_state": _debug_clip_dict(current_state, 700),
        "story_plan": {
            "genre": story_plan.get("genre"),
            "tone": story_plan.get("tone"),
            "current_story_position": _debug_clip_text(story_plan.get("current_story_position"), 700),
            "act_structure": _debug_clip_list(story_plan.get("act_structure", []), 3, 420),
            "status_slots": _debug_clip_list(story_plan.get("status_slots", []), 4, 300),
            "open_threads": _debug_clip_list(story_plan.get("open_threads", []), 20, 280),
            "forbidden_drift": _debug_clip_list(story_plan.get("forbidden_drift", []), 12, 240),
            "future_locks_fields": list((bundle.get("future_locks", {}) or {}).keys()) if isinstance(bundle.get("future_locks"), dict) else [],
            "future_locks_counts": {
                "do_not_reveal_yet": len((bundle.get("future_locks", {}) or {}).get("do_not_reveal_yet", []) or []),
                "hidden_character_seeds": len((bundle.get("future_locks", {}) or {}).get("hidden_character_seeds", []) or []),
            },
        },
        "characters": {cid: _debug_clip_dict(card, 700) for cid, card in (bundle.get("characters") or {}).items()},
        "knowledge": {cid: _debug_clip_dict(entry, 700) for cid, entry in (bundle.get("knowledge") or {}).items()},
        "relationships": {pid: _debug_clip_dict(entry, 700) for pid, entry in (bundle.get("relationships") or {}).items()},
        "history": {
            "recent_scene_history": bundle.get("scene_history", [])[-6:] if isinstance(bundle.get("scene_history"), list) else [],
            "recent_turns": bundle.get("turns", [])[-8:] if isinstance(bundle.get("turns"), list) else [],
            "memory_chunk_count": len(memory_chunks),
            "memory_chunk_ranges": [
                {"chunk_id": chunk.get("chunk_id"), "type": chunk.get("type"), "turn_start": chunk.get("turn_start"), "turn_end": chunk.get("turn_end")}
                for chunk in memory_chunks
                if isinstance(chunk, dict)
            ],
            "maintenance_events": _debug_clip_list(continuity.get("maintenance_events", []), 12, 260),
            "runtime_counts": {
                "raw_scene_history_len": len(raw_scene_history) if isinstance(raw_scene_history, list) else None,
                "raw_turns_len": len(raw_turns) if isinstance(raw_turns, list) else None,
                "action_scene_history_len": len(bundle.get("scene_history", []) or []),
                "action_turns_len": len(bundle.get("turns", []) or []),
                "raw_scene_history_json_len": _raw_payload_size(raw_scene_history),
                "raw_turns_json_len": _raw_payload_size(raw_turns),
            },
            "legacy_payload_check": _legacy_payload_check(raw_scene_history, raw_turns),
        },
        "pending_turn": pending_safe,
        "diagnostics": {
            "turn_number": current_state.get("turn_number"),
            "state_recovery_audit_due": maintenance.get("state_recovery_audit_due") or maintenance.get("continuity_check_required_next"),
            "state_compaction_cleanup_due": maintenance.get("state_compaction_cleanup_due") or maintenance.get("memory_review_required_next"),
            "backend_compacted_after_turn": maintenance.get("backend_compacted_after_turn"),
            "last_compact_turn": maintenance.get("last_compact_turn"),
            "memory_chunk_count": len(memory_chunks),
            "recent_scene_history_kept": len(bundle.get("scene_history", []) or []),
            "recent_turns_kept": len(bundle.get("turns", []) or []),
            "note": "Technical debug dump only; do not continue scene from this response.",
        },
    }


def _save_pending_turn(manager: SessionManager, session_id: str, player_input: str, expected_turn_number: int, *, turn_kind: str = "normal", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    pending = {
        "session_id": session_id,
        "turn_id": _new_turn_id(),
        "status": "pending",
        "player_input": player_input,
        "player_input_sha256": _hash_text(player_input),
        "expected_turn_number": expected_turn_number,
        "created_at": now_iso(),
        "turn_kind": turn_kind,
        **(metadata or {}),
    }
    manager.storage.write_json(session_id, "pending_turn.json", pending)
    return pending




def _repair_pending_prompt_chunks(manager: SessionManager, session_id: str, pending: dict[str, Any]) -> dict[str, Any]:
    chunks = pending.get("prompt_chunks")
    if not isinstance(chunks, list) or not chunks or not all(isinstance(chunk, str) for chunk in chunks):
        return pending
    stored_size = int(pending.get("prompt_chunk_size") or 0)
    needs_repair = stored_size != TURN_PROMPT_CHUNK_SIZE or any(len(chunk) > TURN_PROMPT_CHUNK_SIZE for chunk in chunks)
    if not needs_repair:
        return pending
    full_prompt = "".join(chunks)
    repaired_chunks = _split_prompt_chunks(full_prompt)
    repaired = {
        **pending,
        "scene_prompt_sha256": _hash_text(full_prompt),
        "prompt_chunk_count": len(repaired_chunks),
        "prompt_chunk_size": TURN_PROMPT_CHUNK_SIZE,
        "prompt_chunks": repaired_chunks,
        "prompt_chunks_repaired_at": now_iso(),
    }
    manager.storage.write_json(session_id, "pending_turn.json", repaired)
    return repaired


def _load_pending_turn(manager: SessionManager, session_id: str) -> dict[str, Any]:
    pending = manager.storage.read_json(session_id, "pending_turn.json", default={})
    if isinstance(pending, dict):
        pending.setdefault("session_id", session_id)
        return _repair_pending_prompt_chunks(manager, session_id, pending)
    return {}


def _extract_turn_id_from_scene_response(scene_response: dict[str, Any]) -> str | None:
    """Compatibility layer for old Custom GPT Actions imports.

    Some already-imported Actions schemas expose only `scene_response` and reject a
    top-level `turn_id` parameter. In that case GPT may place the id inside the
    scene_response object, or omit it entirely even though the backend has a
    single pending turn. This helper lets the backend stay strict about pending
    turn matching without breaking old Action schemas.
    """
    if not isinstance(scene_response, dict):
        return None
    for key in ("turn_id", "_turn_id", "pending_turn_id"):
        value = scene_response.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    diagnostics = scene_response.get("diagnostics")
    if isinstance(diagnostics, dict):
        value = diagnostics.get("turn_id") or diagnostics.get("pending_turn_id")
        if isinstance(value, str) and value.strip():
            return value.strip()
    metadata = scene_response.get("metadata")
    if isinstance(metadata, dict):
        value = metadata.get("turn_id") or metadata.get("pending_turn_id")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _coerce_scene_response_payload(request: ApplyTurnResultRequest) -> dict[str, Any]:
    """Move known top-level compatibility fields into scene_response.

    Custom GPT may retry after an Action-schema error by sending fields such as
    rendered_text, proposed_updates or safety_checks next to scene_response. The
    canonical backend contract keeps them inside scene_response, but accepting
    and relocating them here prevents false 422/UnrecognizedKwargs failures.
    """
    raw = dict(request.scene_response or {})

    for key in ("rendered_text", "proposed_updates", "safety_checks", "metadata", "diagnostics"):
        value = getattr(request, key, None)
        if value is not None and key not in raw:
            raw[key] = value

    # Pydantic extra fields, if any, are also folded in conservatively.
    extras = getattr(request, "model_extra", None) or {}
    if isinstance(extras, dict):
        for key in ("rendered_text", "proposed_updates", "safety_checks", "metadata", "diagnostics"):
            value = extras.get(key)
            if value is not None and key not in raw:
                raw[key] = value

    return raw


def _require_pending_turn_match(manager: SessionManager, session_id: str, request_turn_id: str | None, normalized_scene_response: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
    pending = _load_pending_turn(manager, session_id)
    if not pending or not pending.get("turn_id"):
        raise HTTPException(status_code=409, detail="No pending turn. Call processTurn or advanceTime before applyTurnResult.")
    if pending.get("status") == "applied":
        raise HTTPException(status_code=409, detail="This turn was already applied. Call processTurn for the next player input.")

    # Backward-compatible fallback: if the imported Action cannot pass top-level
    # turn_id, bind to the single pending turn. The player_input check below still
    # prevents applying a scene generated from stale context.
    if not request_turn_id:
        request_turn_id = str(pending.get("turn_id") or "").strip()

    if request_turn_id != pending.get("turn_id"):
        raise HTTPException(status_code=409, detail="Stale or mismatched turn_id. Do not apply a scene_response from an old scene_prompt.")

    expected_input = str(pending.get("player_input") or "").strip()
    actual_input = str(normalized_scene_response.get("player_input") or "").strip()
    if not actual_input:
        raise HTTPException(status_code=422, detail="scene_response.player_input is required and must match the pending turn input.")
    if actual_input != expected_input:
        raise HTTPException(status_code=409, detail="scene_response.player_input does not match the pending processTurn input.")

    current_turn_number = int(((bundle.get("current_state") or {}).get("turn_number", 0)) or 0)
    expected_turn_number = int(pending.get("expected_turn_number") or (current_turn_number + 1))
    if expected_turn_number != current_turn_number + 1:
        raise HTTPException(status_code=409, detail="Pending turn number is stale. Call processTurn again.")
    return pending


def _mark_pending_turn_applied(manager: SessionManager, session_id: str, pending: dict[str, Any]) -> None:
    manager.storage.write_json(session_id, "pending_turn.json", {**pending, "status": "applied", "applied_at": now_iso()})


def _process_turn_locked(manager: SessionManager, session_id: str, request: TurnRequest, player_input: str, bundle: dict[str, Any]) -> dict:
    if request.mode == "debug_stub":
        result = process_turn_debug_stub(bundle, player_input)
        apply_result = StateUpdater(manager.storage).apply_scene_response(session_id, result["scene_response"])
        return {
            "session_id": session_id,
            "status": apply_result["status"],
            "scene": result["scene"],
            "scene_prompt": None,
            "turn_id": None,
            "expected_turn_number": apply_result.get("next_builder_hints", {}).get("maintenance", {}).get("last_saved_turn_number"),
            "diagnostics": result["diagnostics"] | {"apply_result": apply_result},
        }

    expected_turn_number = int(((bundle.get("current_state") or {}).get("turn_number", 0)) or 0) + 1
    existing_pending = _load_pending_turn(manager, session_id)
    if existing_pending.get("status") == "pending":
        if existing_pending.get("turn_kind", "normal") != "normal":
            raise HTTPException(status_code=409, detail="A time-skip turn is pending. Apply it before sending a normal turn.")
        same_input = existing_pending.get("player_input_sha256") == _hash_text(player_input)
        same_turn = int(existing_pending.get("expected_turn_number") or 0) == expected_turn_number
        if same_input and same_turn:
            has_prompt = isinstance(existing_pending.get("prompt_chunks"), list) and bool(existing_pending.get("prompt_chunks"))
            if has_prompt:
                return _pending_turn_response(existing_pending, session_id)
            # Recover a turn that was reserved before prompt generation completed.
            repaired_result = process_turn_gpt_actions(bundle, player_input)
            repaired_pending = _store_prompt_chunks(
                manager,
                session_id,
                existing_pending,
                repaired_result["scene_prompt"],
                turn_status=repaired_result["status"],
                turn_diagnostics=repaired_result["diagnostics"],
            )
            return _pending_turn_response(repaired_pending, session_id)
        raise HTTPException(
            status_code=409,
            detail="Another turn is still pending. Apply its result before sending a different player input.",
        )

    # Build the prompt before reserving the turn. A prompt-building exception must
    # not leave an empty pending_turn that blocks the session.
    result = process_turn_gpt_actions(bundle, player_input)
    pending = _save_pending_turn(manager, session_id, player_input, expected_turn_number)
    pending = _store_prompt_chunks(
        manager,
        session_id,
        pending,
        result["scene_prompt"],
        turn_status=result["status"],
        turn_diagnostics=result["diagnostics"],
    )
    return _pending_turn_response(pending, session_id)


def _advance_time_locked(manager: SessionManager, session_id: str, request: AdvanceTimeRequest, player_input: str, bundle: dict[str, Any]) -> dict:
    expected_turn_number = int(((bundle.get("current_state") or {}).get("turn_number", 0)) or 0) + 1
    assessment = assess_time_skip(
        bundle,
        mode=request.skip_mode,
        unit=request.unit,
        amount=request.amount,
    )
    if not assessment["allowed"]:
        control = assessment.get("control") or {}
        raise HTTPException(
            status_code=409,
            detail={
                "code": "time_skip_blocked",
                "reason": control.get("reason"),
                "blockers": assessment.get("blockers", []),
            },
        )

    request_fingerprint = _hash_text(json.dumps({
        "player_input": player_input,
        "skip_mode": request.skip_mode,
        "unit": request.unit,
        "amount": request.amount,
    }, ensure_ascii=False, sort_keys=True))
    existing_pending = _load_pending_turn(manager, session_id)
    if existing_pending.get("status") == "pending":
        same_request = existing_pending.get("time_skip_request_sha256") == request_fingerprint
        same_turn = int(existing_pending.get("expected_turn_number") or 0) == expected_turn_number
        if same_request and same_turn and existing_pending.get("turn_kind") == "time_skip":
            if isinstance(existing_pending.get("prompt_chunks"), list) and existing_pending.get("prompt_chunks"):
                return _pending_turn_response(existing_pending, session_id)
            repaired = process_time_skip_gpt_actions(
                bundle,
                player_input,
                skip_mode=request.skip_mode,
                unit=request.unit,
                amount=request.amount,
            )
            repaired_pending = _store_prompt_chunks(
                manager,
                session_id,
                existing_pending,
                repaired["scene_prompt"],
                turn_status=repaired["status"],
                turn_diagnostics=repaired["diagnostics"],
            )
            return _pending_turn_response(repaired_pending, session_id)
        raise HTTPException(status_code=409, detail="Another turn is still pending. Apply it before advancing time.")

    generated = process_time_skip_gpt_actions(
        bundle,
        player_input,
        skip_mode=request.skip_mode,
        unit=request.unit,
        amount=request.amount,
    )
    pending = _save_pending_turn(
        manager,
        session_id,
        player_input,
        expected_turn_number,
        turn_kind="time_skip",
        metadata={
            "time_skip_request_sha256": request_fingerprint,
            "time_skip_request": generated.get("time_skip_request", {}),
        },
    )
    pending = _store_prompt_chunks(
        manager,
        session_id,
        pending,
        generated["scene_prompt"],
        turn_status=generated["status"],
        turn_diagnostics=generated["diagnostics"],
    )
    return _pending_turn_response(pending, session_id)


def _prepare_bootstrap_preview_payload(bootstrap_json: dict[str, Any]) -> dict[str, Any]:
    normalized_bootstrap = normalize_bootstrap_json(bootstrap_json)
    repair_bootstrap_content(normalized_bootstrap)
    errors = validate_bootstrap_result(normalized_bootstrap)
    prepare_directional_relationships(normalized_bootstrap)
    prepare_director_bible(normalized_bootstrap)
    errors.extend(validate_directional_relationships(normalized_bootstrap))
    errors.extend(validate_director_bible(normalized_bootstrap))
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    return normalized_bootstrap


@app.get("/health", operation_id="health")
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "engine_version": settings.engine_version,
        "data_dir": str(settings.data_dir),
        "mode": "gpt_actions",
        "api_key_required": bool(settings.api_key),
    }


@app.post("/api/v1/sessions", response_model=CreateSessionResponse, dependencies=[Depends(require_api_key)], operation_id="createSession")
def create_session(request: CreateSessionRequest) -> dict:
    return SessionManager().create_session(request)


@app.get("/api/v1/start-questionnaire", dependencies=[Depends(require_api_key)], operation_id="getStartQuestionnaire")
def get_start_questionnaire() -> dict:
    path = Path(__file__).resolve().parent.parent / "prompts" / "start_questionnaire.md"
    return {"questionnaire": path.read_text(encoding="utf-8")}


@app.get("/api/v1/sessions", dependencies=[Depends(require_api_key)], operation_id="listSessions", include_in_schema=False)
def list_sessions() -> dict:
    return {"sessions": SessionManager().list_sessions()}


@app.get("/api/v1/sessions/latest", dependencies=[Depends(require_api_key)], include_in_schema=False)
def get_latest_session() -> dict:
    manager = SessionManager()
    latest = manager.get_latest_session_id(prefer_active=True)
    if not latest:
        raise HTTPException(status_code=404, detail="No sessions found")
    return {"session_id": latest, "session": manager.get_memory(latest)["session"]}


@app.get("/api/v1/sessions/{session_id}", dependencies=[Depends(require_api_key)], operation_id="getSession")
def get_session(session_id: str) -> dict:
    manager = SessionManager()
    try:
        with _session_request_context(manager, session_id):
            return manager.get_memory(session_id)["session"]
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/v1/sessions/{session_id}/memory", dependencies=[Depends(require_api_key)], include_in_schema=False)
def get_memory(session_id: str) -> dict:
    manager = SessionManager()
    try:
        with _session_request_context(manager, session_id):
            return manager.get_memory(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/v1/sessions/{session_id}/bootstrap-result", dependencies=[Depends(require_api_key)], include_in_schema=False)
def apply_bootstrap_result_disabled(session_id: str) -> dict:
    raise HTTPException(status_code=410, detail="bootstrap-result is disabled in v9. Use bootstrap-preview and bootstrap-confirm.")


@app.post("/api/v1/sessions/{session_id}/bootstrap-preview", response_model=BootstrapPreviewResponse, dependencies=[Depends(require_api_key)], operation_id="createBootstrapPreview")
def create_bootstrap_preview(session_id: str, request: BootstrapPreviewRequest) -> dict:
    normalized_bootstrap = _prepare_bootstrap_preview_payload(request.bootstrap_json)
    manager = SessionManager()
    try:
        with _session_request_context(manager, session_id):
            return manager.save_bootstrap_preview(session_id, normalized_bootstrap)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get(
    "/api/v1/sessions/{session_id}/bootstrap-preview-chunk",
    response_model=BootstrapPreviewChunkResponse,
    dependencies=[Depends(require_api_key)],
    operation_id="getBootstrapPreviewChunk",
)
def get_bootstrap_preview_chunk_action(
    session_id: str,
    chunk_index: int = Query(..., ge=0),
    preview_id: str | None = Query(default=None, min_length=1),
) -> dict:
    manager = SessionManager()
    try:
        with _session_request_context(manager, session_id):
            return manager.get_bootstrap_preview_chunk(
                session_id,
                chunk_index,
                preview_id=preview_id,
            )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BootstrapPreviewTransportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/api/v1/sessions/{session_id}/bootstrap-part", response_model=SaveBootstrapPartResponse, dependencies=[Depends(require_api_key)], operation_id="saveBootstrapPart")
def save_bootstrap_part_action(session_id: str, request: SaveBootstrapPartRequest) -> dict:
    manager = SessionManager()
    try:
        with _session_request_context(manager, session_id):
            return save_staged_bootstrap_part(
                manager,
                session_id,
                section=request.section,
                item_id=request.item_id,
                value=request.value,
            )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BootstrapStageError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/api/v1/sessions/{session_id}/bootstrap-preview-finalize", response_model=BootstrapPreviewResponse, dependencies=[Depends(require_api_key)], operation_id="finalizeBootstrapPreview")
def finalize_bootstrap_preview(session_id: str) -> dict:
    manager = SessionManager()
    try:
        with _session_request_context(manager, session_id):
            staged_bootstrap, progress = assemble_staged_bootstrap(manager, session_id)
            normalized_bootstrap = _prepare_bootstrap_preview_payload(staged_bootstrap)
            response = manager.save_bootstrap_preview(session_id, normalized_bootstrap)
            diagnostics = dict(response.get("diagnostics") or {})
            diagnostics.update({"staged_bootstrap": True, "staged_progress": progress})
            response["diagnostics"] = diagnostics
            return response
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BootstrapStageError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/v1/sessions/{session_id}/bootstrap-confirm", response_model=BootstrapConfirmResponse, dependencies=[Depends(require_api_key)], operation_id="confirmBootstrapPreview")
def confirm_bootstrap_preview(session_id: str, request: BootstrapConfirmRequest) -> dict:
    if not _is_explicit_confirmation(request.confirmation_text):
        raise HTTPException(status_code=409, detail="Bootstrap preview is not explicitly confirmed.")
    manager = SessionManager()
    try:
        with _session_request_context(manager, session_id):
            return manager.confirm_bootstrap_preview(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get("/api/v1/sessions/{session_id}/debug-dump", response_model=DebugSessionDumpResponse, dependencies=[Depends(require_api_key)], operation_id="debugSessionDump")
def debug_session_dump(session_id: str) -> dict:
    manager = SessionManager()
    try:
        with _session_request_context(manager, session_id):
            bundle = manager.get_memory(session_id)
            _require_active_session(bundle, "debugging a session")
            return _debug_dump(manager, session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/v1/sessions/{session_id}/scene-contract", dependencies=[Depends(require_api_key)], include_in_schema=False)
def get_scene_contract(session_id: str) -> dict:
    from app.scene_contract_builder import build_scene_contract
    manager = SessionManager()
    try:
        with _session_request_context(manager, session_id):
            bundle = manager.get_memory(session_id)
            _require_active_session(bundle, "building a scene contract")
            return build_scene_contract(bundle)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/v1/sessions/{session_id}/turn", response_model=TurnResponse, response_model_exclude_none=True, dependencies=[Depends(require_api_key)], operation_id="processTurn")
def process_turn(session_id: str, request: TurnRequest) -> dict:
    player_input = (request.player_input or "").strip()
    if not player_input:
        raise HTTPException(status_code=422, detail="player_input is empty; do not write a scene from stale context.")

    manager = SessionManager()
    try:
        with _session_request_context(manager, session_id):
            bundle = manager.get_memory(session_id)
            _require_active_session(bundle, "processing a turn")
            return _process_turn_locked(manager, session_id, request, player_input, bundle)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/v1/sessions/{session_id}/advance-time", response_model=TurnResponse, response_model_exclude_none=True, dependencies=[Depends(require_api_key)], operation_id="advanceTime")
def advance_time(session_id: str, request: AdvanceTimeRequest) -> dict:
    player_input = (request.player_input or "").strip()
    if not player_input:
        raise HTTPException(status_code=422, detail="player_input is empty; time skip must come from the latest user request.")
    if request.skip_mode == "duration" and (request.unit is None or request.amount is None):
        raise HTTPException(status_code=422, detail="duration time skip requires unit and amount.")

    manager = SessionManager()
    try:
        with _session_request_context(manager, session_id):
            bundle = manager.get_memory(session_id)
            _require_active_session(bundle, "advancing time")
            return _advance_time_locked(manager, session_id, request, player_input, bundle)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/v1/sessions/{session_id}/turn-prompt-chunk", response_model=TurnPromptChunkResponse, dependencies=[Depends(require_api_key)], operation_id="getTurnPromptChunk")
def get_turn_prompt_chunk(
    session_id: str,
    turn_id: str = Query(..., description="turn_id returned by processTurn"),
    chunk_index: int = Query(..., ge=0, description="Zero-based prompt chunk index."),
) -> dict:
    manager = SessionManager()
    try:
        with _session_request_context(manager, session_id):
            pending = _load_pending_turn(manager, session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if not pending or pending.get("turn_id") != turn_id:
        raise HTTPException(status_code=409, detail="Missing or mismatched pending turn_id. Call processTurn or advanceTime again.")
    if pending.get("status") == "applied":
        raise HTTPException(status_code=409, detail="This turn was already applied. Call processTurn for the next player input.")

    chunks = pending.get("prompt_chunks")
    if not isinstance(chunks, list) or not chunks:
        raise HTTPException(status_code=404, detail="No stored prompt chunks for this pending turn.")
    if chunk_index >= len(chunks):
        raise HTTPException(status_code=416, detail=f"chunk_index out of range. Available: 0..{len(chunks)-1}")

    has_more = chunk_index < len(chunks) - 1
    return {
        "session_id": session_id,
        "turn_id": turn_id,
        "chunk_index": chunk_index,
        "chunk_count": len(chunks),
        "scene_prompt_chunk": chunks[chunk_index],
        "has_more": has_more,
        "next_chunk_index": chunk_index + 1 if has_more else None,
        "diagnostics": {
            "scene_prompt_sha256": pending.get("scene_prompt_sha256"),
            "instruction": "Concatenate scene_prompt_chunk values in index order before generating scene_response.",
        },
    }


@app.post("/api/v1/sessions/{session_id}/apply-turn-result", response_model=ApplyTurnResultResponse, dependencies=[Depends(require_api_key)], operation_id="applyTurnResult")
def apply_turn_result(session_id: str, request: ApplyTurnResultRequest) -> dict:
    manager = SessionManager()
    updater = StateUpdater(manager.storage)
    try:
        with _session_request_context(manager, session_id):
            bundle = manager.get_memory(session_id)
            _require_active_session(bundle, "applying a turn result")
            raw_scene_response = _coerce_scene_response_payload(request)
            compatible_turn_id = request.turn_id or _extract_turn_id_from_scene_response(raw_scene_response)
            normalized_scene_response = normalize_scene_response(raw_scene_response, bundle)
            pending = _require_pending_turn_match(manager, session_id, compatible_turn_id, normalized_scene_response, bundle)
            errors = validate_scene_response(normalized_scene_response)
            errors.extend(validate_time_skip_scene_response(pending, normalized_scene_response, bundle))
            if errors:
                raise HTTPException(status_code=422, detail=errors)
            result = updater.apply_scene_response(session_id, normalized_scene_response)
            result = apply_npc_state_patches(
                manager.storage,
                session_id,
                normalized_scene_response,
                bundle,
                result,
            )
            result = apply_directional_relationship_patches(
                manager.storage,
                session_id,
                normalized_scene_response,
                bundle,
                result,
            )
            result = apply_director_bible_patches(
                manager.storage,
                session_id,
                normalized_scene_response,
                bundle,
                result,
            )
            result = record_time_skip_result(
                manager.storage,
                session_id,
                pending,
                normalized_scene_response,
                bundle,
                result,
            )
            result = finalize_due_turn_maintenance(manager.storage, session_id, result)
            _mark_pending_turn_applied(manager, session_id, pending)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    rendered_text = normalized_scene_response["scene"]["rendered_text"]
    return {
        "session_id": session_id,
        "status": result["status"],
        "message_to_user": rendered_text,
        "rendered_text": rendered_text,
        "must_show_to_user": True,
        "applied": result["applied"],
        "rejected": result["rejected"],
        "next_builder_hints": result["next_builder_hints"],
    }


from app.novella_openapi_actions import install_openapi_actions
install_openapi_actions(app)
