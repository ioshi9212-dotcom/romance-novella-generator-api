from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"Pattern not found in {path}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


models = ROOT / "app" / "models.py"
replace_once(
    models,
    "from pydantic import BaseModel, ConfigDict, Field\n",
    "from pydantic import BaseModel, ConfigDict, Field, model_validator\n",
)
replace_once(
    models,
    'TimeSkipUnit = Literal["hours", "days", "weeks", "months"]\n',
    'TimeSkipUnit = Literal["hours", "days", "weeks", "months"]\n\n'
    'BOOTSTRAP_ROOT_FIELDS = (\n'
    '    "protagonist",\n'
    '    "characters",\n'
    '    "relationships",\n'
    '    "knowledge",\n'
    '    "story_plan",\n'
    '    "director_bible",\n'
    '    "current_state",\n'
    '    "npc_state",\n'
    '    "future_locks",\n'
    '    "continuity",\n'
    '    "scene_history",\n'
    '    "turns",\n'
    ')\n',
)
replace_once(
    models,
    'class BootstrapPreviewRequest(BaseModel):\n    bootstrap_json: dict[str, Any]\n',
    '''class BootstrapPreviewRequest(BaseModel):
    # Canonical callers send only bootstrap_json. Known root fields are declared
    # as compatibility inputs because Custom GPT may close bootstrap_json early
    # and spill the remaining fields next to it.
    model_config = ConfigDict(extra="forbid")

    bootstrap_json: dict[str, Any] = Field(
        ...,
        description="Entire bootstrap payload. Keep every bootstrap root field inside this object.",
    )
    protagonist: dict[str, Any] | None = None
    characters: dict[str, Any] | None = None
    relationships: dict[str, Any] | None = None
    knowledge: dict[str, Any] | None = None
    story_plan: dict[str, Any] | None = None
    director_bible: dict[str, Any] | None = None
    current_state: dict[str, Any] | None = None
    npc_state: dict[str, Any] | None = None
    future_locks: dict[str, Any] | None = None
    continuity: dict[str, Any] | None = None
    scene_history: list[Any] | None = None
    turns: list[Any] | None = None

    @model_validator(mode="after")
    def fold_spilled_bootstrap_fields(self) -> "BootstrapPreviewRequest":
        merged = dict(self.bootstrap_json or {})
        conflicts: list[str] = []
        for field_name in BOOTSTRAP_ROOT_FIELDS:
            value = getattr(self, field_name)
            if value is None:
                continue
            if field_name in merged and merged[field_name] != value:
                conflicts.append(field_name)
                continue
            merged[field_name] = value
        if conflicts:
            raise ValueError(
                "Conflicting bootstrap fields inside and outside bootstrap_json: "
                + ", ".join(sorted(conflicts))
            )
        self.bootstrap_json = merged
        return self
''',
)

openapi = ROOT / "app" / "novella_openapi_actions.py"
replace_once(
    openapi,
    'def _string_array() -> dict[str, Any]:\n    return {"type": "array", "items": {"type": "string"}}\n',
    '''def _string_array() -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}}


def _bootstrap_compat(schema: dict[str, Any]) -> dict[str, Any]:
    return {
        **schema,
        "deprecated": True,
        "description": "Compatibility recovery only. Canonical callers keep this field inside bootstrap_json.",
    }
''',
)
replace_once(
    openapi,
    '''BOOTSTRAP_PREVIEW_SCHEMA = _schema_obj(
    {
        "bootstrap_json": {"$ref": "#/components/schemas/BootstrapPayload"},
    },
    required=["bootstrap_json"],
)
''',
    '''BOOTSTRAP_PREVIEW_SCHEMA = _schema_obj(
    {
        "bootstrap_json": {
            "$ref": "#/components/schemas/BootstrapPayload",
            "description": "Canonical request field. It must contain the entire bootstrap object and all root fields.",
        },
        "protagonist": _bootstrap_compat(_loose_obj()),
        "characters": _bootstrap_compat(_loose_obj()),
        "relationships": _bootstrap_compat(_loose_obj()),
        "knowledge": _bootstrap_compat(_loose_obj()),
        "story_plan": _bootstrap_compat(_loose_obj()),
        "director_bible": _bootstrap_compat(_loose_obj()),
        "current_state": _bootstrap_compat(_loose_obj()),
        "npc_state": _bootstrap_compat(_loose_obj()),
        "future_locks": _bootstrap_compat(_loose_obj()),
        "continuity": _bootstrap_compat(_loose_obj()),
        "scene_history": _bootstrap_compat({"type": "array", "items": _loose_obj()}),
        "turns": _bootstrap_compat({"type": "array", "items": _loose_obj()}),
    },
    required=["bootstrap_json"],
)
''',
)

instructions = ROOT / "gpt" / "custom_gpt_instructions.md"
replace_once(
    instructions,
    '4. createBootstrapPreview только с bootstrap_json, без mode и других верхнеуровневых полей.\n',
    '4. createBootstrapPreview: session_id + один bootstrap_json со всеми корневыми полями; снаружи ничего не дублируй. UnrecognizedKwargsError → повтори тот же вызов в этой сессии, упаковав всё внутрь bootstrap_json.\n',
)
