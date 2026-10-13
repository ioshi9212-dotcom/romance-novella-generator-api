"""Novel creation and RAW persistence. No narrative generation or scene rules."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

import fcntl
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Novella Generator API", version="0.1.0")

PHASES = ("сбор", "вопросы", "готово_к_записи", "запись_и_сверка", "готово_к_игре")
CORE = {
    "анкета.json", "персонажи.json", "state.json", "хронология.json",
    "скрытый_лор_и_крючки.json", "отношения.json", "локации.json",
}
IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
RELATIONSHIP_AXES = {
    "доверие", "близость", "привязанность", "симпатия", "влечение",
    "уважение", "подозрение", "настороженность", "раздражение", "обида",
    "ревность", "страх", "соперничество",
}


class CreateNovel(BaseModel):
    request_id: str | None = Field(default=None, min_length=1, max_length=120)
    initial_text: str = ""


class RawPart(BaseModel):
    event_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    text: str = Field(min_length=1)
    question: str | None = None
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


class VerifyNovel(BaseModel):
    audited_against_raw: bool = False
    unresolved_issues: list[str] = Field(default_factory=list)


def authorize(x_api_key: str | None = Header(default=None)) -> None:
    expected = os.environ.get("API_KEY")
    if not expected:
        raise HTTPException(503, "API_KEY is not configured")
    if not x_api_key or not hmac.compare_digest(expected, x_api_key):
        raise HTTPException(401, "Invalid API key")


def session_dir(session_id: uuid.UUID) -> Path:
    return Path(os.environ.get("DATA_DIR", "./data")) / "sessions" / str(session_id)


@contextmanager
def locked(folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / ".lock").open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
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
    }


def source_digest(part: RawPart) -> str:
    source = [part.text, part.question, part.file_name]
    return hashlib.sha256(json.dumps(source, ensure_ascii=False).encode("utf-8")).hexdigest()


def append_source(folder: Path, meta: dict[str, Any], part: RawPart) -> None:
    receipts = meta.setdefault("_raw_receipts", {})
    digest = source_digest(part)
    previous = receipts.get(part.event_id)
    if previous is not None:
        if previous != digest:
            raise HTTPException(409, "event_id was already used for different material")
        return
    if meta["этап"] not in ("сбор", "вопросы"):
        raise HTTPException(409, "RAW intake is closed at this stage")
    raw_file = folder / "raw.txt"
    marker = f"===== RAW {part.event_id} {digest} =====\n"
    # Recover safely if the RAW append succeeded but metadata write was interrupted.
    if raw_file.exists():
        text = raw_file.read_text(encoding="utf-8")
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


def validate_foundation(folder: Path) -> list[str]:
    issues: list[str] = []
    docs: dict[str, dict[str, Any]] = {}
    for name in sorted(CORE):
        try:
            docs[name] = read_data(folder, name)
        except HTTPException:
            issues.append("Не сохранён или повреждён " + name)
    if issues:
        return issues

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
        issues.append("POV должен быть физически присутствующим в начальном State")
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
                for metric, value in metrics.items():
                    if metric not in RELATIONSHIP_AXES or isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 100:
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
def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/sessions", dependencies=[Depends(authorize)])
def create_novel(payload: CreateNovel) -> dict[str, Any]:
    key = os.environ.get("API_KEY", "")
    session_id = uuid.uuid5(uuid.NAMESPACE_URL, key + ":" + payload.request_id) if payload.request_id else uuid.uuid4()
    folder = session_dir(session_id)
    with locked(folder):
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


@app.get("/sessions/{session_id}", dependencies=[Depends(authorize)])
def get_session(session_id: uuid.UUID) -> dict[str, Any]:
    return summary(load(session_dir(session_id)))


@app.post("/sessions/{session_id}/raw", dependencies=[Depends(authorize)])
def add_raw(session_id: uuid.UUID, part: RawPart) -> dict[str, Any]:
    folder = session_dir(session_id)
    with locked(folder):
        meta = load(folder)
        append_source(folder, meta, part)
        return summary(meta)


@app.get("/sessions/{session_id}/raw", dependencies=[Depends(authorize)])
def get_raw(session_id: uuid.UUID) -> dict[str, str]:
    folder = session_dir(session_id)
    load(folder)
    path = folder / "raw.txt"
    return {"raw": path.read_text(encoding="utf-8") if path.exists() else ""}


@app.post("/sessions/{session_id}/advance", dependencies=[Depends(authorize)])
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


@app.put("/sessions/{session_id}/data", dependencies=[Depends(authorize)])
def put_document(session_id: uuid.UUID, payload: SaveDocument) -> dict[str, str]:
    if not valid_path(payload.path):
        raise HTTPException(400, "Invalid document path")
    folder = session_dir(session_id)
    with locked(folder):
        meta = load(folder)
        if meta["этап"] != "запись_и_сверка":
            raise HTTPException(409, "Novel files can only be written during creation review")
        atomic_json(folder / payload.path, payload.document)
        return {"path": payload.path, "status": "saved"}


@app.get("/sessions/{session_id}/data", dependencies=[Depends(authorize)])
def get_document(session_id: uuid.UUID, path: str) -> dict[str, Any]:
    folder = session_dir(session_id)
    load(folder)
    return {"path": path, "document": read_data(folder, path)}


@app.post("/sessions/{session_id}/verify", dependencies=[Depends(authorize)])
def verify_novel(session_id: uuid.UUID, payload: VerifyNovel) -> dict[str, Any]:
    folder = session_dir(session_id)
    with locked(folder):
        meta = load(folder)
        if meta["этап"] != "запись_и_сверка":
            raise HTTPException(409, "Novel is not in review stage")
        if not payload.audited_against_raw or payload.unresolved_issues:
            raise HTTPException(409, {"code": "SEMANTIC_AUDIT_REQUIRED", "issues": payload.unresolved_issues})
        issues = validate_foundation(folder)
        if issues:
            raise HTTPException(409, {"code": "FOUNDATION_INCOMPLETE", "issues": issues})
        meta["этап"] = "готово_к_игре"
        atomic_json(folder / "сессия.json", meta)
        return summary(meta)


@app.post("/sessions/{session_id}/prepare-turn", dependencies=[Depends(authorize)])
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
        return build_packet(
            root=folder,
            meta=meta,
            user_input=payload.user_input,
            additional_character_ids=payload.additional_character_ids,
            selected_hook_indices=payload.selected_hook_indices,
            selected_secret_indices=payload.selected_secret_indices,
            additional_location_ids=payload.additional_location_ids,
        )