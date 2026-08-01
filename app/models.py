from __future__ import annotations

import json
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.config import MAX_QUESTIONNAIRE_CHARS


class SessionStatus(StrEnum):
    QUESTIONNAIRE = "questionnaire"
    CLARIFICATION = "clarification"
    BUILDING = "building"
    REVIEW_PENDING = "review_pending"
    ACTIVE = "active"
    ARCHIVED = "archived"


class TurnMode(StrEnum):
    PLAY = "play"
    TECHNICAL = "technical"
    AUDIT = "audit"


class BootstrapPartType(StrEnum):
    PROFILE = "profile"
    LORE = "lore"
    HIDDEN_CANON = "hidden_canon"
    PLOT = "plot"
    CURRENT = "current"
    CHARACTER = "character"
    REVIEW = "review"


class CreateSessionRequest(BaseModel):
    title: str | None = Field(default=None, max_length=160)


class SessionSummary(BaseModel):
    session_id: str
    resume_code: str
    title: str
    status: SessionStatus
    schema_version: int
    state_version: int
    turn_number: int
    created_at: str
    updated_at: str
    pending_turn_id: str | None = None
    bootstrap_missing: list[str] = Field(default_factory=list)
    bootstrap_warnings: list[str] = Field(default_factory=list)
    questionnaire_entry_count: int = 0
    last_questionnaire_entry_id: str | None = None
    review: dict[str, Any] | None = None
    current_summary: dict[str, Any] | None = None


