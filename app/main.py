from pathlib import Path
from fastapi import Depends, FastAPI, Header, HTTPException
from app.config import get_settings
from app.models import (
    ApplyTurnResultRequest,
    ApplyTurnResultResponse,
    BootstrapResultRequest,
    CreateSessionRequest,
    CreateSessionResponse,
    TurnRequest,
    TurnResponse,
)
from app.session_manager import SessionManager
from app.state_updater import StateUpdater
from app.turn_processor import process_turn_debug_stub, process_turn_gpt_actions
from app.validators import validate_bootstrap_result, validate_scene_response


app = FastAPI(title="Romance Novella Generator API", version="gpt-actions-v8")


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Optional API key protection.

    If API_KEY is set in Railway variables, every protected endpoint must receive
    X-API-Key with the same value. If API_KEY is not set, local/dev mode stays open.
    """
    expected = get_settings().api_key
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


def _require_active_session(bundle: dict, action: str) -> None:
    status = (bundle.get("session") or {}).get("status")
    if status != "active":
        raise HTTPException(
            status_code=409,
            detail=f"Session must be active before {action}. Current status: {status}",
        )


@app.get("/health")
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "engine_version": settings.engine_version,
        "data_dir": str(settings.data_dir),
        "mode": "gpt_actions",
        "api_key_required": bool(settings.api_key),
    }


@app.post("/api/v1/sessions", response_model=CreateSessionResponse, dependencies=[Depends(require_api_key)])
def create_session(request: CreateSessionRequest) -> dict:
    manager = SessionManager()
    return manager.create_session(request)


@app.get("/api/v1/start-questionnaire", dependencies=[Depends(require_api_key)])
def get_start_questionnaire() -> dict:
    path = Path(__file__).resolve().parent.parent / "prompts" / "start_questionnaire.md"
    return {"questionnaire": path.read_text(encoding="utf-8")}


@app.get("/api/v1/sessions", dependencies=[Depends(require_api_key)])
def list_sessions() -> dict:
    manager = SessionManager()
    return {"sessions": manager.list_sessions()}


@app.get("/api/v1/sessions/latest", dependencies=[Depends(require_api_key)])
def get_latest_session() -> dict:
    manager = SessionManager()
    latest = manager.get_latest_session_id(prefer_active=True)
    if not latest:
        raise HTTPException(status_code=404, detail="No sessions found")
    return {"session_id": latest, "session": manager.get_memory(latest)["session"]}


@app.get("/api/v1/sessions/{session_id}", dependencies=[Depends(require_api_key)])
def get_session(session_id: str) -> dict:
    manager = SessionManager()
    try:
        return manager.get_memory(session_id)["session"]
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/v1/sessions/{session_id}/memory", dependencies=[Depends(require_api_key)])
def get_memory(session_id: str) -> dict:
    manager = SessionManager()
    try:
        return manager.get_memory(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/v1/sessions/{session_id}/bootstrap-result", dependencies=[Depends(require_api_key)])
def apply_bootstrap_result(session_id: str, request: BootstrapResultRequest) -> dict:
    errors = validate_bootstrap_result(request.bootstrap_json)
    if errors:
        raise HTTPException(status_code=422, detail=errors)

    manager = SessionManager()
    try:
        session = manager.get_memory(session_id)["session"]
        if session.get("status") not in {"bootstrap_pending", "active"}:
            raise HTTPException(status_code=409, detail=f"Cannot apply bootstrap to session status: {session.get('status')}")
        return manager.apply_bootstrap_result(session_id, request.bootstrap_json)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/v1/sessions/{session_id}/scene-contract", dependencies=[Depends(require_api_key)])
def get_scene_contract(session_id: str) -> dict:
    from app.scene_contract_builder import build_scene_contract

    manager = SessionManager()
    try:
        bundle = manager.get_memory(session_id)
        _require_active_session(bundle, "building a scene contract")
        return build_scene_contract(bundle)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/v1/sessions/{session_id}/turn", response_model=TurnResponse, dependencies=[Depends(require_api_key)])
def process_turn(session_id: str, request: TurnRequest) -> dict:
    manager = SessionManager()
    try:
        bundle = manager.get_memory(session_id)
        _require_active_session(bundle, "processing a turn")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if request.mode == "debug_stub":
        result = process_turn_debug_stub(bundle, request.player_input)
        updater = StateUpdater(manager.storage)
        apply_result = updater.apply_scene_response(session_id, result["scene_response"])
        return {
            "session_id": session_id,
            "status": apply_result["status"],
            "scene": result["scene"],
            "scene_prompt": None,
            "diagnostics": result["diagnostics"] | {"apply_result": apply_result},
        }

    result = process_turn_gpt_actions(bundle, request.player_input)
    return {
        "session_id": session_id,
        "status": result["status"],
        "scene": None,
        "scene_prompt": result["scene_prompt"],
        "diagnostics": result["diagnostics"],
    }


@app.post("/api/v1/sessions/{session_id}/apply-turn-result", response_model=ApplyTurnResultResponse, dependencies=[Depends(require_api_key)])
def apply_turn_result(session_id: str, request: ApplyTurnResultRequest) -> dict:
    errors = validate_scene_response(request.scene_response)
    if errors:
        raise HTTPException(status_code=422, detail=errors)

    manager = SessionManager()
    updater = StateUpdater(manager.storage)

    try:
        bundle = manager.get_memory(session_id)
        _require_active_session(bundle, "applying a turn result")
        result = updater.apply_scene_response(session_id, request.scene_response)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return {
        "session_id": session_id,
        "status": result["status"],
        "applied": result["applied"],
        "rejected": result["rejected"],
        "next_builder_hints": result["next_builder_hints"],
    }
