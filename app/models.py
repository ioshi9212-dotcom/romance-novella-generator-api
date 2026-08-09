from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

SafeId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    ),
]


class OpenModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class CharacterCard(OpenModel):
    character_id: SafeId
    card_hint: str = Field(min_length=1, max_length=700)
    record_status: Literal["active", "inactive"]
    story_status: Literal[
        "not_introduced",
        "active",
        "offstage",
        "missing",
        "dead",
        "retired",
    ]
    player_visibility: Literal["hidden", "partial", "visible"]


class CharacterBundle(BaseModel):
    character_id: SafeId
    card: CharacterCard = Field(description="Relatively stable character card.")
    current_state: dict[str, Any] = Field(
        default_factory=dict,
        description="Frequently changing location, condition, goal, intention and activity.",
    )
    relationships: dict[str, Any] = Field(
        default_factory=dict,
        description="Relationships owned by this character and directed toward targets.",
    )
    knowledge: dict[str, Any] = Field(
        default_factory=dict,
        description="Only facts, partial facts and wrong beliefs known by this character.",
    )


class LocationBundle(BaseModel):
    location_id: SafeId
    state: dict[str, Any] = Field(default_factory=dict)


class ObjectBundle(BaseModel):
    object_id: SafeId
    state: dict[str, Any] = Field(default_factory=dict)


class CreateSessionRequest(BaseModel):
    player_confirmation: str = Field(
        min_length=1,
        max_length=500,
        description="Copy the player's actual message containing the positive word «подтверждаю».",
    )
    novel: dict[str, Any] = Field(
        description="Confirmed title, genre, style, POV and format settings for this novella."
    )
    hidden_lore: dict[str, Any] = Field(
        description="Director-only truths, secrets and reveal conditions; never player preview text."
    )
    plot_state: dict[str, Any] = Field(
        description="Active lines, open threads, pending consequences and resolved compact history."
    )
    world_state: dict[str, Any] = Field(
        description="Global time, offscreen actions, whereabouts, dangers and location availability."
    )
    scene_state: dict[str, Any] = Field(
        description="Exact current frame: place, people, objects and unfinished moment to continue."
    )
    characters: list[CharacterBundle] = Field(
        min_length=1,
        description="Every confirmed card character, including POV and hidden future characters.",
    )
    locations: list[LocationBundle] = Field(default_factory=list)
    objects: list[ObjectBundle] = Field(default_factory=list)


class CreateSessionResponse(BaseModel):
    session_id: str
    status: Literal["active"]
    state_revision: int
    next_turn_number: int
    cycle_position: int
    next_required_action: str


class TurnPacketRequest(BaseModel):
    player_input: str = Field(min_length=1, max_length=20_000)
    mode: Literal["new", "revise_last"] = Field(
        default="new",
        description="Use new for the next turn; use revise_last to replace the last scene without incrementing turn.",
    )
    client_request_id: SafeId | None = None


class PacketChunkResponse(BaseModel):
    session_id: str
    packet_id: str
    packet_type: Literal["turn", "audit"]
    chunk_index: int
    chunk_count: int
    content: str
    content_sha256: str
    has_more: bool
    next_chunk_index: int | None
    next_required_action: str


class ChronologyEventInput(BaseModel):
    scene_id: SafeId
    story_datetime: str
    location_id: SafeId | None = None
    participants_present: list[SafeId] = Field(default_factory=list)
    event: str = Field(min_length=1, max_length=3000)
    consequences: list[str] = Field(default_factory=list)
    knowledge_update_refs: list[str] = Field(default_factory=list)
    minor_npcs: list[dict[str, Any]] = Field(default_factory=list)
    supersedes_event_id: SafeId | None = None


class CharacterUpdate(BaseModel):
    character_id: SafeId
    card: CharacterCard | None = None
    current_state: dict[str, Any] | None = None
    relationships: dict[str, Any] | None = None
    knowledge: dict[str, Any] | None = None


