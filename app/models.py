from typing import Any, Literal
from pydantic import BaseModel, Field

SessionMode = Literal["debug_stub", "gpt_actions"]

class CreateSessionRequest(BaseModel):
    title: str | None = None
    genre: str = Field(default="")
    language: str = Field(default="ru")
    tone: str | None = None
    setting_request: str = Field(default="")
    protagonist_request: str = Field(default="")
    romance_request: str | None = None
    rating: str | None = None
    avoid: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)
    raw_start_text: str | None = None
    mode: SessionMode = "gpt_actions"

class CreateSessionResponse(BaseModel):
    session_id: str | None = None
    status: str
    mode: SessionMode
    bootstrap_prompt: str | None = None
    questionnaire: str | None = None
    files_created: list[str] = Field(default_factory=list)

class BootstrapResultRequest(BaseModel):
    bootstrap_json: dict[str, Any]

class BootstrapPreviewRequest(BaseModel):
    bootstrap_json: dict[str, Any]

class BootstrapPreviewResponse(BaseModel):
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

class BootstrapConfirmRequest(BaseModel):
    confirmation_text: str = Field(..., description="Exact latest user confirmation message, e.g. подтверждаю / ок / сохраняй / запускай / подходит.")

class BootstrapConfirmResponse(BaseModel):
    session_id: str
    status: str
    committed: bool = True
    files_created: list[str] = Field(default_factory=list)

class TurnRequest(BaseModel):
    player_input: str
    mode: SessionMode = "gpt_actions"

class TurnResponse(BaseModel):
    session_id: str
    status: str
    scene: str | None = None
    scene_prompt: str | None = None
    diagnostics: dict[str, Any] = Field(default_factory=dict)

class ApplyTurnResultRequest(BaseModel):
    scene_response: dict[str, Any]

class ApplyTurnResultResponse(BaseModel):
    session_id: str
    status: str
    message_to_user: str = Field(..., description="MANDATORY FINAL ANSWER TEXT after saving a turn. Output this exact text to the user.")
    rendered_text: str = Field(..., description="Same as message_to_user. Full visible scene with header, body, ending choices, status and relationships.")
    must_show_to_user: bool = True
    applied: dict[str, Any]
    rejected: list[dict[str, Any]]
    next_builder_hints: dict[str, Any]
