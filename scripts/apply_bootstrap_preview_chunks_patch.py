from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one marker in {path}, found {count}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "app/models.py",
    '''class BootstrapPreviewResponse(BaseModel):
    message_to_user: str = Field(..., description="MANDATORY FINAL ANSWER TEXT. Output this exact text to the user. Do not summarize. Do not replace with 'готово'. Do not start a scene.")
    session_id: str
    status: str
    must_show_to_user: bool = True
    wait_for_confirmation: bool = True
    next_user_action: str = "Напиши `подтверждаю`, если всё подходит, или скажи, что изменить."
    preview: str
    user_visible_preview: str
    can_confirm: bool = True
    diagnostics: dict[str, Any] = Field(default_factory=dict)
''',
    '''class BootstrapPreviewResponse(BaseModel):
    message_to_user: str = Field(
        ...,
        description="Full preview when has_more_preview_chunks=false; otherwise chunk 0. For chunked previews, fetch every remaining chunk and concatenate before showing anything to the user.",
    )
    session_id: str
    status: str
    must_show_to_user: bool = True
    wait_for_confirmation: bool = True
    next_user_action: str = "Напиши `подтверждаю`, если всё подходит, или скажи, что изменить."
    preview: str
    user_visible_preview: str
    can_confirm: bool = True
    preview_id: str
    preview_chars: int = Field(ge=0)
    preview_chunk_index: int = Field(default=0, ge=0)
    preview_chunk_count: int = Field(default=1, ge=1)
    has_more_preview_chunks: bool = False
    next_preview_chunk_index: int | None = Field(default=None, ge=0)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class BootstrapPreviewChunkResponse(BaseModel):
    session_id: str
    status: str
    preview_id: str
    preview_chars: int = Field(ge=0)
    chunk_index: int = Field(ge=0)
    chunk_count: int = Field(ge=1)
    preview_chunk: str = Field(..., description="One ordered preview fragment. Do not show it alone; concatenate all chunks in numeric order.")
    has_more: bool
    next_chunk_index: int | None = Field(default=None, ge=0)
    must_show_to_user: bool = False
    ready_to_show_full_preview: bool = False
    can_confirm: bool = False
    diagnostics: dict[str, Any] = Field(default_factory=dict)
''',
)

replace_once(
    "app/session_manager.py",
    "from app.bootstrap_normalizer import normalize_bootstrap_json\n",
    "from app.bootstrap_normalizer import normalize_bootstrap_json\nfrom app.bootstrap_preview_transport import BOOTSTRAP_STAGING_TRANSPORT_RULES, build_bootstrap_preview_response, get_bootstrap_preview_chunk\n",
)
replace_once(
    "app/session_manager.py",
    '        prompt = build_bootstrap_prompt(user_request) + "\\n\\n" + BOOTSTRAP_DIRECTION_RULES\n',
    '        prompt = (\n            build_bootstrap_prompt(user_request)\n            + "\\n\\n"\n            + BOOTSTRAP_DIRECTION_RULES\n            + "\\n\\n"\n            + BOOTSTRAP_STAGING_TRANSPORT_RULES\n        )\n',
)
replace_once(
    "app/session_manager.py",
    '''        return {
            "message_to_user": preview,
            "session_id": session_id,
            "status": "bootstrap_review_pending",
            "must_show_to_user": True,
            "wait_for_confirmation": True,
            "next_user_action": "Напиши `подтверждаю`, если всё подходит, или скажи, что изменить.",
            "preview": preview,
            "user_visible_preview": preview,
            "can_confirm": True,
            "diagnostics": {
                "character_count": len(bootstrap_json.get("characters", {}) or {}),
                "relationship_count": len(bootstrap_json.get("relationships", {}) or {}),
                "knowledge_count": len(bootstrap_json.get("knowledge", {}) or {}),
                "normalized": True,
                "cast_profiles_enabled": True,
                "npc_runtime_enabled": True,
                "directional_relationships_enabled": True,
                "director_bible_enabled": True,
                "event_queue_count": len((bootstrap_json.get("director_bible") or {}).get("event_queue", [])),
            },
        }
''',
    '''        return build_bootstrap_preview_response(
            self.storage,
            session_id,
            preview,
            diagnostics={
                "character_count": len(bootstrap_json.get("characters", {}) or {}),
                "relationship_count": len(bootstrap_json.get("relationships", {}) or {}),
                "knowledge_count": len(bootstrap_json.get("knowledge", {}) or {}),
                "normalized": True,
                "cast_profiles_enabled": True,
                "npc_runtime_enabled": True,
                "directional_relationships_enabled": True,
                "director_bible_enabled": True,
                "event_queue_count": len((bootstrap_json.get("director_bible") or {}).get("event_queue", [])),
            },
        )
''',
)
replace_once(
    "app/session_manager.py",
    '''    def confirm_bootstrap_preview(self, session_id: str) -> dict[str, Any]:
''',
    '''    def get_bootstrap_preview_chunk(
        self,
        session_id: str,
        chunk_index: int,
        *,
        preview_id: str | None = None,
    ) -> dict[str, Any]:
        return get_bootstrap_preview_chunk(
            self.storage,
            session_id,
            chunk_index,
            expected_preview_id=preview_id,
        )

    def confirm_bootstrap_preview(self, session_id: str) -> dict[str, Any]:
''',
)

replace_once(
    "app/main.py",
    "from app.bootstrap_content_repair import repair_bootstrap_content\n",
    "from app.bootstrap_content_repair import repair_bootstrap_content\nfrom app.bootstrap_preview_transport import BootstrapPreviewTransportError\n",
)
replace_once(
    "app/main.py",
    "from app.models import AdvanceTimeRequest, ApplyTurnResultRequest, ApplyTurnResultResponse, BootstrapPreviewRequest, BootstrapPreviewResponse, BootstrapConfirmRequest, BootstrapConfirmResponse, CreateSessionRequest, CreateSessionResponse, DebugSessionDumpResponse, SaveBootstrapPartRequest, SaveBootstrapPartResponse, TurnPromptChunkResponse, TurnRequest, TurnResponse\n",
    "from app.models import AdvanceTimeRequest, ApplyTurnResultRequest, ApplyTurnResultResponse, BootstrapPreviewChunkResponse, BootstrapPreviewRequest, BootstrapPreviewResponse, BootstrapConfirmRequest, BootstrapConfirmResponse, CreateSessionRequest, CreateSessionResponse, DebugSessionDumpResponse, SaveBootstrapPartRequest, SaveBootstrapPartResponse, TurnPromptChunkResponse, TurnRequest, TurnResponse\n",
)
replace_once(
    "app/main.py",
    '            "chunk_endpoint": "getTurnPromptChunk",\n',
    '            "chunk_endpoint": "getTurnPromptChunk",\n            "bootstrap_preview_chunk_endpoint": "getBootstrapPreviewChunk",\n',
)
replace_once(
    "app/main.py",
    '''@app.post("/api/v1/sessions/{session_id}/bootstrap-part", response_model=SaveBootstrapPartResponse, dependencies=[Depends(require_api_key)], operation_id="saveBootstrapPart")
def save_bootstrap_part_action(session_id: str, request: SaveBootstrapPartRequest) -> dict:
''',
    '''@app.get(
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
''',
)

for temporary_path in [
    ROOT / "scripts" / "apply_bootstrap_preview_chunks_patch.py",
    ROOT / ".github" / "workflows" / "apply-bootstrap-preview-chunks.yml",
]:
    if temporary_path.exists():
        temporary_path.unlink()
