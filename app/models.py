from typing import Any, Literal
from pydantic import BaseModel, Field


SessionMode = Literal["local_stub", "manual_gpt", "llm"]


class CreateSessionRequest(BaseModel):
    title: str | None = None
    genre: str = Field(default="romance")
    language: str = Field(default="ru")
    tone: str | None = None
    setting_request: str = Field(default="")
    protagonist_request: str = Field(default="")
    romance_request: str | None = None
    rating: str | None = None
    avoid: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)
    mode: SessionMode = "local_stub"


class CreateSessionResponse(BaseModel):
    session_id: str
    status: str
    mode: SessionMode
    bootstrap_prompt: str | None = None
    files_created: list[str]


class BootstrapResultRequest(BaseModel):
    bootstrap_json: dict[str, Any]


class TurnRequest(BaseModel):
    player_input: str
    mode: SessionMode = "manual_gpt"


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
    applied: dict[str, Any]
    rejected: list[dict[str, Any]]
    next_builder_hints: dict[str, Any]