class QuestionnaireRequest(BaseModel):
    phase: Literal["initial", "clarification"]
    raw_answers: str = Field(min_length=1, max_length=MAX_QUESTIONNAIRE_CHARS)
    normalized: dict[str, Any] = Field(default_factory=dict)
    unknown_fields: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)

    @field_validator("raw_answers", mode="before")
    @classmethod
    def preserve_raw_answers(cls, value: Any) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @field_validator("normalized", mode="before")
    @classmethod
    def tolerate_normalized_json_text(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                return {"unparsed_notes": value}
            if isinstance(decoded, dict):
                return decoded
            return {"value": decoded}
        return {"value": value}

    @field_validator("unknown_fields", "contradictions", mode="before")
    @classmethod
    def tolerate_single_text_item(cls, value: Any) -> list[str]:
        if value is None:
            return []
        items = value if isinstance(value, list) else [value]
        output: list[str] = []
        for item in items:
            if isinstance(item, str):
                text = item.strip()
            else:
                text = json.dumps(item, ensure_ascii=False, separators=(",", ":")).strip()
            if text:
                output.append(text)
        return output


class BootstrapPartRequest(BaseModel):
    part_type: BootstrapPartType
    part_id: str | None = Field(default=None, max_length=80)
    merge: bool = False
    content: dict[str, Any]

    @field_validator("content", mode="before")
    @classmethod
    def parse_json_content(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("content must be a valid JSON object string") from exc
        if not isinstance(decoded, dict):
            raise ValueError("content JSON must decode to an object")
        return decoded

    @model_validator(mode="after")
    def character_requires_id(self) -> "BootstrapPartRequest":
        if self.part_type == BootstrapPartType.CHARACTER and not self.part_id:
            raise ValueError("part_id is required for character")
        if self.part_type != BootstrapPartType.CHARACTER and self.part_id:
            raise ValueError("part_id is only allowed for character")
        return self


class BootstrapSaveResponse(BaseModel):
    status: Literal["saved"]
    part_type: BootstrapPartType
    part_id: str | None = None
    size_chars: int
    merged: bool = False
    warnings: list[str] = Field(default_factory=list)


class BootstrapValidationResponse(BaseModel):
    ready: bool
    missing: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    character_ids: list[str] = Field(default_factory=list)
    director_repairs: list[str] = Field(default_factory=list)
    user_questions: list[str] = Field(default_factory=list)
    next_action: Literal["show_review", "repair_bootstrap", "ask_user"] = "repair_bootstrap"


class PrepareTurnRequest(BaseModel):
    user_input: str = Field(default="", max_length=30000)
    mode: TurnMode = TurnMode.PLAY
    replace_pending: bool = False

    @model_validator(mode="after")
    def play_requires_input(self) -> "PrepareTurnRequest":
        if self.mode == TurnMode.PLAY and not self.user_input.strip():
            raise ValueError("user_input is required in play mode")
        return self


class ContextChunk(BaseModel):
    chunk_index: int
    sections: list[dict[str, Any]]


class PrepareTurnResponse(BaseModel):
    status: Literal["prepared"]
    session_id: str
    turn_id: str
    mode: TurnMode
    base_state_version: int
    input_hash: str
    chunk: ContextChunk
    has_more: bool
    next_chunk_index: int | None = None
    total_chunks: int
    warnings: list[str] = Field(default_factory=list)


class CharacterPatch(BaseModel):
    character_id: str = Field(min_length=1, max_length=80)
    changes: dict[str, Any] = Field(default_factory=dict)


class NewCharacter(BaseModel):
    character_id: str = Field(min_length=1, max_length=80)
    card: dict[str, Any]
    starting_knowledge: list[dict[str, Any]] = Field(default_factory=list)


class KnowledgeEvent(BaseModel):
    character_id: str = Field(min_length=1, max_length=80)
    fact: str = Field(min_length=1, max_length=4000)
    status: Literal[
        "fact",
        "heard_fragment",
        "incomplete_version",
        "mistaken_version",
        "suspicion",
        "lie_believed",
        "corrected",
        "refuted",
        "unknown",
    ]
    source: str = Field(min_length=1, max_length=2000)
    replaces_entry_id: str | None = Field(default=None, max_length=120)


class RelationshipEvent(BaseModel):
    from_character_id: str = Field(min_length=1, max_length=80)
    to_character_id: str = Field(min_length=1, max_length=80)
    metric: str = Field(min_length=1, max_length=80)
    delta: int = Field(ge=-25, le=25)
    reason: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def different_characters(self) -> "RelationshipEvent":
        if self.from_character_id == self.to_character_id:
            raise ValueError("relationship event requires two different characters")
        return self


class PlotlinePatch(BaseModel):
    plotline_id: str = Field(min_length=1, max_length=80)
    changes: dict[str, Any] = Field(default_factory=dict)


class CommitTurnRequest(BaseModel):
    scene_text: str = Field(default="", max_length=20000)
    scene_summary: str = Field(default="", max_length=5000)
    current_patch: dict[str, Any] = Field(default_factory=dict)
    time_advance_minutes: int = Field(default=0, ge=0, le=525600)
    character_patches: list[CharacterPatch] = Field(default_factory=list, max_length=50)
    new_characters: list[NewCharacter] = Field(default_factory=list, max_length=20)
    knowledge_events: list[KnowledgeEvent] = Field(default_factory=list, max_length=100)
    relationship_events: list[RelationshipEvent] = Field(default_factory=list, max_length=100)
    plotline_patches: list[PlotlinePatch] = Field(default_factory=list, max_length=50)
    chronology_event: dict[str, Any] | None = None
    audit_updates: dict[str, Any] = Field(default_factory=dict)


class TurnReceipt(BaseModel):
    status: Literal["committed"]
    session_id: str
    turn_id: str
    mode: TurnMode
    base_state_version: int
    new_state_version: int
    turn_number: int
    scene_number: int | None = None
    changed_files: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    committed_at: str


class AbortTurnRequest(BaseModel):
    reason: str = Field(default="replaced by user request", max_length=1000)


class AbortTurnResponse(BaseModel):
    status: Literal["aborted", "already_committed", "already_aborted"]
    turn_id: str


class ErrorResponse(BaseModel):
    detail: str
    code: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
