from typing import Any, Literal
from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    title: str = Field(default="New Novella Session")
    genre: str = Field(default="urban mystery romance")
    player_name: str = Field(default="Noa Hart")


class TurnRequest(BaseModel):
    player_input: str = Field(min_length=1)
    mode: Literal["manual_gpt", "local_stub"] = "manual_gpt"


class ManualResultRequest(BaseModel):
    player_input: str = Field(min_length=1)
    scene_text: str = Field(min_length=1)
    state_update: dict[str, Any] = Field(default_factory=dict)
    knowledge_update: dict[str, Any] = Field(default_factory=dict)
    npc_life_update: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class SessionListItem(BaseModel):
    session_id: str
    title: str
    genre: str
    turn_number: int
    current_location: str | None = None
    current_time: str | None = None
