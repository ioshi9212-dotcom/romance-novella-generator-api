from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

ROOT = Path(os.getenv("DATA_DIR", "data")).resolve()
TEMPLATES = Path(__file__).resolve().parent.parent / "state_templates"
SAFE = re.compile(r"^[A-Za-z0-9_.-]+$")

app = FastAPI(title="Novel AI Memory API", version="0.2.0")


class Character(BaseModel):
    character_id: str = Field(min_length=1, max_length=80)
    card: str = ""
    knowledge_start: str = ""
    relationship_start: str = ""


class NewSession(BaseModel):
    session_id: Optional[str] = None
    title: str = "Новая новелла"


class SetupChunk(BaseModel):
    message_number: int = Field(ge=1)
    text: str


class FinalizeSetup(BaseModel):
    novel: str
    novel_rules: str = ""
    hidden_lore: str = ""
    plot_threads: str = ""
    pov_character_id: Optional[str] = None
    characters: List[Character] = Field(default_factory=list)
    audit: bool = False


class OpeningScene(BaseModel):
    scene_text: str
    continuity: Optional[str] = None
    continuity_events: str = ""
    game_day: Optional[str] = None
    world_date: Optional[str] = None
    world_time: Optional[str] = None


class Turn(BaseModel):
    turn_number: int = Field(ge=1)
    user_text: str
    scene_text: str
    chronology_note: str = ""
    continuity: Optional[str] = None
    continuity_events: str = ""
    plot_threads: Optional[str] = None
    knowledge_updates: Dict[str, str] = Field(default_factory=dict)
    relationship_updates: Dict[str, str] = Field(default_factory=dict)
    character_updates: Dict[str, str] = Field(default_factory=dict)
    present_characters: List[str] = Field(default_factory=list)
    remote_characters: List[str] = Field(default_factory=list)
    meaningful_character_actions: Dict[str, str] = Field(default_factory=dict)
    cast_updates: Dict[str, str] = Field(default_factory=dict)
    new_characters: List[Character] = Field(default_factory=list)
    game_day: Optional[str] = None
    world_date: Optional[str] = None
    world_time: Optional[str] = None


class Compact(BaseModel):
    through_turn: int = Field(ge=15)
    content: str = Field(min_length=1)


def fail(code: int, msg: str):
    raise HTTPException(status_code=code, detail=msg)


def clean(value: str, label: str) -> str:
    if not value or not SAFE.fullmatch(value):
        fail(400, f"bad {label}")
    return value


