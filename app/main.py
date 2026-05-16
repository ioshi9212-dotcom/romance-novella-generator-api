from fastapi import FastAPI, HTTPException

from app.config import get_settings
from app.engine import PromptEngine
from app.models import CreateSessionRequest, ManualResultRequest, SessionListItem, TurnRequest
from app.session_manager import SessionManager

settings = get_settings()
session_manager = SessionManager(settings.data_dir, settings.templates_dir)
prompt_engine = PromptEngine(settings.prompts_dir)

app = FastAPI(title=settings.app_name)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "mode": "manual_gpt_without_required_api_key",
    }


@app.post("/api/v1/sessions")
def create_session(request: CreateSessionRequest) -> dict:
    try:
        return session_manager.create_session(request)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=f"Missing template: {exc}") from exc


@app.get("/api/v1/sessions", response_model=list[SessionListItem])
def list_sessions() -> list[dict]:
    return session_manager.list_sessions()


@app.get("/api/v1/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    try:
        return session_manager.load_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc


@app.get("/api/v1/sessions/{session_id}/memory")
def get_session_memory(session_id: str) -> dict:
    try:
        data = session_manager.load_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc

    return {
        "current_state": data["current_state"],
        "player_character": data["player_character"],
        "characters": data["characters"],
        "relationships": data["relationships"],
        "knowledge_map": data["knowledge_map"],
        "npc_life_state": data["npc_life_state"],
        "story_compass": data["story_compass"],
    }


@app.post("/api/v1/sessions/{session_id}/turns")
def create_turn(session_id: str, request: TurnRequest) -> dict:
    try:
        data = session_manager.load_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc

    if request.mode == "manual_gpt":
        return {
            "mode": "manual_gpt",
            "instruction": "Copy this prompt into ChatGPT. Then paste the generated scene and JSON updates into /manual-results.",
            "prompt": prompt_engine.build_manual_prompt(data, request.player_input),
        }

    stub = prompt_engine.local_stub_scene(data, request.player_input)
    result = ManualResultRequest(
        player_input=request.player_input,
        scene_text=stub["scene_text"],
        state_update=stub["state_update"],
        knowledge_update=stub["knowledge_update"],
        npc_life_update=stub["npc_life_update"],
        notes=stub["notes"],
    )
    updated = session_manager.save_manual_result(session_id, result)
    return {
        "mode": "local_stub",
        "scene_text": stub["scene_text"],
        "session": updated,
    }


@app.post("/api/v1/sessions/{session_id}/manual-results")
def save_manual_result(session_id: str, request: ManualResultRequest) -> dict:
    try:
        return session_manager.save_manual_result(session_id, request)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
