from fastapi import FastAPI, HTTPException
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
from app.turn_processor import process_turn_local_stub, process_turn_manual
from app.validators import validate_bootstrap_result, validate_scene_response


app = FastAPI(title="Romance Novella Generator API", version="starter-v1")


@app.get("/health")
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "engine_version": settings.engine_version,
        "data_dir": str(settings.data_dir),
        "mode": "starter",
    }


@app.post("/api/v1/sessions", response_model=CreateSessionResponse)
def create_session(request: CreateSessionRequest) -> dict:
    manager = SessionManager()
    return manager.create_session(request)


@app.get("/api/v1/sessions")
def list_sessions() -> dict:
    manager = SessionManager()
    return {"sessions": manager.list_sessions()}


@app.get("/api/v1/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    manager = SessionManager()
    try:
        return manager.get_memory(session_id)["session"]
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/v1/sessions/{session_id}/memory")
def get_memory(session_id: str) -> dict:
    manager = SessionManager()
    try:
        return manager.get_memory(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/v1/sessions/{session_id}/bootstrap-result")
def apply_bootstrap_result(session_id: str, request: BootstrapResultRequest) -> dict:
    errors = validate_bootstrap_result(request.bootstrap_json)
    if errors:
        raise HTTPException(status_code=422, detail=errors)

    manager = SessionManager()
    try:
        return manager.apply_bootstrap_result(session_id, request.bootstrap_json)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/v1/sessions/{session_id}/scene-contract")
def get_scene_contract(session_id: str) -> dict:
    from app.scene_contract_builder import build_scene_contract

    manager = SessionManager()
    try:
        bundle = manager.get_memory(session_id)
        return build_scene_contract(bundle)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/v1/sessions/{session_id}/turn", response_model=TurnResponse)
def process_turn(session_id: str, request: TurnRequest) -> dict:
    manager = SessionManager()
    try:
        bundle = manager.get_memory(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if request.mode == "local_stub":
        result = process_turn_local_stub(bundle, request.player_input)
        updater = StateUpdater(manager.storage)
        apply_result = updater.apply_scene_response(session_id, result["scene_response"])
        return {
            "session_id": session_id,
            "status": apply_result["status"],
            "scene": result["scene"],
            "scene_prompt": None,
            "diagnostics": result["diagnostics"] | {"apply_result": apply_result},
        }

    if request.mode == "manual_gpt":
        result = process_turn_manual(bundle, request.player_input)
        return {
            "session_id": session_id,
            "status": result["status"],
            "scene": None,
            "scene_prompt": result["scene_prompt"],
            "diagnostics": result["diagnostics"],
        }

    raise HTTPException(status_code=501, detail="llm mode is reserved for the next ZIP/version")


@app.post("/api/v1/sessions/{session_id}/apply-turn-result", response_model=ApplyTurnResultResponse)
def apply_turn_result(session_id: str, request: ApplyTurnResultRequest) -> dict:
    errors = validate_scene_response(request.scene_response)
    if errors:
        raise HTTPException(status_code=422, detail=errors)

    manager = SessionManager()
    updater = StateUpdater(manager.storage)

    try:
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
