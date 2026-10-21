"""Novel creation and RAW persistence. No narrative generation or scene rules."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

import fcntl
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .response_chunks import present, read_chunk
from .storage_paths import storage_root, storage_diagnostics
from .initial_state import canonicalize_initial_state
from .initial_relationships import verify_initial_relationship_review
from .raw_file_transfer import fetch_openai_file, repair_placeholder, placeholder_events, reject_placeholder
from .raw_chunk_transfer import ingest_part

app = FastAPI(title="Novella Generator API", version="0.6.6")

PHASES = ("сбор", "вопросы", "готово_к_записи", "запись_и_сверка", "готово_к_игре")
CORE = {
    "анкета.json", "персонажи.json", "state.json", "хронология.json",
    "скрытый_лор_и_крючки.json", "отношения.json", "локации.json",
}
IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
MAX_RELATIONSHIP_PARAMETERS = 10


class CreateNovel(BaseModel):
    request_id: str | None = Field(default=None, min_length=1, max_length=120)
    initial_text: str = ""


class RawPart(BaseModel):
    event_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    text: str = Field(min_length=1)
    question: str | None = None
    file_name: str | None = None


class RawFileInput(BaseModel):
    # GPT Actions populates this special array with file reference dictionaries.
    openaiFileIdRefs: list[Any] = Field(min_length=1, max_length=1)
    event_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,80}$")
    expected_bytes: int | None = Field(default=None, ge=1, le=5 * 1024 * 1024)
    expected_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class RawChunkInput(BaseModel):
    # Byte-preserving GPT Actions fallback when openaiFileIdRefs is only /mnt/data/...
    event_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    mode: Literal["append", "recover", "repair"] = "append"
    part_index: int = Field(ge=0)
    total_parts: int = Field(ge=1, le=427)
    chunk_b64: str = Field(min_length=1, max_length=16384)
    expected_bytes: int = Field(ge=1, le=5 * 1024 * 1024)
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    file_name: str | None = None


class StageCommand(BaseModel):
    command: Literal["подтверждаю", "вопросов_больше_нет"]


class SaveDocument(BaseModel):
    path: str
    document: dict[str, Any]


class PrepareTurn(BaseModel):
    user_input: str = ""
    additional_character_ids: list[str] = Field(default_factory=list)
    selected_hook_indices: list[int] = Field(default_factory=list)
    selected_secret_indices: list[int] = Field(default_factory=list)
    additional_location_ids: list[str] = Field(default_factory=list)
    full_memory_character_ids: list[str] = Field(default_factory=list)
    full_chronology: bool = False


class PatchOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["set", "append", "remove", "merge_by_id"]
    path: str
    value: Any = None

    @model_validator(mode="after")
    def require_patch_value(self):
        if self.op in {"set", "append", "merge_by_id"} and "value" not in self.model_fields_set:
            raise ValueError("set/append/merge_by_id operations require an explicit value")
        return self


class RelationshipException(BaseModel):
    """Explicit exception to the normal 0–3 relationship movement per turn."""
    model_config = ConfigDict(extra="forbid")
    owner_id: str = Field(min_length=1)
    parameter: str = Field(min_length=1)
    reason: str = Field(min_length=12)


class RelationshipChange(BaseModel):
    """A causal scene-level delta, evaluated by GPT, applied by the server."""
    model_config = ConfigDict(extra="forbid")
    owner_id: str = Field(min_length=1)
    parameter: str = Field(min_length=1)
    delta: int | None = Field(default=None, ge=-100, le=100)
    initial_value: int | None = Field(default=None, ge=1, le=100)

    @model_validator(mode="after")
    def change_mode(self):
        if (self.delta is None) == (self.initial_value is None):
            raise ValueError("Choose exactly one of delta (existing axis) or initial_value (new axis)")
        if self.delta == 0:
            raise ValueError("Zero delta is not a change; omit this row")
        return self


class HeardStatement(BaseModel):
    """A verbatim assertion heard by one NPC, never a verified world truth."""
    model_config = ConfigDict(extra="forbid")
    listener_id: str = Field(min_length=1)
    speaker_id: str = Field(min_length=1)
    quote: str = Field(min_length=1)


class CommitTurn(BaseModel):
    turn_id: str
    user_input: str = ""
    context_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    scene: str = Field(min_length=1)
    updates: dict[str, list[PatchOperation]] = Field(default_factory=dict)
    relationship_changes: list[RelationshipChange] = Field(default_factory=list)
    heard_statements: list[HeardStatement] = Field(default_factory=list)
    relationship_exceptions: list[RelationshipException] = Field(default_factory=list)
    additional_character_ids: list[str] = Field(default_factory=list)
    selected_hook_indices: list[int] = Field(default_factory=list)
    selected_secret_indices: list[int] = Field(default_factory=list)
    additional_location_ids: list[str] = Field(default_factory=list)
    full_memory_character_ids: list[str] = Field(default_factory=list)
    full_chronology: bool = False


class AuditPrepare(BaseModel):
    character_ids: list[str] = Field(default_factory=list)


class AuditCommit(BaseModel):
    through_turn: int = Field(ge=1)
    audit_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    character_ids: list[str] = Field(default_factory=list)
    reviewed_against_archive: bool = False
    findings: list[str] = Field(default_factory=list)
    evidence_turns: dict[str, list[int]] = Field(default_factory=dict)
    updates: dict[str, list[PatchOperation]] = Field(default_factory=dict)


class RollbackTurn(BaseModel):
    expected_turn_id: str = Field(min_length=1)


class CompactionCommit(BaseModel):
    through_turn: int = Field(ge=60)
    review_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    reviewed_against_archive: bool = False
    world_summary: str = Field(min_length=1)
    character_summaries: dict[str, str] = Field(default_factory=dict)


class VerifyNovel(BaseModel):
    audited_against_raw: bool = False
    unresolved_issues: list[str] = Field(default_factory=list)


def server_namespace() -> str:
    """Private persistent random namespace for retry-safe request IDs.

    This is generated by the server on first use; no API key or user
    configuration is required. Random namespace prevents predictable UUID5
    session IDs even when someone guesses the public request_id.
    """
    data_root = storage_root()
    data_root.mkdir(parents=True, exist_ok=True)
    marker = data_root / ".session_namespace"
    with (data_root / ".session_namespace.lock").open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            if marker.is_file():
                secret = marker.read_text(encoding="ascii").strip()
                if not re.fullmatch(r"[0-9a-f]{32}", secret):
                    raise HTTPException(503, "Invalid private session namespace on disk")
                return secret
            secret = uuid.uuid4().hex
            fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w", encoding="ascii") as out:
                out.write(secret + "\n")
                out.flush()
                os.fsync(out.fileno())
            return secret
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def session_dir(session_id: uuid.UUID) -> Path:
    return storage_root() / "sessions" / str(session_id)


@contextmanager
def locked(folder: Path, *, create: bool = False):
    # A read of an unknown session must not generate a ghost directory.
    # Never overwrite partial/raw data with a newly invented session.
    if create:
        folder.mkdir(parents=True, exist_ok=True)
    elif not (folder / "сессия.json").is_file():
        if folder.is_dir() and any(item.name != ".lock" for item in folder.iterdir()):
            raise HTTPException(
                503, "SESSION_METADATA_MISSING: Session files remain but "
                "сессия.json is missing. Preserve this directory for recovery."
            )
        raise HTTPException(
            404, "SESSION_NOT_FOUND: Session is absent from persistent storage. "
            "Check session_id and Amvera Data volume; do not start a replacement automatically."
        )
    with (folder / ".lock").open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            from .turn_commit import recover_pending
            from .turn_maintenance import recover_maintenance
            recover_pending(folder)
            recover_maintenance(folder)
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".tmp_")
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def load(folder: Path) -> dict[str, Any]:
    path = folder / "сессия.json"
    if not path.is_file():
        raise HTTPException(404, "Session not found")
    return json.loads(path.read_text(encoding="utf-8"))


def summary(meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": meta["id"],
        "этап": meta["этап"],
        "последний_ход": meta["последний_ход"],
        "источников": len(meta.get("_raw_receipts", {})),
        "последнее_сжатие": int(meta.get("last_compacted_turn", 0)),
        "сжатие_требуется": (int(meta.get("последний_ход", 0)) > 0 and
                              int(meta.get("последний_ход", 0)) % 60 == 0 and
                              int(meta.get("last_compacted_turn", 0)) < int(meta.get("последний_ход", 0))),
        "аудит_по_ход": int(meta.get("last_audited_turn", 0)),
        "аудит_требуется": int(meta.get("последний_ход", 0)) >= 15 and (
            (int(meta.get("последний_ход", 0)) // 15) * 15 > int(meta.get("last_audited_turn", 0))
        ),
    }


def source_digest(part: RawPart) -> str:
    source = [part.text, part.question, part.file_name]
    return hashlib.sha256(json.dumps(source, ensure_ascii=False).encode("utf-8")).hexdigest()


def append_source(folder: Path, meta: dict[str, Any], part: RawPart, *, allow_recovery: bool = False) -> None:
    reject_placeholder(part.text)
    receipts = meta.setdefault("_raw_receipts", {})
    digest = source_digest(part)
    previous = receipts.get(part.event_id)
    if previous is not None:
        if previous != digest:
            raise HTTPException(409, "event_id was already used for different material")
        return
    if meta["этап"] not in ("сбор", "вопросы"):
        if not (allow_recovery and meta["этап"] in ("готово_к_записи", "запись_и_сверка")
                and int(meta.get("последний_ход", 0)) == 0):
            raise HTTPException(409, "RAW intake is closed at this stage")
    raw_file = folder / "raw.txt"
    marker = f"===== RAW {part.event_id} {digest} =====\n"
    # Recover safely if the RAW append succeeded but metadata write was interrupted.
    if raw_file.exists():
        text = raw_file.read_bytes().decode("utf-8")
        for line in text.splitlines(keepends=True):
            if line.startswith(f"===== RAW {part.event_id} "):
                if line != marker:
                    raise HTTPException(409, "event_id was already used for different material")
                receipts[part.event_id] = digest
                atomic_json(folder / "сессия.json", meta)
                return
    header = ""
    if part.file_name is not None:
        header += "Файл: " + json.dumps(part.file_name, ensure_ascii=False) + "\n"
    if part.question is not None:
        header += "Вопрос: " + json.dumps(part.question, ensure_ascii=False) + "\n"
    # The original text is preserved verbatim between source markers.
    block = "\n" + marker + header + part.text + "\n===== END RAW " + part.event_id + " =====\n"
    with raw_file.open("ab") as stream:
        stream.write(block.encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())
    receipts[part.event_id] = digest
    atomic_json(folder / "сессия.json", meta)


def valid_path(path: str) -> bool:
    if path in CORE:
        return True
    pieces = path.split("/")
    return (
        len(pieces) == 2 and pieces[0] in {"карточки", "память"}
        and pieces[1].endswith(".json")
        and bool(IDENTIFIER.fullmatch(pieces[1][:-5]))
    )


def read_data(folder: Path, path: str) -> dict[str, Any]:
    if not valid_path(path):
        raise HTTPException(400, "Invalid novel document path")
    destination = folder / path
    if not destination.is_file():
        raise HTTPException(404, f"Missing document: {path}")
    try:
        data = json.loads(destination.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(409, f"Unreadable document: {path}") from exc
    if not isinstance(data, dict):
        raise HTTPException(422, f"Document must be a JSON object: {path}")
    return data


def validate_foundation(folder: Path, *, state_override: dict[str, Any] | None = None) -> list[str]:
    issues: list[str] = []
    docs: dict[str, dict[str, Any]] = {}
    for name in sorted(CORE):
        try:
            docs[name] = read_data(folder, name)
        except HTTPException:
            issues.append("Не сохранён или повреждён " + name)
    if issues:
        return issues
    if state_override is not None:
        docs["state.json"] = state_override

    roster = docs["персонажи.json"].get("персонажи")
    if not isinstance(roster, list) or not roster:
        return ["Нет списка персонажей"]
    known: set[str] = set()
    for record in roster:
        if not isinstance(record, dict) or not isinstance(record.get("id"), str):
            issues.append("В реестре запись без ID")
            continue
        cid = record["id"]
        if not IDENTIFIER.fullmatch(cid) or cid in known:
            issues.append("Некорректный или повторный ID: " + cid)
            continue
        known.add(cid)
        for subdir, idkey in (("карточки", "id"), ("память", "персонаж_id")):
            try:
                personal = read_data(folder, f"{subdir}/{cid}.json")
            except HTTPException:
                issues.append(f"Отсутствует {subdir}/{cid}.json")
                continue
            if personal.get(idkey) != cid:
                issues.append(f"Не совпадает ID в {subdir}/{cid}.json")
    scene = docs["state.json"]
    pov_id = scene.get("pov_id")
    if not isinstance(pov_id, str) or pov_id not in known:
        issues.append("POV отсутствует в реестре или state.json")
    present = scene.get("физически")
    if not isinstance(present, list) or not any(
        isinstance(x, dict) and x.get("id") == pov_id for x in present
    ):
        observed = (
            [x.get("id", x.get("имя", "?")) if isinstance(x, dict) else x for x in present]
            if isinstance(present, list) else type(present).__name__
        )
        issues.append(
            "POV должен быть физически присутствующим в начальном State; "
            f"state.pov_id={pov_id!r}, физически={observed!r}. "
            'Укажи физически: [{"id": "тот_же_ID_из_реестра"}].'
        )
    for channel in ("физически", "удалённо"):
        for row in scene.get(channel, []) if isinstance(scene.get(channel), list) else []:
            if not isinstance(row, dict) or row.get("id") not in known:
                issues.append(f"Неизвестный участник в State: {channel}")

    rel = docs["отношения.json"]
    if rel.get("pov_id") != pov_id:
        issues.append("pov_id различается в State и отношениях")
    owners = rel.get("персонажи")
    if not isinstance(owners, dict):
        issues.append("Отношения: персонажи должны быть объектом")
    else:
        if pov_id in owners:
            issues.append("Нельзя хранить отношения от имени POV")
        for owner, record in owners.items():
            if owner not in known or not isinstance(record, dict):
                issues.append(f"Неизвестный владелец отношений: {owner}")
                continue
            pov_relation = record.get("к_POV", {})
            if not isinstance(pov_relation, dict):
                issues.append(f"Некорректные отношения к POV: {owner}")
                continue
            metrics = pov_relation.get("параметры", {})
            if not isinstance(metrics, dict):
                issues.append(f"Некорректные числовые параметры: {owner}")
            else:
                if len(metrics) > MAX_RELATIONSHIP_PARAMETERS:
                    issues.append(f"Слишком много параметров отношений {owner}: максимум {MAX_RELATIONSHIP_PARAMETERS}")
                for metric, value in metrics.items():
                    if not isinstance(metric, str) or not metric.strip() or (
                        isinstance(value, bool) or not isinstance(value, (int, float))
                        or not 0 <= value <= 100
                    ):
                        issues.append(f"Некорректная шкала отношений {owner}: {metric}")
            npc_relations = record.get("к_другим_NPC") or {}
            if not isinstance(npc_relations, dict):
                issues.append(f"Связи с другими NPC должны быть объектом: {owner}")
            else:
                for target, description in npc_relations.items():
                    if target not in known or target == pov_id or not isinstance(description, str):
                        issues.append(f"Некорректная словесная связь NPC к NPC {owner} → {target}")
    return issues


@app.get("/health")
def health() -> dict[str, Any]:
    # An accessible API process is not healthy unless its storage is usable.
    return {"ok": True, "storage": storage_diagnostics()}


@app.get("/runtime")
def get_runtime_instructions(known_sha256: str | None = None) -> dict[str, Any]:
    """Return current technical Rules and Skin Builder only when their version changed."""
    from .runtime_docs import read_runtime

    active = read_runtime()
    changed = active["sha256"] != known_sha256
    return present({
        "sha256": active["sha256"],
        "changed": changed,
        "rules": active["rules"] if changed else "",
        "skin_builder": active["skin_builder"] if changed else "",
    }, "runtime")



@app.get("/chunks/{read_id}/{chunk_index}")
def get_response_chunk(read_id: str, chunk_index: int) -> dict[str, Any]:
    """Read one immutable response fragment without rebuilding context."""
    return read_chunk(read_id, chunk_index)


@app.post("/sessions")
def create_novel(payload: CreateNovel) -> dict[str, Any]:
    if payload.initial_text:
        reject_placeholder(payload.initial_text)
    session_id = (uuid.uuid5(uuid.NAMESPACE_URL, server_namespace() + ":" + payload.request_id)
                  if payload.request_id else uuid.uuid4())
    folder = session_dir(session_id)
    with locked(folder, create=True):
        if (folder / "сессия.json").exists():
            meta = load(folder)
            if payload.initial_text and meta.get("_initial_text_digest") != hashlib.sha256(payload.initial_text.encode()).hexdigest():
                raise HTTPException(409, "request_id already belongs to a different initial text")
            if payload.initial_text and "initial" not in meta.get("_raw_receipts", {}):
                append_source(folder, meta, RawPart(event_id="initial", text=payload.initial_text))
            return summary(meta)
        meta: dict[str, Any] = {"id": str(session_id), "этап": "сбор", "последний_ход": 0, "_raw_receipts": {}, "_initial_text_digest": hashlib.sha256(payload.initial_text.encode()).hexdigest()}
        atomic_json(folder / "сессия.json", meta)
        if payload.initial_text:
            append_source(folder, meta, RawPart(event_id="initial", text=payload.initial_text))
        return summary(meta)


@app.get("/sessions/{session_id}")
def get_session(session_id: uuid.UUID) -> dict[str, Any]:
    folder = session_dir(session_id)
    with locked(folder):
        return summary(load(folder))


@app.post("/sessions/{session_id}/raw")
def add_raw(session_id: uuid.UUID, part: RawPart) -> dict[str, Any]:
    folder = session_dir(session_id)
    with locked(folder):
        meta = load(folder)
        append_source(folder, meta, part)
        return summary(meta)


@app.post("/sessions/{session_id}/raw/file")
def append_raw_file(session_id: uuid.UUID, payload: RawFileInput) -> dict[str, Any]:
    """Stream an actual ChatGPT TXT attachment into RAW, without model transcription."""
    text, name, size, sha = fetch_openai_file(payload.openaiFileIdRefs)
    if payload.expected_bytes is not None and payload.expected_bytes != size:
        raise HTTPException(409, "RAW file byte count mismatch; nothing was written")
    if payload.expected_sha256 is not None and payload.expected_sha256 != sha:
        raise HTTPException(409, "RAW file SHA-256 mismatch; nothing was written")
    if not payload.event_id:
        raise HTTPException(422, "event_id is required when adding a new RAW source")
    folder = session_dir(session_id)
    with locked(folder):
        meta = load(folder)
        append_source(folder, meta, RawPart(event_id=payload.event_id, text=text, file_name=name))
        return {**summary(meta), "event_id": payload.event_id, "bytes": size, "sha256": sha}


@app.post("/sessions/{session_id}/raw/repair-file")
def repair_raw_file(session_id: uuid.UUID, payload: RawFileInput) -> dict[str, Any]:
    """Replace only a corrupted placeholder using the entire original TXT attachment."""
    text, _name, size, sha = fetch_openai_file(payload.openaiFileIdRefs)
    if payload.expected_bytes is not None and payload.expected_bytes != size:
        raise HTTPException(409, "RAW file byte count mismatch; nothing was written")
    if payload.expected_sha256 is not None and payload.expected_sha256 != sha:
        raise HTTPException(409, "RAW file SHA-256 mismatch; nothing was written")
    folder = session_dir(session_id)
    with locked(folder):
        meta = load(folder)
        result = repair_placeholder(
            folder, meta, event_id=payload.event_id, text=text, byte_count=size,
            sha256=sha, atomic_json=atomic_json, source_digest=source_digest, RawPart=RawPart
        )
        return {**summary(meta), **result}


@app.post("/sessions/{session_id}/raw/chunk")
def append_raw_chunk(session_id: uuid.UUID, payload: RawChunkInput) -> dict[str, Any]:
    """Backup transport using verified base64 chunks copied from actual file bytes."""
    folder = session_dir(session_id)
    with locked(folder):
        meta = load(folder)
        result = ingest_part(
            folder, meta, payload, append_source=append_source,
            repair_placeholder=repair_placeholder, RawPart=RawPart,
            source_digest=source_digest, atomic_json=atomic_json,
        )
        return {**summary(meta), **result}


@app.get("/sessions/{session_id}/raw")
def get_raw(session_id: uuid.UUID) -> dict[str, Any]:
    folder = session_dir(session_id)
    with locked(folder):
        load(folder)
        path = folder / "raw.txt"
        return present({"raw": path.read_bytes().decode("utf-8") if path.exists() else ""}, "raw")


@app.post("/sessions/{session_id}/advance")
def advance(session_id: uuid.UUID, payload: StageCommand) -> dict[str, Any]:
    folder = session_dir(session_id)
    with locked(folder):
        meta = load(folder)
        phase = meta["этап"]
        if phase == "сбор" and payload.command == "подтверждаю" and meta.get("_raw_receipts"):
            meta["этап"] = "вопросы"
        elif phase == "вопросы" and payload.command == "вопросов_больше_нет":
            meta["этап"] = "готово_к_записи"
        elif phase == "готово_к_записи" and payload.command == "подтверждаю":
            meta["этап"] = "запись_и_сверка"
        else:
            raise HTTPException(409, f"Command {payload.command!r} is not valid in stage {phase!r}")
        atomic_json(folder / "сессия.json", meta)
        return summary(meta)


@app.put("/sessions/{session_id}/data")
def put_document(session_id: uuid.UUID, payload: SaveDocument) -> dict[str, str]:
    if not valid_path(payload.path):
        raise HTTPException(400, "Invalid document path")
    folder = session_dir(session_id)
    with locked(folder):
        meta = load(folder)
        if meta["этап"] != "запись_и_сверка":
            # Correct a botched initial relationship summary in a VERIFIED novel,
            # but only before the first archived game turn. Never rewrite past
            # gameplay or permit editing arbitrary canon after verification.
            if not (
                meta["этап"] == "готово_к_игре"
                and int(meta["последний_ход"]) == 0
                and payload.path == "отношения.json"
            ):
                raise HTTPException(409, "Novel files can only be written during creation review")
            from .turn_commit import verify_overlay
            problems = verify_overlay(
                folder, {"отношения.json": payload.document}, validate_foundation
            )
            roster = read_data(folder, "персонажи.json").get("персонажи")
            state = read_data(folder, "state.json")
            if not isinstance(roster, list):
                problems.append("Character registry is invalid")
            else:
                problems += verify_initial_relationship_review(
                    folder, roster, payload.document, state.get("pov_id", "")
                )
            if problems:
                raise HTTPException(409, {
                    "code": "RELATIONSHIP_REVIEW_REQUIRED",
                    "issues": problems,
                })
        atomic_json(folder / payload.path, payload.document)
        return {"path": payload.path, "status": "saved"}


@app.get("/sessions/{session_id}/data")
def get_document(session_id: uuid.UUID, path: str) -> dict[str, Any]:
    folder = session_dir(session_id)
    with locked(folder):
        load(folder)
        return present({"path": path, "document": read_data(folder, path)}, "document")


@app.post("/sessions/{session_id}/verify")
def verify_novel(session_id: uuid.UUID, payload: VerifyNovel) -> dict[str, Any]:
    folder = session_dir(session_id)
    with locked(folder):
        meta = load(folder)
        if meta["этап"] != "запись_и_сверка":
            raise HTTPException(409, "Novel is not in review stage")
        if not payload.audited_against_raw or payload.unresolved_issues:
            raise HTTPException(409, {"code": "SEMANTIC_AUDIT_REQUIRED", "issues": payload.unresolved_issues})
        if (folder / "raw.txt").is_file():
            corrupted = placeholder_events((folder / "raw.txt").read_bytes().decode("utf-8"))
            if corrupted:
                raise HTTPException(409, {"code": "RAW_PLACEHOLDER_NOT_REPAIRED", "event_ids": corrupted})
        if meta.get("_raw_repair_requires_review"):
            # The caller must read the repaired RAW and rewrite/review any old JSON.
            # Expose the pending flag. Verification still requires audited_against_raw;
            # the backend cannot itself prove semantic equivalence.
            pass
        # Normalize only explicit, uniquely resolvable participant references.
        # Never invent presence or replace an unknown character with POV.
        try:
            current_state = read_data(folder, "state.json")
            registry_doc = read_data(folder, "персонажи.json")
        except HTTPException:
            raise HTTPException(409, {
                "code": "FOUNDATION_INCOMPLETE",
                "issues": validate_foundation(folder),
            })
        roster = registry_doc.get("персонажи")
        if isinstance(roster, list):
            normalized_state, state_issues = canonicalize_initial_state(
                current_state, roster
            )
        else:
            normalized_state, state_issues = current_state, []
        issues = state_issues + validate_foundation(
            folder, state_override=normalized_state
        )
        if issues:
            raise HTTPException(409, {"code": "FOUNDATION_INCOMPLETE", "issues": issues})
        from_roster = roster if isinstance(roster, list) else []
        relationship_issues = verify_initial_relationship_review(
            folder, from_roster, read_data(folder, "отношения.json"),
            normalized_state.get("pov_id", ""),
        )
        if relationship_issues:
            raise HTTPException(409, {
                "code": "RELATIONSHIP_REVIEW_REQUIRED",
                "issues": relationship_issues,
            })
        if normalized_state != current_state:
            atomic_json(folder / "state.json", normalized_state)
        meta["этап"] = "готово_к_игре"
        meta.pop("_raw_repair_requires_review", None)
        atomic_json(folder / "сессия.json", meta)
        return summary(meta)


@app.post("/sessions/{session_id}/prepare-turn")
def prepare_turn(session_id: uuid.UUID, payload: PrepareTurn) -> dict[str, Any]:
    """Read-only context for the current turn; repeat to expand selected NPCs.

    This operation does not advance the game or invent any actions. The writer
    chooses events, and a future commit operation will persist the outcome.
    """
    from .turn_context import build_packet

    folder = session_dir(session_id)
    with locked(folder):
        meta = load(folder)
        if meta["этап"] not in {"готово_к_игре", "игра"}:
            raise HTTPException(409, "Novel must be verified before preparing a turn")
        from .turn_maintenance import audit_due
        if audit_due(meta):
            raise HTTPException(409, {"code": "AUDIT_REQUIRED", "through_turn": meta["последний_ход"]})
        from .session_continuity import compaction_due
        if compaction_due(meta):
            raise HTTPException(409, {"code": "COMPACTION_REQUIRED", "through_turn": meta["последний_ход"]})
        return present(build_packet(
            root=folder,
            meta=meta,
            user_input=payload.user_input,
            additional_character_ids=payload.additional_character_ids,
            selected_hook_indices=payload.selected_hook_indices,
            selected_secret_indices=payload.selected_secret_indices,
            additional_location_ids=payload.additional_location_ids,
            full_memory_character_ids=payload.full_memory_character_ids,
            full_chronology=payload.full_chronology,
        ), "prepare-turn")


@app.post("/sessions/{session_id}/commit-turn")
def commit_turn(session_id: uuid.UUID, payload: CommitTurn) -> dict[str, Any]:
    """Apply sparse JSON changes and archive a complete scene as one recoverable turn."""
    from .turn_commit import save_turn
    from .turn_context import build_packet

    folder = session_dir(session_id)
    with locked(folder):
        meta = load(folder)
        if meta["этап"] not in {"готово_к_игре", "игра"}:
            raise HTTPException(409, "Novel must be verified before committing a turn")
        # A retry of an ALREADY saved turn must remain idempotent even when
        # its 15th-turn audit or 60th-turn compaction is pending. Newly proposed
        # turns still cannot bypass either checkpoint.
        next_id = f"{meta['id']}:{int(meta['последний_ход']) + 1}"
        if payload.turn_id == next_id:
            from .turn_maintenance import audit_due
            if audit_due(meta):
                raise HTTPException(409, {"code": "AUDIT_REQUIRED", "through_turn": meta["последний_ход"]})
            from .session_continuity import compaction_due
            if compaction_due(meta):
                raise HTTPException(409, {"code": "COMPACTION_REQUIRED", "through_turn": meta["последний_ход"]})
        if not payload.scene.strip():
            raise HTTPException(422, "Scene must not be blank")
        return save_turn(
            root=folder,
            meta=meta,
            payload=payload.model_dump(),
            valid_path=valid_path,
            foundation_check=validate_foundation,
            build_packet=build_packet,
        )


@app.post("/sessions/{session_id}/prepare-audit")
def prepare_audit_endpoint(session_id: uuid.UUID, payload: AuditPrepare) -> dict[str, Any]:
    """Read exact last 15 turns and relevant personal memories for review."""
    from .turn_maintenance import prepare_audit
    folder = session_dir(session_id)
    with locked(folder):
        meta = load(folder)
        if meta["этап"] not in {"готово_к_игре", "игра"}:
            raise HTTPException(409, "Session is not in game mode")
        return present(prepare_audit(folder, meta, payload.character_ids), "prepare-audit")


@app.post("/sessions/{session_id}/commit-audit")
def commit_audit_endpoint(session_id: uuid.UUID, payload: AuditCommit) -> dict[str, Any]:
    """Save reviewed, evidence-linked corrections without creating a game turn."""
    from .turn_maintenance import commit_audit
    folder = session_dir(session_id)
    with locked(folder):
        meta = load(folder)
        if meta["этап"] not in {"готово_к_игре", "игра"}:
            raise HTTPException(409, "Session is not in game mode")
        return commit_audit(folder, meta, payload.model_dump(), valid_path, validate_foundation)


@app.post("/sessions/{session_id}/rollback-last-turn")
def rollback_last_turn_endpoint(session_id: uuid.UUID, payload: RollbackTurn) -> dict[str, Any]:
    """Rollback only the exact last archived turn, transactionally."""
    from .turn_maintenance import rollback_last
    folder = session_dir(session_id)
    with locked(folder):
        meta = load(folder)
        return rollback_last(folder, meta, payload.expected_turn_id)


@app.get("/sessions/{session_id}/resume")
def resume_endpoint(session_id: uuid.UUID) -> dict[str, Any]:
    """Lightweight read-only handoff to a new ChatGPT conversation."""
    from .session_continuity import resume_session
    folder = session_dir(session_id)
    with locked(folder):
        return present(resume_session(folder, load(folder)), "resume")


@app.get("/sessions/{session_id}/turns")
def read_archive_endpoint(session_id: uuid.UUID, from_turn: int = 1, to_turn: int = 1) -> dict[str, Any]:
    """Retrieve up to 15 exact archived scenes only when details are needed."""
    from .session_continuity import archived_scenes
    folder = session_dir(session_id)
    with locked(folder):
        return present(archived_scenes(folder, load(folder), from_turn, to_turn), "turns")


@app.post("/sessions/{session_id}/prepare-compaction")
def prepare_compaction_endpoint(session_id: uuid.UUID) -> dict[str, Any]:
    from .session_continuity import prepare_compaction
    folder = session_dir(session_id)
    with locked(folder):
        return present(prepare_compaction(folder, load(folder)), "prepare-compaction")


@app.post("/sessions/{session_id}/commit-compaction")
def commit_compaction_endpoint(session_id: uuid.UUID, payload: CompactionCommit) -> dict[str, Any]:
    from .session_continuity import commit_compaction
    folder = session_dir(session_id)
    with locked(folder):
        return commit_compaction(folder, load(folder), payload.model_dump())