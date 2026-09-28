from __future__ import annotations

import fcntl, hashlib, json, os, re, uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

ROOT = Path(os.getenv("DATA_DIR", "data")).resolve()
TEMPLATES = Path(__file__).resolve().parent.parent / "state_templates"
SAFE = re.compile(r"^[A-Za-z0-9_.-]+$")
app = FastAPI(title="Novel AI Memory API", version="0.1.0")

class Character(BaseModel):
    character_id: str = Field(min_length=1, max_length=80)
    card: str = ""

class NewSession(BaseModel):
    session_id: Optional[str] = None
    title: str = "Новая новелла"
    pov_character_id: Optional[str] = None
    novel: str = ""
    hidden_lore: str = ""
    characters: List[Character] = Field(default_factory=list)

class Turn(BaseModel):
    turn_number: int = Field(ge=1)
    user_text: str
    scene_text: str
    chronology_note: str = ""
    continuity: Optional[str] = None
    plot_threads: Optional[str] = None
    knowledge_updates: Dict[str, str] = Field(default_factory=dict)
    relationship_updates: Dict[str, str] = Field(default_factory=dict)
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
    if not value or not SAFE.fullmatch(value): fail(400, f"bad {label}")
    return value

def tpl(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")

def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)

def jwrite(path: Path, obj): write(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
def jread(path: Path): return json.loads(path.read_text(encoding="utf-8"))
def sdir(sid: str) -> Path: return ROOT / clean(sid, "session_id")
def cdir(sd: Path, cid: str) -> Path: return sd / "characters" / clean(cid, "character_id")

@contextmanager
def lock(sd: Path):
    sd.mkdir(parents=True, exist_ok=True)
    with (sd / ".lock").open("a+") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try: yield
        finally: fcntl.flock(f.fileno(), fcntl.LOCK_UN)

def meta_md(m):
    return ("# Служебное состояние сохранения\n\n"
            f"Название сессии: {m['title']}\nТекущий ход: {m['last_saved_turn']}\n"
            f"Последний сохранённый ход: {m['last_saved_turn']}\n"
            f"Последняя свёртка хронологии: {m['last_compaction_turn']}\n"
            f"Игровой день: {m.get('game_day') or ''}\nДата в мире: {m.get('world_date') or ''}\n"
            f"Текущее время: {m.get('world_time') or ''}\n")

def save_meta(sd: Path, m): jwrite(sd / "meta.json", m); write(sd / "save_meta.md", meta_md(m))

def add_character(sd: Path, ch: Character, replay=False):
    d = cdir(sd, ch.character_id)
    if d.exists() and not replay: fail(409, f"character already exists: {ch.character_id}")
    d.mkdir(parents=True, exist_ok=True)
    if ch.card: write(d / "card.md", ch.card.rstrip() + "\n")
    elif not (d / "card.md").exists(): write(d / "card.md", tpl("character.md"))
    if not (d / "knowledge.md").exists(): write(d / "knowledge.md", tpl("knowledge.md").replace("Персонаж:\n", f"Персонаж: {ch.character_id}\n", 1))
    if not (d / "relationship.md").exists(): write(d / "relationship.md", tpl("relationship.md").replace("Персонаж:\n", f"Персонаж: {ch.character_id}\n", 1))

def receipts(sd: Path):
    out=[]
    for p in sorted((sd / "turn_receipts").glob("*.json")):
        x=jread(p)
        if x.get("status") == "committed": out.append(x)
    return out

def render_recent(sd: Path):
    parts=["# Последние 15 ходов\n\n"]
    for r in receipts(sd)[-15:]:
        p=r["payload"]
        parts.append(f"## Ход {p['turn_number']}\n\n### Игрок\n{p['user_text']}\n\n### Сцена\n{p['scene_text']}\n\n")
    text="".join(parts).rstrip()+"\n"; write(sd / "recent_turns.md", text); return text

def render_chronology(sd: Path, m):
    text=(sd / "chronology_compacted.md").read_text(encoding="utf-8").rstrip()
    for p in sorted((sd / "chronology_fragments").glob("*.md")):
        if int(p.stem) > m["last_compaction_turn"]:
            x=p.read_text(encoding="utf-8").strip()
            if x: text += "\n\n" + x
    text=text.rstrip()+"\n"; write(sd / "chronology.md", text); return text

@app.get("/health", operation_id="health")
def health(): return {"ok": True}

@app.post("/sessions", operation_id="createSession")
def create_session(req: NewSession):
    ROOT.mkdir(parents=True, exist_ok=True)
    sid=clean(req.session_id, "session_id") if req.session_id else uuid.uuid4().hex[:12]
    sd=sdir(sid)
    if sd.exists() and any(sd.iterdir()): fail(409, f"session already exists: {sid}")
    with lock(sd):
        for name in ("turn_receipts","chronology_fragments","characters"): (sd/name).mkdir(parents=True, exist_ok=True)
        write(sd/"novel.md", (req.novel or tpl("novel.md")).rstrip()+"\n")
        write(sd/"hidden_lore.md", (req.hidden_lore or tpl("hidden_lore.md")).rstrip()+"\n")
        for name in ("continuity.md","plot_threads.md"): write(sd/name, tpl(name))
        write(sd/"chronology_compacted.md", tpl("chronology.md")); write(sd/"chronology.md", tpl("chronology.md")); write(sd/"recent_turns.md", tpl("recent_turns.md"))
        for ch in req.characters: add_character(sd, ch)
        m={"session_id":sid,"title":req.title,"pov_character_id":req.pov_character_id,"last_saved_turn":0,"last_compaction_turn":0,"game_day":None,"world_date":None,"world_time":None}; save_meta(sd,m)
    return {"session_id":sid,"last_saved_turn":0}

@app.post("/sessions/{session_id}/turns", operation_id="saveTurn")
def save_turn(session_id: str, req: Turn):
    sd=sdir(session_id); mp=sd/"meta.json"
    if not mp.exists(): fail(404, "session not found")
    payload=req.model_dump(mode="json"); digest=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest(); rp=sd/"turn_receipts"/f"{req.turn_number:08d}.json"
    with lock(sd):
        m=jread(mp); old=jread(rp) if rp.exists() else None
        if old:
            if old["hash"] != digest: fail(409, "turn already exists with different content")
            if old["status"] == "committed":
                render_recent(sd); render_chronology(sd,m)
                return {"saved":True,"idempotent":True,"turn_number":req.turn_number,"compaction_due":req.turn_number%15==0 and m["last_compaction_turn"]<req.turn_number}
        else:
            if m["last_saved_turn"]-m["last_compaction_turn"] >= 15: fail(409, f"chronology compaction required through turn {m['last_compaction_turn']+15}")
            if req.turn_number != m["last_saved_turn"]+1: fail(409, f"expected turn {m['last_saved_turn']+1}")
            existing={p.name for p in (sd/"characters").iterdir() if p.is_dir()}; new=[x.character_id for x in req.new_characters]
            if len(new)!=len(set(new)): fail(400,"duplicate new character_id")
            if set(new)&existing: fail(409,"new character already exists")
            allowed=existing|set(new)
            bad=(set(req.knowledge_updates)|set(req.relationship_updates))-allowed
            if bad: fail(400,f"unknown character: {sorted(bad)[0]}")
            jwrite(rp,{"status":"pending","hash":digest,"payload":payload})
        for ch in req.new_characters:
            if not cdir(sd,ch.character_id).exists(): add_character(sd,ch,replay=True)
        if req.continuity is not None: write(sd/"continuity.md",req.continuity.rstrip()+"\n")
        if req.plot_threads is not None: write(sd/"plot_threads.md",req.plot_threads.rstrip()+"\n")
        for cid,text in req.knowledge_updates.items(): write(cdir(sd,cid)/"knowledge.md",text.rstrip()+"\n")
        for cid,text in req.relationship_updates.items(): write(cdir(sd,cid)/"relationship.md",text.rstrip()+"\n")
        note=req.chronology_note.strip(); write(sd/"chronology_fragments"/f"{req.turn_number:08d}.md", f"### Ход {req.turn_number}\n{note}\n" if note else "")
        m["last_saved_turn"]=req.turn_number
        for key in ("game_day","world_date","world_time"):
            val=getattr(req,key)
            if val is not None: m[key]=val
        save_meta(sd,m); jwrite(rp,{"status":"committed","hash":digest,"payload":payload}); render_recent(sd); render_chronology(sd,m)
        return {"saved":True,"idempotent":False,"turn_number":req.turn_number,"compaction_due":req.turn_number%15==0 and m["last_compaction_turn"]<req.turn_number}

@app.post("/sessions/{session_id}/chronology/compact", operation_id="compactChronology")
def compact(session_id: str, req: Compact):
    sd=sdir(session_id); mp=sd/"meta.json"
    if not mp.exists(): fail(404,"session not found")
    with lock(sd):
        m=jread(mp); normalized=req.content.rstrip()+"\n"
        if req.through_turn == m["last_compaction_turn"]:
            if (sd/"chronology_compacted.md").read_text(encoding="utf-8") == normalized:
                return {"compacted":True,"idempotent":True,"through_turn":req.through_turn,"chronology":render_chronology(sd,m)}
            fail(409,"this block was already compacted with different content")
        expected=m["last_compaction_turn"]+15
        if req.through_turn != expected: fail(409,f"expected compaction through turn {expected}")
        if req.through_turn > m["last_saved_turn"]: fail(409,"cannot compact unsaved turns")
        write(sd/"chronology_compacted.md",normalized); m["last_compaction_turn"]=req.through_turn; save_meta(sd,m)
        return {"compacted":True,"idempotent":False,"through_turn":req.through_turn,"chronology":render_chronology(sd,m)}

@app.get("/sessions/{session_id}/state", operation_id="getSessionState")
def state(session_id: str):
    sd=sdir(session_id); mp=sd/"meta.json"
    if not mp.exists(): fail(404,"session not found")
    with lock(sd):
        m=jread(mp); recent=render_recent(sd); chronology=render_chronology(sd,m); save_meta(sd,m)
        chars=sorted(p.name for p in (sd/"characters").iterdir() if p.is_dir())
        return {"meta":m,"novel":(sd/"novel.md").read_text(encoding="utf-8"),"hidden_lore":(sd/"hidden_lore.md").read_text(encoding="utf-8"),"chronology":chronology,"continuity":(sd/"continuity.md").read_text(encoding="utf-8"),"plot_threads":(sd/"plot_threads.md").read_text(encoding="utf-8"),"recent_turns":recent,"characters":chars,"compaction_due":m["last_saved_turn"]-m["last_compaction_turn"]>=15}

@app.get("/sessions/{session_id}/characters/{character_id}", operation_id="getCharacterState")
def character_state(session_id: str, character_id: str):
    sd=sdir(session_id); mp=sd/"meta.json"
    if not mp.exists(): fail(404,"session not found")
    with lock(sd):
        d=cdir(sd,character_id)
        if not d.exists(): fail(404,"character not found")
        return {"character_id":character_id,"card":(d/"card.md").read_text(encoding="utf-8"),"knowledge":(d/"knowledge.md").read_text(encoding="utf-8"),"relationship":(d/"relationship.md").read_text(encoding="utf-8")}