class LocationUpdate(BaseModel):
    location_id: SafeId
    state: dict[str, Any]


class ObjectUpdate(BaseModel):
    object_id: SafeId
    state: dict[str, Any]


class RuntimeStateUpdates(BaseModel):
    novel: dict[str, Any] | None = None
    hidden_lore: dict[str, Any] | None = None
    plot_state: dict[str, Any] | None = None
    world_state: dict[str, Any] | None = None
    scene_state: dict[str, Any] | None = None
    characters: list[CharacterUpdate] = Field(default_factory=list)
    locations: list[LocationUpdate] = Field(default_factory=list)
    objects: list[ObjectUpdate] = Field(default_factory=list)


class CommitTurnRequest(BaseModel):
    turn_id: SafeId
    expected_state_revision: int = Field(ge=1)
    scene_output: str = Field(min_length=1, max_length=80_000)
    summary: str = Field(min_length=1, max_length=3000)
    scene_id: SafeId
    story_datetime: str
    events: list[ChronologyEventInput] = Field(
        default_factory=list,
        description="Compact established facts for chronology, never a copy of the whole scene.",
    )
    state_updates: RuntimeStateUpdates = Field(
        default_factory=RuntimeStateUpdates,
        description="Only documents changed by this scene; omitted documents remain unchanged.",
    )
    displayed_state_changes: dict[str, Any] = Field(
        default_factory=dict,
        description="The state and relationship changes actually printed in the scene footer.",
    )


class CommitTurnResponse(BaseModel):
    session_id: str
    turn_id: str
    turn_number: int
    turn_revision: int
    state_revision: int
    last_completed_turn: int
    last_audited_turn: int
    next_turn_number: int
    next_cycle_position: int | None
    audit_required: bool
    next_required_action: str


class AuditChecklist(BaseModel):
    events_and_consequences: bool
    time_and_movement: bool
    scene_and_physical_state: bool
    character_current_states: bool
    character_continuity: bool
    minor_npc_lifecycle: bool
    knowledge_sources: bool
    knowledge_boundaries: bool
    directional_relationships: bool
    plot_threads: bool
    hidden_lore_and_reveal_timing: bool
    compaction_and_duplicates: bool


class ChronologyCorrectionInput(ChronologyEventInput):
    turn_number: int = Field(ge=1)
    supersedes_event_id: SafeId


class ChronologyCompactionInput(ChronologyEventInput):
    turn_number: int = Field(ge=1)
    compacts_event_ids: list[SafeId] = Field(
        min_length=1,
        description="Existing active events replaced in runtime context by this compact summary.",
    )
    supersedes_event_id: None = None


class CommitAuditRequest(BaseModel):
    audit_id: SafeId
    expected_state_revision: int = Field(ge=1)
    checklist: AuditChecklist
    findings: dict[str, Any] = Field(
        default_factory=dict,
        description="What was missing, corrected, compacted, closed or promoted during the audit.",
    )
    state_updates: RuntimeStateUpdates = Field(
        default_factory=RuntimeStateUpdates,
        description="Compacted replacements for current state documents; history must not be erased.",
    )
    chronology_corrections: list[ChronologyCorrectionInput] = Field(
        default_factory=list,
        description="Corrective events that explicitly supersede inaccurate chronology events.",
    )
    chronology_compactions: list[ChronologyCompactionInput] = Field(
        default_factory=list,
        description=(
            "Compact summaries that hide repetitive source events from future packets while "
            "preserving the original records in Railway."
        ),
    )


class CommitAuditResponse(BaseModel):
    session_id: str
    audit_id: str
    audit_complete: bool
    audited_turn_from: int
    audited_turn_to: int
    state_revision: int
    last_audited_turn: int
    audit_required: bool
    next_turn_number: int
    next_cycle_position: int | None
    next_required_action: str


class ChronologyPageResponse(BaseModel):
    session_id: str
    cursor: int
    events: list[dict[str, Any]]
    include_inactive: bool
    has_more: bool
    next_cursor: int | None
