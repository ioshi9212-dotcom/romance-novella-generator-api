from pathlib import Path
import re


MODELS = Path("app/models.py")
MAIN = Path("app/main.py")


models = MODELS.read_text(encoding="utf-8")
models_pattern = re.compile(
    r"class BootstrapPreviewResponse\(BaseModel\):.*?\nclass BootstrapConfirmRequest\(BaseModel\):",
    re.S,
)
models_replacement = '''class BootstrapPreviewResponse(BaseModel):
    message_to_user: str = Field(
        ...,
        description=(
            "First bounded preview chunk. If has_more_preview_chunks=true, do not answer the user yet: "
            "load every remaining chunk with getBootstrapPreviewChunk, concatenate in index order, "
            "then output the complete preview exactly once."
        ),
    )
    session_id: str
    status: str
    must_show_to_user: bool = True
    wait_for_confirmation: bool = True
    next_user_action: str = "Напиши `подтверждаю`, если всё подходит, или скажи, что изменить."
    preview: str = Field(..., description="Compatibility alias for the first bounded preview chunk.")
    user_visible_preview: str = Field(..., description="Compatibility alias for the first bounded preview chunk.")
    preview_id: str
    preview_chunk: str
    preview_chunk_index: int = 0
    preview_chunk_count: int = 1
    has_more_preview_chunks: bool = False
    next_preview_chunk_index: int | None = None
    can_confirm: bool = True
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class BootstrapPreviewChunkResponse(BaseModel):
    session_id: str
    preview_id: str
    chunk_index: int
    chunk_count: int
    preview_chunk: str
    has_more: bool
    next_chunk_index: int | None = None
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class BootstrapConfirmRequest(BaseModel):'''
models, count = models_pattern.subn(models_replacement, models, count=1)
if count != 1:
    raise RuntimeError(f"BootstrapPreviewResponse replacement count: {count}")
MODELS.write_text(models, encoding="utf-8")


main = MAIN.read_text(encoding="utf-8")
old_import = "from app.bootstrap_normalizer import normalize_bootstrap_json\n"
new_import = (
    "from app.bootstrap_normalizer import normalize_bootstrap_json\n"
    "from app.bootstrap_preview_transport import (\n"
    "    BootstrapPreviewChunkError,\n"
    "    get_bootstrap_preview_chunk,\n"
    "    prepare_bootstrap_preview_transport,\n"
    "    require_complete_bootstrap_preview_delivery,\n"
    ")\n"
)
if main.count(old_import) != 1:
    raise RuntimeError("bootstrap_normalizer import not found exactly once")
main = main.replace(old_import, new_import, 1)

old_models_import = "from app.models import AdvanceTimeRequest, ApplyTurnResultRequest, ApplyTurnResultResponse, BootstrapPreviewRequest, BootstrapPreviewResponse, BootstrapConfirmRequest, BootstrapConfirmResponse, CreateSessionRequest, CreateSessionResponse, DebugSessionDumpResponse, SaveBootstrapPartRequest, SaveBootstrapPartResponse, TurnPromptChunkResponse, TurnRequest, TurnResponse"
new_models_import = "from app.models import AdvanceTimeRequest, ApplyTurnResultRequest, ApplyTurnResultResponse, BootstrapPreviewChunkResponse, BootstrapPreviewRequest, BootstrapPreviewResponse, BootstrapConfirmRequest, BootstrapConfirmResponse, CreateSessionRequest, CreateSessionResponse, DebugSessionDumpResponse, SaveBootstrapPartRequest, SaveBootstrapPartResponse, TurnPromptChunkResponse, TurnRequest, TurnResponse"
if main.count(old_models_import) != 1:
    raise RuntimeError("models import not found exactly once")
main = main.replace(old_models_import, new_models_import, 1)

old_direct = '''        with _session_request_context(manager, session_id):
            return manager.save_bootstrap_preview(session_id, normalized_bootstrap)
'''
new_direct = '''        with _session_request_context(manager, session_id):
            response = manager.save_bootstrap_preview(session_id, normalized_bootstrap)
            return prepare_bootstrap_preview_transport(manager, session_id, response)
'''
if main.count(old_direct) != 1:
    raise RuntimeError("direct bootstrap preview block not found exactly once")
main = main.replace(old_direct, new_direct, 1)

old_finalize = '''            diagnostics = dict(response.get("diagnostics") or {})
            diagnostics.update({"staged_bootstrap": True, "staged_progress": progress})
            response["diagnostics"] = diagnostics
            return response
'''
new_finalize = '''            diagnostics = dict(response.get("diagnostics") or {})
            diagnostics.update({"staged_bootstrap": True, "staged_progress": progress})
            response["diagnostics"] = diagnostics
            return prepare_bootstrap_preview_transport(manager, session_id, response)
'''
if main.count(old_finalize) != 1:
    raise RuntimeError("finalize bootstrap preview block not found exactly once")
main = main.replace(old_finalize, new_finalize, 1)

confirm_marker = '''@app.post("/api/v1/sessions/{session_id}/bootstrap-confirm", response_model=BootstrapConfirmResponse, dependencies=[Depends(require_api_key)], operation_id="confirmBootstrapPreview")
def confirm_bootstrap_preview(session_id: str, request: BootstrapConfirmRequest) -> dict:
'''
chunk_endpoint = '''@app.get("/api/v1/sessions/{session_id}/bootstrap-preview-chunk", response_model=BootstrapPreviewChunkResponse, dependencies=[Depends(require_api_key)], operation_id="getBootstrapPreviewChunk")
def get_bootstrap_preview_chunk_action(
    session_id: str,
    preview_id: str = Query(..., description="preview_id returned by createBootstrapPreview/finalizeBootstrapPreview"),
    chunk_index: int = Query(..., ge=0, description="Zero-based preview chunk index."),
) -> dict:
    manager = SessionManager()
    try:
        with _session_request_context(manager, session_id):
            return get_bootstrap_preview_chunk(
                manager,
                session_id,
                preview_id=preview_id,
                chunk_index=chunk_index,
            )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BootstrapPreviewChunkError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


'''
if main.count(confirm_marker) != 1:
    raise RuntimeError("bootstrap confirm marker not found exactly once")
main = main.replace(confirm_marker, chunk_endpoint + confirm_marker, 1)

old_confirm = '''    manager = SessionManager()
    try:
        with _session_request_context(manager, session_id):
            return manager.confirm_bootstrap_preview(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
'''
new_confirm = '''    manager = SessionManager()
    try:
        with _session_request_context(manager, session_id):
            require_complete_bootstrap_preview_delivery(manager, session_id)
            return manager.confirm_bootstrap_preview(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except BootstrapPreviewChunkError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
'''
if main.count(old_confirm) != 1:
    raise RuntimeError("bootstrap confirm implementation not found exactly once")
main = main.replace(old_confirm, new_confirm, 1)

MAIN.write_text(main, encoding="utf-8")
