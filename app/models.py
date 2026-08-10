from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

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


class CharacterIdentity(OpenModel):
    name: str = Field(min_length=1, max_length=200)
    age: str = Field(min_length=1, max_length=100)
    role: str = Field(min_length=1, max_length=500)
    occupation: str = Field(min_length=1, max_length=500)


class CharacterAppearance(OpenModel):
    height: str = Field(min_length=1, max_length=200)
    build: str = Field(min_length=1, max_length=300)
    hair: str = Field(min_length=1, max_length=300)
    eyes: str = Field(min_length=1, max_length=300)
    face: str = Field(min_length=1, max_length=500)
    skin_and_features: str = Field(min_length=1, max_length=500)
    movement_and_mannerisms: str = Field(min_length=1, max_length=700)
    clothing_style: str = Field(min_length=1, max_length=700)
    distinguishing_details: list[str] = Field(min_length=1, max_length=6)
    visual_impression: str = Field(min_length=1, max_length=500)
    visual_noticeability: Literal[
        "unremarkable", "pleasant", "attractive", "striking", "distinctive"
    ]


class CharacterPersonality(OpenModel):
    outward_mask: str = Field(min_length=1, max_length=700)
    inner_character: str = Field(min_length=1, max_length=1000)
    strengths: list[str] = Field(min_length=1, max_length=8)
    flaws: list[str] = Field(min_length=1, max_length=8)
    temperament: str = Field(min_length=1, max_length=400)
    internal_conflict: str = Field(min_length=1, max_length=1000)
    behavior_under_pressure: str = Field(min_length=1, max_length=700)
    habits: list[str] = Field(min_length=2, max_length=6)
    speech: str = Field(min_length=1, max_length=700)


class CharacterPreferences(OpenModel):
    likes: list[str] = Field(min_length=1, max_length=8)
    dislikes: list[str] = Field(min_length=1, max_length=8)
    likes_in_people: list[str] = Field(min_length=1, max_length=6)
    dislikes_in_people: list[str] = Field(min_length=1, max_length=6)


class CharacterGoals(OpenModel):
    personal: str = Field(min_length=1, max_length=1000)
    immediate: str = Field(min_length=1, max_length=700)
    toward_pov: str = Field(min_length=1, max_length=700)
    story_function: str = Field(min_length=1, max_length=1000)
    possible_arc: str = Field(min_length=1, max_length=1000)


class CharacterCard(OpenModel):
    character_id: SafeId
    card_level: Literal["noticeable", "recurring", "important", "player_defined"]
    origin: Literal["player", "director_setup", "runtime"]
    card_hint: str = Field(min_length=1, max_length=3_000)
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
    identity: CharacterIdentity
    appearance: CharacterAppearance
    immediate_scene_goal: str = Field(min_length=1, max_length=700)
    personality: CharacterPersonality | None = None
    preferences: CharacterPreferences | None = None
    biography: list[str] = Field(default_factory=list, max_length=12)
    skills: list[str] = Field(default_factory=list, max_length=12)
    goals: CharacterGoals | None = None
    hidden_motives: list[str] = Field(default_factory=list, max_length=8)
    secrets: list[str] = Field(default_factory=list, max_length=8)
    constraints: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def validate_depth_for_level(self) -> "CharacterCard":
        if self.origin == "player" and self.card_level != "player_defined":
            raise ValueError("player-origin characters must use player_defined card_level")
        if self.card_level == "player_defined" and self.origin != "player":
            raise ValueError("player_defined card_level is reserved for player-origin characters")
        if self.card_level in {"important", "player_defined"}:
            missing = [
                name
                for name, value in (
                    ("personality", self.personality),
                    ("preferences", self.preferences),
                    ("goals", self.goals),
                )
                if value is None
            ]
            if missing:
                raise ValueError(
                    "important and player-defined cards require: " + ", ".join(missing)
                )
            if not self.biography:
                raise ValueError("important and player-defined cards require biography")
            if not self.constraints:
                raise ValueError("important and player-defined cards require constraints")
        if self.card_level == "recurring" and (self.personality is None or self.goals is None):
            raise ValueError("recurring cards require personality and goals")
        return self


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


class LocationCanon(OpenModel):
    name: str = Field(min_length=1, max_length=300)
    purpose: str = Field(min_length=1, max_length=500)
    scale: str = Field(min_length=1, max_length=300)
    layout: str = Field(min_length=1, max_length=1200)
    zones: list[str] = Field(min_length=1, max_length=20)
    visual_style: str = Field(min_length=1, max_length=700)
    condition: str = Field(min_length=1, max_length=500)
    color_palette: list[str] = Field(min_length=1, max_length=10)
    materials: list[str] = Field(min_length=1, max_length=10)
    lighting: str = Field(min_length=1, max_length=700)
    windows_and_view: str = Field(min_length=1, max_length=700)
    entrances: list[str] = Field(min_length=1, max_length=12)
    permanent_objects: list[str] = Field(default_factory=list, max_length=30)
    signature_details: list[str] = Field(min_length=1, max_length=10)


class LocationCard(OpenModel):
    canon: LocationCanon
    current_changes: list[str] = Field(default_factory=list, max_length=30)
    access: list[str] = Field(default_factory=list, max_length=20)
    damage_or_modifications: list[str] = Field(default_factory=list, max_length=20)


class LocationBundle(BaseModel):
    location_id: SafeId
    state: LocationCard


class DirectorPlan(OpenModel):
    active_threads: list[dict[str, Any]] = Field(default_factory=list)
    character_agendas: list[dict[str, Any]] = Field(default_factory=list)
    event_windows: list[dict[str, Any]] = Field(default_factory=list)
    collision_points: list[dict[str, Any]] = Field(default_factory=list)
    offscreen_events: list[dict[str, Any]] = Field(default_factory=list)
    consequences_without_pov: list[dict[str, Any]] = Field(default_factory=list)
    possible_pov_contacts: list[dict[str, Any]] = Field(default_factory=list)


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
    director_plan: DirectorPlan = Field(
        description=(
            "Flexible director-only plan: independent character agendas, event windows, "
            "collisions and consequences that can happen without POV."
        )
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
    card_change_reason: str | None = Field(default=None, min_length=1, max_length=1000)
    current_state: dict[str, Any] | None = None
    relationships: dict[str, Any] | None = None
    knowledge: dict[str, Any] | None = None


class LocationUpdate(BaseModel):
    location_id: SafeId
    state: LocationCard
    canon_change_reason: str | None = Field(default=None, min_length=1, max_length=1000)


class ObjectUpdate(BaseModel):
    object_id: SafeId
    state: dict[str, Any]


class RuntimeStateUpdates(BaseModel):
    novel: dict[str, Any] | None = None
    hidden_lore: dict[str, Any] | None = None
    plot_state: dict[str, Any] | None = None
    director_plan: DirectorPlan | None = None
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