def tpl(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def jwrite(path: Path, obj):
    write(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def jread(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest_obj(obj) -> str:
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sdir(sid: str) -> Path:
    return ROOT / clean(sid, "session_id")


def cdir(sd: Path, cid: str) -> Path:
    return sd / "characters" / clean(cid, "character_id")


@contextmanager
def lock(sd: Path):
    sd.mkdir(parents=True, exist_ok=True)
    with (sd / ".lock").open("a+") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def meta_md(m):
    confirmed = "да" if m.get("setup_confirmed") else "нет"
    opening = "да" if m.get("opening_scene_saved") else "нет"
    return (
        "# Служебное состояние\n\n"
        "Правило: только короткие технические отметки.\n\n"
        f"Сессия: {m['title']} ({m['session_id']})\n"
        f"Этап setup: {m.get('setup_stage', 'сбор')}\n"
        f"Setup подтверждён игроком: {confirmed}\n"
        f"Последний сохранённый блок исходника: {m.get('last_setup_message', 0)}\n"
        f"Последний проверенный блок исходника: {m.get('last_checked_setup_message', 0)}\n"
        f"Количество аудитов setup: {m.get('setup_audit_count', 0)}\n"
        f"Нулевая сцена сохранена: {opening}\n\n"
        f"Текущий ход: {m.get('last_saved_turn', 0)}\n"
        f"Последний полностью сохранённый ход: {m.get('last_saved_turn', 0)}\n"
        f"Последняя свёртка хронологии: {m.get('last_compaction_turn', 0)}\n"
        f"Игровой день: {m.get('game_day') or ''}\n"
        f"Дата в мире: {m.get('world_date') or ''}\n"
        f"Текущее время: {m.get('world_time') or ''}\n"
    )


def save_meta(sd: Path, m):
    jwrite(sd / "meta.json", m)
    write(sd / "save_meta.md", meta_md(m))


def setup_receipts(sd: Path):
    out = []
    for p in sorted((sd / "setup_messages").glob("*.json")):
        x = jread(p)
        if x.get("status") == "committed":
            out.append(x)
    return out


def render_setup_source(sd: Path, m):
    status = "готово" if m.get("setup_stage") == "готово" else m.get("setup_stage", "сбор")
    parts = [
        "# Дословный материал игрока\n\n",
        f"Статус: {status}\n\n",
        "Правило: здесь хранится только исходный ввод игрока о новелле. Ничего не исправлять и не пересказывать.\n\n",
    ]
    for r in setup_receipts(sd):
        p = r["payload"]
        parts.append(f"## Сообщение {p['message_number']}\n\n")
        parts.append(p["text"])
        parts.append("\n\n")
    text = "".join(parts)
    write(sd / "setup_source.md", text)
    return text


def add_character(sd: Path, ch: Character, replay=False):
    d = cdir(sd, ch.character_id)
    if d.exists() and not replay:
        fail(409, f"character already exists: {ch.character_id}")
    d.mkdir(parents=True, exist_ok=True)

    if ch.card:
        write(d / "card_base.md", ch.card.rstrip() + "\n")
    elif not (d / "card_base.md").exists():
        write(d / "card_base.md", tpl("character.md"))

    profile = {
        "character_id": ch.character_id,
        "knowledge_start": ch.knowledge_start,
        "relationship_start": ch.relationship_start,
    }
    jwrite(d / "profile.json", profile)
    render_character_card(sd, ch.character_id)
    render_character_knowledge(sd, ch.character_id)
    render_character_relationship(sd, ch.character_id)


def turn_receipts(sd: Path):
    out = []
    for p in sorted((sd / "turn_receipts").glob("*.json")):
        x = jread(p)
        if x.get("status") == "committed":
            out.append(x)
    return out


def render_character_card(sd: Path, cid: str):
    d = cdir(sd, cid)
    if not d.exists():
        fail(404, "character not found")

    base_path = d / "card_base.md"
    if base_path.exists():
        base = base_path.read_text(encoding="utf-8").rstrip()
    elif (d / "card.md").exists():
        base = (d / "card.md").read_text(encoding="utf-8").rstrip()
        write(base_path, base + "\n")
    else:
        base = tpl("character.md").rstrip()
        write(base_path, base + "\n")

    parts = [base]
    for r in turn_receipts(sd):
        p = r["payload"]
        text = (p.get("character_updates") or {}).get(cid)
        if text:
            parts.append(f"\n\n### Дополнение после хода {p['turn_number']}\n{text}")

    result = "".join(parts).rstrip() + "\n"
    write(d / "card.md", result)
    return result


def render_character_knowledge(sd: Path, cid: str):
    d = cdir(sd, cid)
    if not d.exists():
        fail(404, "character not found")
    base = tpl("knowledge.md").replace("Персонаж:\n", f"Персонаж: {cid}\n", 1).rstrip()
    parts = [base]
    profile_path = d / "profile.json"
    if profile_path.exists():
        start = jread(profile_path).get("knowledge_start", "")
        if start:
            parts.append(f"\n\n## На старте истории\n{start}")
    for r in turn_receipts(sd):
        p = r["payload"]
        text = (p.get("knowledge_updates") or {}).get(cid)
        if text:
            parts.append(f"\n\n### Ход {p['turn_number']}\n{text}")
    result = "".join(parts).rstrip() + "\n"
    write(d / "knowledge.md", result)
    return result


def render_character_relationship(sd: Path, cid: str):
    d = cdir(sd, cid)
    if not d.exists():
        fail(404, "character not found")
    base = tpl("relationship.md").replace("Персонаж:\n", f"Персонаж: {cid}\n", 1).rstrip()
    parts = [base]
    profile_path = d / "profile.json"
    if profile_path.exists():
        start = jread(profile_path).get("relationship_start", "")
        if start:
            parts.append(f"\n\n## Старт истории\n{start}")
    for r in turn_receipts(sd):
        p = r["payload"]
        text = (p.get("relationship_updates") or {}).get(cid)
        if text:
            parts.append(f"\n\n### Изменение после хода {p['turn_number']}\n{text}")
    result = "".join(parts).rstrip() + "\n"
    write(d / "relationship.md", result)
    return result


def sync_meta_from_receipts(sd: Path, m):
    committed = turn_receipts(sd)
    m["last_saved_turn"] = committed[-1]["payload"]["turn_number"] if committed else 0

    opening_path = sd / "opening_scene.json"
    m["opening_scene_saved"] = (
        opening_path.exists()
        and jread(opening_path).get("status") == "committed"
    )

    compacted = sorted((sd / "chronology_compactions").glob("*.md"))
    m["last_compaction_turn"] = int(compacted[-1].stem) if compacted else 0

    # Время и дата восстанавливаются только из подтверждённых записей.
    for key in ("game_day", "world_date", "world_time"):
        value = None
        if m["opening_scene_saved"]:
            value = jread(opening_path)["payload"].get(key)
        for r in committed:
            candidate = r["payload"].get(key)
            if candidate is not None:
                value = candidate
        m[key] = value

    return m


def active_character_ids(sd: Path, m):
    ids = set(m.get("setup_character_ids", []))
    for r in turn_receipts(sd):
        for ch in r["payload"].get("new_characters", []):
            ids.add(ch["character_id"])
    return sorted(ids)


def game_day_number(value):
    if value is None:
        return None
    match = re.search(r"\d+", str(value))
    return int(match.group(0)) if match else None


def card_field(text: str, label: str) -> str:
    for line in str(text or "").splitlines():
        if line.strip().startswith(label + ":"):
            return line.split(":", 1)[1].strip()
    return ""


def render_cast_registry(sd: Path, m):
    current_turn = int(m.get("last_saved_turn", 0) or 0)
    current_day = game_day_number(m.get("game_day"))
    pov_id = str(m.get("pov_character_id") or "")
    rows = []

    for cid in active_character_ids(sd, m):
        if cid == pov_id:
            continue
        d = cdir(sd, cid)
        if not d.exists():
            continue

        card = render_character_card(sd, cid)
        name = " ".join(
            x for x in [card_field(card, "Имя"), card_field(card, "Фамилия")] if x
        ).strip() or cid
        role = card_field(card, "Роль в истории")
        goal = card_field(card, "Личная цель")
        function = card_field(card, "Режиссёрская функция в истории")

        last_physical = None
        last_participation = None
        last_meaningful = None
        last_meaningful_text = ""
        last_cast_update = ""

        for receipt in turn_receipts(sd):
            p = receipt["payload"]
            turn_no = int(p["turn_number"])
            day = game_day_number(p.get("game_day"))
            present = set(p.get("present_characters") or [])
            remote = set(p.get("remote_characters") or [])
            meaningful = p.get("meaningful_character_actions") or {}
            cast_updates = p.get("cast_updates") or {}

            if cid in present:
                last_physical = (turn_no, day)
                last_participation = (turn_no, day)
            elif cid in remote:
                last_participation = (turn_no, day)

            if cid in meaningful and meaningful[cid]:
                last_meaningful = (turn_no, day)
                last_meaningful_text = str(meaningful[cid])

            if cid in cast_updates and cast_updates[cid]:
                last_cast_update = str(cast_updates[cid])

        def stamp(value):
            if not value:
                return "ещё не было"
            turn_no, day = value
            return f"ход {turn_no}" + (f", игровой день {day}" if day is not None else "")

        def since_turn(value):
            return "—" if not value else str(max(0, current_turn - value[0]))

        def since_day(value):
            if not value or current_day is None or value[1] is None:
                return "—"
            return str(max(0, current_day - value[1]))

        rows.append(
            "\n".join([
                f"## {name} / {cid}",
                "",
                f"Роль в истории: {role}",
                f"Личная цель: {goal}",
                f"Режиссёрская функция: {function}",
                "",
                f"Последнее физическое появление: {stamp(last_physical)}",
                f"Последнее участие вообще: {stamp(last_participation)}",
                f"Последнее значимое действие: {stamp(last_meaningful)}"
                + (f" — {last_meaningful_text}" if last_meaningful_text else ""),
                "",
                f"Ходов с физического появления: {since_turn(last_physical)}",
                f"Игровых дней с физического появления: {since_day(last_physical)}",
                f"Ходов со значимого действия: {since_turn(last_meaningful)}",
                f"Игровых дней со значимого действия: {since_day(last_meaningful)}",
                "",
                f"Что у персонажа сейчас незакрыто / причина вернуться: {last_cast_update or 'смотреть цель, роль и открытые крючки'}",
            ])
        )

    intro = (
        "# Реестр персонажей\n\n"
        "Правило: это подсказка режиссёру о постоянном касте, а не таймер обязательных камео. "
        "Долгое отсутствие нужно учитывать вместе с ролью, целью и открытыми линиями персонажа. "
        "Отношения с POV не определяют, имеет ли персонаж право вернуться.\n"
    )
    text = intro + ("\n\n" + "\n\n".join(rows) if rows else "\n\nПостоянных NPC пока нет.\n")
    if not text.endswith("\n"):
        text += "\n"
    write(sd / "cast_registry.md", text)
    return text


def render_continuity(sd: Path, m):
    current = None
    events = []

    opening_path = sd / "opening_scene.json"
    if opening_path.exists():
        opening = jread(opening_path)["payload"]
        if opening.get("continuity") is not None:
            current = opening["continuity"]
        if opening.get("continuity_events"):
            events.append(("Нулевая сцена", opening["continuity_events"]))

    for r in turn_receipts(sd):
        p = r["payload"]
        if p.get("continuity") is not None:
            current = p["continuity"]
        if p.get("continuity_events"):
            events.append((f"Ход {p['turn_number']}", p["continuity_events"]))

    parts = [
        "# Текущее состояние и непрерывность\n\n",
        "Правило: текущая сцена — актуальный снимок. История важных перемещений не стирается.\n\n",
        "## Текущая сцена\n\n",
        (current if current is not None else "Состояние ещё не задано."),
        "\n\n## История важных предметов и цифровых следов\n",
    ]
    if events:
        for title, body in events:
            parts.append(f"\n### {title}\n{body}\n")
    else:
        parts.append("\nПока нет записей.\n")

    text = "".join(parts)
    write(sd / "continuity.md", text)
    return text


def render_plot_threads(sd: Path):
    parts = ["# Крючки и договорённости\n"]
    base_path = sd / "plot_threads_base.md"
    if base_path.exists():
        base = base_path.read_text(encoding="utf-8").strip()
        if base:
            parts.append("\n## На старте\n" + base + "\n")

    for r in turn_receipts(sd):
        p = r["payload"]
        update = p.get("plot_threads")
        if update:
            parts.append(f"\n## Изменение после хода {p['turn_number']}\n{update}\n")

    text = "".join(parts)
    write(sd / "plot_threads.md", text)
    return text


def render_recent(sd: Path, m):
    parts = ["# Последние 15 ходов\n\n"]
    opening_path = sd / "opening_scene.json"
    if opening_path.exists() and m.get("last_saved_turn", 0) < 5:
        opening = jread(opening_path)["payload"]["scene_text"]
        parts.append("## Нулевая сцена\n\n")
        parts.append(opening)
        parts.append("\n\n")

    for r in turn_receipts(sd)[-15:]:
        p = r["payload"]
        parts.append(f"## Ход {p['turn_number']}\n\n### Игрок\n")
        parts.append(p["user_text"])
        parts.append("\n\n### Сцена\n")
        parts.append(p["scene_text"])
        parts.append("\n\n")

    text = "".join(parts)
    write(sd / "recent_turns.md", text)
    return text


def render_chronology(sd: Path, m):
    parts = ["# Хронология\n"]
    for p in sorted((sd / "chronology_compactions").glob("*.md")):
        block = p.read_text(encoding="utf-8").strip()
        if block:
            parts.append("\n" + block + "\n")

    last_compacted = m.get("last_compaction_turn", 0)
    for p in sorted((sd / "chronology_fragments").glob("*.md")):
        if int(p.stem) > last_compacted:
            block = p.read_text(encoding="utf-8").strip()
            if block:
                parts.append("\n" + block + "\n")

    text = "".join(parts).rstrip() + "\n"
    write(sd / "chronology.md", text)
    return text


def refresh_character_files(sd: Path, character_ids=None):
    if character_ids is None:
        character_ids = [p.name for p in (sd / "characters").iterdir() if p.is_dir()]
    for cid in sorted(set(character_ids)):
        if cdir(sd, cid).exists():
            render_character_card(sd, cid)
            render_character_knowledge(sd, cid)
            render_character_relationship(sd, cid)


@app.get("/health", operation_id="health")
def health():
    return {"ok": True, "version": "0.2.0"}


@app.post("/sessions", operation_id="createSession")
def create_session(req: NewSession):
    ROOT.mkdir(parents=True, exist_ok=True)
    sid = clean(req.session_id, "session_id") if req.session_id else uuid.uuid4().hex[:12]
    sd = sdir(sid)
    if sd.exists() and any(sd.iterdir()):
        fail(409, f"session already exists: {sid}")

    with lock(sd):
        for name in (
            "setup_messages",
            "turn_receipts",
            "chronology_fragments",
            "chronology_compactions",
            "characters",
        ):
            (sd / name).mkdir(parents=True, exist_ok=True)

        write(sd / "novel.md", tpl("novel.md"))
        write(sd / "novel_rules.md", tpl("novel_rules.md"))
        write(sd / "hidden_lore.md", tpl("hidden_lore.md"))
        write(sd / "continuity.md", tpl("continuity.md"))
        write(sd / "plot_threads_base.md", "")
        write(sd / "plot_threads.md", tpl("plot_threads.md"))
        write(sd / "cast_registry.md", tpl("cast_registry.md"))
        write(sd / "chronology.md", "# Хронология\n")
        write(sd / "recent_turns.md", "# Последние 15 ходов\n")

        m = {
            "session_id": sid,
            "title": req.title,
            "pov_character_id": None,
            "setup_character_ids": [],
            "setup_stage": "сбор",
            "setup_confirmed": False,
            "last_setup_message": 0,
            "last_checked_setup_message": 0,
            "setup_revision": 0,
            "setup_audit_count": 0,
            "opening_scene_saved": False,
            "last_saved_turn": 0,
            "last_compaction_turn": 0,
            "game_day": None,
            "world_date": None,
            "world_time": None,
        }
        save_meta(sd, m)
        render_setup_source(sd, m)

    return {"session_id": sid, "setup_stage": "сбор"}


@app.post("/sessions/{session_id}/setup/messages", operation_id="appendSetupMessage")
def append_setup_message(session_id: str, req: SetupChunk):
    sd = sdir(session_id)
    mp = sd / "meta.json"
    if not mp.exists():
        fail(404, "session not found")

    payload = req.model_dump(mode="json")
    digest = digest_obj(payload)
    rp = sd / "setup_messages" / f"{req.message_number:08d}.json"

    with lock(sd):
        m = jread(mp)
        if m.get("opening_scene_saved") or m.get("last_saved_turn", 0) > 0:
            fail(409, "setup is locked after story start")

        if rp.exists():
            old = jread(rp)
            if old["hash"] != digest:
                fail(409, "setup message already exists with different content")
            m["last_setup_message"] = max(m.get("last_setup_message", 0), req.message_number)
            save_meta(sd, m)
            render_setup_source(sd, m)
            return {
                "saved": True,
                "idempotent": True,
                "message_number": req.message_number,
            }

        expected = m.get("last_setup_message", 0) + 1
        if req.message_number != expected:
            fail(409, f"expected setup message {expected}")

        jwrite(rp, {"status": "committed", "hash": digest, "payload": payload})
        m["last_setup_message"] = req.message_number
        m["setup_stage"] = "сбор"
        m["setup_confirmed"] = False
        save_meta(sd, m)
        render_setup_source(sd, m)
        render_plot_threads(sd)
        render_cast_registry(sd, m)

        return {
            "saved": True,
            "idempotent": False,
            "message_number": req.message_number,
        }


@app.post("/sessions/{session_id}/setup/finalize", operation_id="finalizeSetup")
def finalize_setup(session_id: str, req: FinalizeSetup):
    sd = sdir(session_id)
    mp = sd / "meta.json"
    if not mp.exists():
        fail(404, "session not found")

    with lock(sd):
        m = jread(mp)
        if m.get("opening_scene_saved") or m.get("last_saved_turn", 0) > 0:
            fail(409, "setup is locked after story start")
        if m.get("last_setup_message", 0) < 1:
            fail(409, "setup source is empty")

        ids = [ch.character_id for ch in req.characters]
        if len(ids) != len(set(ids)):
            fail(400, "duplicate character_id")
        if req.pov_character_id and req.pov_character_id not in ids:
            fail(400, "pov_character_id must be one of characters")

        write(sd / "novel.md", (req.novel or tpl("novel.md")).rstrip() + "\n")
        write(sd / "novel_rules.md", (req.novel_rules or tpl("novel_rules.md")).rstrip() + "\n")
        write(sd / "hidden_lore.md", (req.hidden_lore or tpl("hidden_lore.md")).rstrip() + "\n")
        write(sd / "plot_threads_base.md", req.plot_threads.rstrip() + "\n" if req.plot_threads else "")

        chars_root = sd / "characters"
        for child in list(chars_root.iterdir()):
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()

        for ch in req.characters:
            add_character(sd, ch)

        m["pov_character_id"] = req.pov_character_id
        m["setup_character_ids"] = ids
        m["setup_stage"] = "готово"
        m["setup_confirmed"] = True
        m["last_checked_setup_message"] = m.get("last_setup_message", 0)
        m["setup_revision"] = m.get("setup_revision", 0) + 1
        if req.audit:
            m["setup_audit_count"] = m.get("setup_audit_count", 0) + 1

        save_meta(sd, m)
        render_setup_source(sd, m)
        render_plot_threads(sd)

        return {
            "finalized": True,
            "setup_revision": m["setup_revision"],
            "setup_audit_count": m["setup_audit_count"],
            "checked_through_message": m["last_checked_setup_message"],
            "characters": ids,
        }


@app.post("/sessions/{session_id}/opening-scene", operation_id="saveOpeningScene")
def save_opening_scene(session_id: str, req: OpeningScene):
    sd = sdir(session_id)
    mp = sd / "meta.json"
    if not mp.exists():
        fail(404, "session not found")

    payload = req.model_dump(mode="json")
    digest = digest_obj(payload)
    op = sd / "opening_scene.json"

    with lock(sd):
        m = sync_meta_from_receipts(sd, jread(mp))
        if m.get("setup_stage") != "готово" or not m.get("setup_confirmed"):
            fail(409, "setup is not ready")
        if m.get("last_saved_turn", 0) > 0:
            fail(409, "opening scene cannot change after turn 1")

        if op.exists():
            old = jread(op)
            if old["hash"] != digest:
                fail(409, "opening scene already exists with different content")
            m["opening_scene_saved"] = True
            save_meta(sd, m)
            return {"saved": True, "idempotent": True}

        jwrite(op, {"status": "committed", "hash": digest, "payload": payload})
        m["opening_scene_saved"] = True
        for key in ("game_day", "world_date", "world_time"):
            val = getattr(req, key)
            if val is not None:
                m[key] = val
        save_meta(sd, m)
        render_recent(sd, m)
        render_continuity(sd, m)
        render_plot_threads(sd)
        return {"saved": True, "idempotent": False}


@app.post("/sessions/{session_id}/turns", operation_id="saveTurn")
def save_turn(session_id: str, req: Turn):
    sd = sdir(session_id)
    mp = sd / "meta.json"
    if not mp.exists():
        fail(404, "session not found")

    payload = req.model_dump(mode="json")
    digest = digest_obj(payload)
    rp = sd / "turn_receipts" / f"{req.turn_number:08d}.json"

    with lock(sd):
        m = sync_meta_from_receipts(sd, jread(mp))
        if m.get("setup_stage") != "готово" or not m.get("setup_confirmed"):
            fail(409, "setup is not ready")
        if not m.get("opening_scene_saved"):
            fail(409, "opening scene is not saved")

        old = jread(rp) if rp.exists() else None
        if old:
            if old["hash"] != digest:
                fail(409, "turn already exists with different content")
            if old["status"] == "committed":
                render_recent(sd, m)
                render_chronology(sd, m)
                render_continuity(sd, m)
                render_plot_threads(sd)
                render_cast_registry(sd, m)
                refresh_character_files(sd, active_character_ids(sd, m))
                return {
                    "saved": True,
                    "idempotent": True,
                    "turn_number": req.turn_number,
                    "compaction_due": (
                        req.turn_number % 15 == 0
                        and m["last_compaction_turn"] < req.turn_number
                    ),
                }
        else:
            if m["last_saved_turn"] - m["last_compaction_turn"] >= 15:
                fail(
                    409,
                    f"chronology compaction required through turn {m['last_compaction_turn'] + 15}",
                )
            if req.turn_number != m["last_saved_turn"] + 1:
                fail(409, f"expected turn {m['last_saved_turn'] + 1}")

            existing = set(active_character_ids(sd, m))
            new = [x.character_id for x in req.new_characters]
            if len(new) != len(set(new)):
                fail(400, "duplicate new character_id")
            if set(new) & existing:
                fail(409, "new character already exists")

            allowed = existing | set(new)
            bad = (
                set(req.knowledge_updates)
                | set(req.relationship_updates)
                | set(req.character_updates)
                | set(req.present_characters)
                | set(req.remote_characters)
                | set(req.meaningful_character_actions)
                | set(req.cast_updates)
            ) - allowed
            if bad:
                fail(400, f"unknown character: {sorted(bad)[0]}")
            both = set(req.present_characters) & set(req.remote_characters)
            if both:
                fail(400, f"character cannot be present and remote: {sorted(both)[0]}")

            jwrite(rp, {"status": "pending", "hash": digest, "payload": payload})

        for ch in req.new_characters:
            if not cdir(sd, ch.character_id).exists():
                add_character(sd, ch, replay=True)

        note = req.chronology_note.strip()
        fragment = f"### Ход {req.turn_number}\n{note}\n" if note else ""
        write(sd / "chronology_fragments" / f"{req.turn_number:08d}.md", fragment)

        m["last_saved_turn"] = req.turn_number
        for key in ("game_day", "world_date", "world_time"):
            val = getattr(req, key)
            if val is not None:
                m[key] = val

        save_meta(sd, m)
        jwrite(rp, {"status": "committed", "hash": digest, "payload": payload})
        render_recent(sd, m)
        render_chronology(sd, m)
        render_continuity(sd, m)
        render_plot_threads(sd)
        render_cast_registry(sd, m)
        refresh_character_files(
            sd,
            list(req.knowledge_updates)
            + list(req.relationship_updates)
            + list(req.character_updates)
            + [x.character_id for x in req.new_characters],
        )

        return {
            "saved": True,
            "idempotent": False,
            "turn_number": req.turn_number,
            "compaction_due": (
                req.turn_number % 15 == 0
                and m["last_compaction_turn"] < req.turn_number
            ),
        }


@app.post("/sessions/{session_id}/chronology/compact", operation_id="compactChronology")
def compact(session_id: str, req: Compact):
    sd = sdir(session_id)
    mp = sd / "meta.json"
    if not mp.exists():
        fail(404, "session not found")

    with lock(sd):
        m = jread(mp)
        expected = m["last_compaction_turn"] + 15
        block_path = sd / "chronology_compactions" / f"{req.through_turn:08d}.md"
        start_turn = req.through_turn - 14
        normalized = (
            f"## Свёртка ходов {start_turn}–{req.through_turn}\n\n"
            + req.content.rstrip()
            + "\n"
        )

        if req.through_turn == m["last_compaction_turn"] and block_path.exists():
            if block_path.read_text(encoding="utf-8") == normalized:
                return {
                    "compacted": True,
                    "idempotent": True,
                    "through_turn": req.through_turn,
                    "chronology": render_chronology(sd, m),
                }
            fail(409, "this block was already compacted with different content")

        if req.through_turn != expected:
            fail(409, f"expected compaction through turn {expected}")
        if req.through_turn > m["last_saved_turn"]:
            fail(409, "cannot compact unsaved turns")

        write(block_path, normalized)
        m["last_compaction_turn"] = req.through_turn
        save_meta(sd, m)

        return {
            "compacted": True,
            "idempotent": False,
            "through_turn": req.through_turn,
            "chronology": render_chronology(sd, m),
        }


@app.get("/sessions/{session_id}/state", operation_id="getSessionState")
def state(session_id: str):
    sd = sdir(session_id)
    mp = sd / "meta.json"
    if not mp.exists():
        fail(404, "session not found")

    with lock(sd):
        m = sync_meta_from_receipts(sd, jread(mp))
        setup_source = render_setup_source(sd, m)
        recent = render_recent(sd, m)
        chronology = render_chronology(sd, m)
        continuity = render_continuity(sd, m)
        plot_threads = render_plot_threads(sd)
        cast_registry = render_cast_registry(sd, m)
        chars = active_character_ids(sd, m)
        refresh_character_files(sd, chars)
        save_meta(sd, m)
        opening = None
        if (sd / "opening_scene.json").exists():
            opening = jread(sd / "opening_scene.json")["payload"]["scene_text"]

        return {
            "meta": m,
            "setup_source": setup_source,
            "novel": (sd / "novel.md").read_text(encoding="utf-8"),
            "novel_rules": (sd / "novel_rules.md").read_text(encoding="utf-8"),
            "hidden_lore": (sd / "hidden_lore.md").read_text(encoding="utf-8"),
            "opening_scene": opening,
            "chronology": chronology,
            "continuity": continuity,
            "plot_threads": plot_threads,
            "cast_registry": cast_registry,
            "recent_turns": recent,
            "characters": chars,
            "compaction_due": (
                m["last_saved_turn"] - m["last_compaction_turn"] >= 15
            ),
        }


@app.get(
    "/sessions/{session_id}/characters/{character_id}",
    operation_id="getCharacterState",
)
def character_state(session_id: str, character_id: str):
    sd = sdir(session_id)
    mp = sd / "meta.json"
    if not mp.exists():
        fail(404, "session not found")

    with lock(sd):
        m = sync_meta_from_receipts(sd, jread(mp))
        if character_id not in active_character_ids(sd, m):
            fail(404, "character not found")
        d = cdir(sd, character_id)
        if not d.exists():
            fail(404, "character not found")

        card = render_character_card(sd, character_id)
        knowledge = render_character_knowledge(sd, character_id)
        relationship = render_character_relationship(sd, character_id)
        return {
            "character_id": character_id,
            "card": card,
            "knowledge": knowledge,
            "relationship": relationship,
        }
