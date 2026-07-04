from pathlib import Path
from typing import Any
from app.bootstrapper import BASE_FILES, build_bootstrap_prompt, debug_stub_bootstrap
from app.config import get_settings
from app.id_utils import new_session_id, now_iso
from app.models import CreateSessionRequest
from app.storage import JsonStorage


FINAL_BOOTSTRAP_FILES = [
    "session.json",
    "user_request.json",
    "protagonist.json",
    "characters_index.json",
    "state/knowledge_index.json",
    "state/relationship_index.json",
    "story_plan.json",
    "current_state.json",
    "npc_state.json",
    "future_locks.json",
    "continuity.json",
    "scene_history.json",
    "turns.json",
    "characters/",
    "state/knowledge/",
    "state/relationship_pairs/",
]


def get_storage() -> JsonStorage:
    return JsonStorage(get_settings().data_dir)


def _questionnaire_text() -> str:
    path = Path(__file__).resolve().parent.parent / "prompts" / "start_questionnaire.md"
    return path.read_text(encoding="utf-8")


def _needs_questionnaire(request: CreateSessionRequest) -> bool:
    raw = (request.raw_start_text or "").strip().lower()
    if raw in {"начнем", "начнём", "старт", "создай сессию", "новая сессия"}:
        return True

    meaningful = [
        request.setting_request.strip(),
        request.protagonist_request.strip(),
        (request.romance_request or "").strip(),
        (request.tone or "").strip(),
    ]
    has_meaningful_detail = any(value and value not in {"-", "—", "придумай"} for value in meaningful)
    genre_only = bool(request.genre.strip()) and not has_meaningful_detail
    return genre_only or not has_meaningful_detail


def _one_line(value: Any, fallback: str = "—") -> str:
    if value is None:
        return fallback
    if isinstance(value, list):
        return ", ".join(str(x) for x in value if str(x).strip()) or fallback
    if isinstance(value, dict):
        return "; ".join(f"{k}: {v}" for k, v in value.items()) or fallback
    text = str(value).strip()
    return text or fallback


def _short_list(items: Any, limit: int = 5) -> list[str]:
    if not isinstance(items, list):
        return []
    return [str(x) for x in items[:limit] if str(x).strip()]


def build_setup_preview(bootstrap_json: dict[str, Any]) -> str:
    """Build a human-readable review before committing generated state.

    This preview is intentionally derived from generated JSON and contains no
    hidden future seeds. It lets the user confirm or request edits before the
    session becomes active.
    """
    protagonist = bootstrap_json.get("protagonist") or {}
    characters = bootstrap_json.get("characters") or {}
    relationships = bootstrap_json.get("relationships") or {}
    story_plan = bootstrap_json.get("story_plan") or {}
    current_state = bootstrap_json.get("current_state") or {}

    pc_id = protagonist.get("id") or current_state.get("player_character_id") or "player_character"
    pc_card = characters.get(pc_id, protagonist if isinstance(protagonist, dict) else {}) or {}

    lines: list[str] = []
    lines.append("## Черновик новеллы")
    lines.append("")
    lines.append("Это ещё не активная сцена и не сохранённая игра. Проверь основу. Если всё ок — напиши `подтверждаю`, и тогда Railway сохранит персонажей, знания, отношения и план в state.")
    lines.append("")

    lines.append("### Главная героиня / персонаж игрока")
    lines.append(f"- **ID:** `{pc_id}`")
    lines.append(f"- **Имя:** {_one_line(pc_card.get('name'))}")
    lines.append(f"- **Возраст / роль:** {_one_line(pc_card.get('age'))} · {_one_line(pc_card.get('role'))}")
    lines.append(f"- **Кто она:** {_one_line(pc_card.get('past_short'))}")
    lines.append(f"- **Цель:** {_one_line(pc_card.get('goal'))}")
    lines.append(f"- **Характер:** {_one_line((pc_card.get('personality') or {}).get('core'))}")
    lines.append(f"- **Манера речи:** {_one_line((pc_card.get('personality') or {}).get('speech'))}")
    lines.append(f"- **Привычки:** {_one_line(pc_card.get('habits'))}")
    lines.append(f"- **Что ценит в людях:** {_one_line(pc_card.get('likes_in_people'))}")
    lines.append(f"- **Что отталкивает:** {_one_line(pc_card.get('dislikes_in_people'))}")
    lines.append("")

    appearance = pc_card.get("appearance") or {}
    if appearance:
        lines.append("### Внешность / подача")
        for key in ["height", "build", "hair", "eyes", "face", "style"]:
            if appearance.get(key):
                lines.append(f"- **{key}:** {_one_line(appearance.get(key))}")
        lines.append("")

    known_cards = [card for cid, card in characters.items() if cid != pc_id]
    lines.append("### Кого она знает на старте")
    if not known_cards:
        lines.append("- Значимых знакомых на старте нет или они будут введены позже.")
    else:
        for card in known_cards[:10]:
            cid = card.get("id") or "unknown_id"
            name = _one_line(card.get("name"))
            role = _one_line(card.get("role"))
            relation_bits = []
            for connection in card.get("connections") or []:
                if isinstance(connection, dict) and connection.get("character_id") == pc_id:
                    relation_bits.append(_one_line(connection.get("relation")))
                    if connection.get("summary"):
                        relation_bits.append(_one_line(connection.get("summary")))
            relation = " · ".join(relation_bits) if relation_bits else _one_line(card.get("past_short"), "связь будет уточняться сценами")
            lines.append(f"- `{cid}` — **{name}**, {role}. {relation}")
    lines.append("")

    lines.append("### Где стартуем")
    lines.append(f"- **Дата/время:** {_one_line(current_state.get('date'))} · {_one_line(current_state.get('time'))}")
    lines.append(f"- **Локация:** {_one_line(current_state.get('location'))}")
    lines.append(f"- **Погода/атмосфера:** {_one_line(current_state.get('weather'))}")
    lines.append(f"- **Состояние сцены:** {_one_line(current_state.get('scene_state'))}")
    lines.append(f"- **Одежда:** {_one_line(current_state.get('outfit'))}")
    lines.append(f"- **При себе:** {_one_line(current_state.get('inventory'))}")
    lines.append("")

    lines.append("### План новеллы")
    lines.append(f"- **Жанр:** {_one_line(story_plan.get('genre'))}")
    lines.append(f"- **Тон:** {_one_line(story_plan.get('tone'))}")
    lines.append(f"- **Сеттинг:** {_one_line(story_plan.get('setting_summary'))}")
    lines.append(f"- **Главная завязка:** {_one_line(story_plan.get('main_premise'))}")
    lines.append(f"- **Цель игрока/героини:** {_one_line(story_plan.get('player_goal'))}")
    lines.append(f"- **Главный конфликт:** {_one_line(story_plan.get('central_conflict'))}")
    lines.append(f"- **Главный вопрос:** {_one_line(story_plan.get('central_question'))}")
    lines.append(f"- **Позиция истории:** {_one_line(story_plan.get('current_story_position'))}")

    open_threads = _short_list(story_plan.get("open_threads"), 6)
    if open_threads:
        lines.append("- **Открытые нити:** " + "; ".join(open_threads))
    forbidden = _short_list(story_plan.get("forbidden_drift"), 6)
    if forbidden:
        lines.append("- **Не уводить в:** " + "; ".join(forbidden))
    lines.append("")

    act_structure = story_plan.get("act_structure") or []
    if isinstance(act_structure, list) and act_structure:
        lines.append("### Сюжетный компас")
        for act in act_structure[:4]:
            if not isinstance(act, dict):
                continue
            label = act.get("act") or act.get("id") or "акт"
            goal = _one_line(act.get("goal"))
            must = _one_line(act.get("must_happen"))
            lines.append(f"- **{label}:** {goal}. Важно: {must}")
        lines.append("")

    status_slots = story_plan.get("status_slots") or []
    if status_slots:
        lines.append("### Поля состояния истории")
        for slot in status_slots[:2]:
            if isinstance(slot, dict):
                lines.append(f"- **{_one_line(slot.get('label'))}:** {_one_line(slot.get('initial_value'))}")
        lines.append("")

    if relationships:
        lines.append("### Стартовые отношения")
        for pair_id, rel in list(relationships.items())[:10]:
            if not isinstance(rel, dict):
                continue
            scores = rel.get("scores") or {}
            score_line = ", ".join(f"{k}: {v}" for k, v in scores.items()) if scores else "уровни будут уточняться"
            lines.append(f"- `{pair_id}` — {_one_line(rel.get('status'))}. {score_line}")
        lines.append("")

    lines.append("### Что дальше")
    lines.append("Напиши `подтверждаю`, если всё подходит. Или напиши, что исправить: героиню, работу/роль, знакомых, тон, романтику, сеттинг, стартовую сцену или план.")
    return "\n".join(lines)


class SessionManager:
    def __init__(self, storage: JsonStorage | None = None):
        self.storage = storage or get_storage()

    def create_session(self, request: CreateSessionRequest) -> dict[str, Any]:
        user_request = request.model_dump()

        if request.mode == "gpt_actions" and _needs_questionnaire(request):
            return {
                "session_id": None,
                "status": "needs_questionnaire",
                "mode": request.mode,
                "bootstrap_prompt": None,
                "questionnaire": _questionnaire_text(),
                "files_created": [],
            }

        session_id = new_session_id()
        session_dir = self.storage.ensure_session_dir(session_id)

        if request.mode == "debug_stub":
            bundle = debug_stub_bootstrap(session_id, user_request)
            self._write_bootstrap_files(session_id, bundle)
            return {
                "session_id": session_id,
                "status": "active",
                "mode": request.mode,
                "bootstrap_prompt": None,
                "questionnaire": None,
                "files_created": BASE_FILES,
            }

        created_at = now_iso()
        session = {
            "session_id": session_id,
            "title": request.title or "Untitled novella",
            "status": "bootstrap_pending",
            "engine_version": get_settings().engine_version,
            "created_at": created_at,
            "updated_at": created_at,
        }

        empty_files = {
            "session.json": session,
            "user_request.json": user_request,
            "protagonist.json": {},
            "characters_index.json": {"ids": []},
            "state/knowledge_index.json": {"ids": []},
            "state/relationship_index.json": {"pair_ids": []},
            "story_plan.json": {},
            "current_state.json": {},
            "npc_state.json": {},
            "future_locks.json": {},
            "continuity.json": {},
            "scene_history.json": [],
            "turns.json": [],
        }

        for filename, data in empty_files.items():
            self.storage.write_json(session_id, filename, data)
        (session_dir / "characters").mkdir(parents=True, exist_ok=True)
        (session_dir / "state" / "knowledge").mkdir(parents=True, exist_ok=True)
        (session_dir / "state" / "relationship_pairs").mkdir(parents=True, exist_ok=True)

        prompt = build_bootstrap_prompt(user_request)
        (session_dir / "pending_bootstrap_prompt.md").write_text(prompt, encoding="utf-8")

        return {
            "session_id": session_id,
            "status": "bootstrap_pending",
            "mode": request.mode,
            "bootstrap_prompt": prompt,
            "questionnaire": None,
            "files_created": list(empty_files.keys()) + ["characters/", "state/knowledge/", "state/relationship_pairs/", "pending_bootstrap_prompt.md"],
        }

    def _write_bootstrap_files(self, session_id: str, bootstrap_json: dict[str, Any]) -> list[str]:
        session = self.storage.read_json(session_id, "session.json", default=bootstrap_json.get("session", {}))
        session["status"] = "active"
        session["updated_at"] = now_iso()
        self.storage.write_json(session_id, "session.json", session)

        user_request = self.storage.read_json(session_id, "user_request.json", default=bootstrap_json.get("user_request", {}))
        self.storage.write_json(session_id, "user_request.json", user_request)
        self.storage.write_json(session_id, "protagonist.json", bootstrap_json["protagonist"])

        characters = bootstrap_json.get("characters", {})
        self.storage.write_json(session_id, "characters_index.json", {"ids": list(characters.keys())})
        for character_id, card in characters.items():
            self.storage.write_character(session_id, character_id, {**card, "id": card.get("id") or character_id})

        knowledge = bootstrap_json.get("knowledge", {})
        self.storage.write_json(session_id, "state/knowledge_index.json", {"ids": list(knowledge.keys())})
        for character_id, entry in knowledge.items():
            self.storage.write_character_knowledge(session_id, character_id, entry)

        relationships = bootstrap_json.get("relationships", {})
        self.storage.write_json(session_id, "state/relationship_index.json", {"pair_ids": list(relationships.keys())})
        for pid, entry in relationships.items():
            self.storage.write_relationship_pair(session_id, pid, entry)

        self.storage.write_json(session_id, "story_plan.json", bootstrap_json["story_plan"])
        self.storage.write_json(session_id, "current_state.json", bootstrap_json["current_state"])
        self.storage.write_json(session_id, "npc_state.json", bootstrap_json.get("npc_state", {}))
        self.storage.write_json(session_id, "future_locks.json", bootstrap_json.get("future_locks", {}))
        self.storage.write_json(session_id, "continuity.json", bootstrap_json.get("continuity", {}))
        self.storage.write_json(session_id, "scene_history.json", bootstrap_json.get("scene_history", []))
        self.storage.write_json(session_id, "turns.json", bootstrap_json.get("turns", []))
        return FINAL_BOOTSTRAP_FILES

    def save_bootstrap_preview(self, session_id: str, bootstrap_json: dict[str, Any]) -> dict[str, Any]:
        session = self.storage.read_json(session_id, "session.json")
        if session.get("status") not in {"bootstrap_pending", "bootstrap_review_pending"}:
            raise ValueError(f"Cannot create bootstrap preview for session status: {session.get('status')}")

        preview = build_setup_preview(bootstrap_json)
        self.storage.write_json(session_id, "pending_bootstrap.json", bootstrap_json)
        (self.storage.session_dir(session_id) / "pending_setup_preview.md").write_text(preview, encoding="utf-8")
        session["status"] = "bootstrap_review_pending"
        session["updated_at"] = now_iso()
        self.storage.write_json(session_id, "session.json", session)
        return {
            "session_id": session_id,
            "status": "bootstrap_review_pending",
            "preview": preview,
            "can_confirm": True,
            "diagnostics": {
                "character_count": len(bootstrap_json.get("characters", {}) or {}),
                "relationship_count": len(bootstrap_json.get("relationships", {}) or {}),
                "knowledge_count": len(bootstrap_json.get("knowledge", {}) or {}),
            },
        }

    def confirm_bootstrap_preview(self, session_id: str) -> dict[str, Any]:
        session = self.storage.read_json(session_id, "session.json")
        if session.get("status") != "bootstrap_review_pending":
            raise ValueError(f"No bootstrap preview waiting for confirmation. Current status: {session.get('status')}")
        bootstrap_json = self.storage.read_json(session_id, "pending_bootstrap.json")
        files_created = self._write_bootstrap_files(session_id, bootstrap_json)
        return {"session_id": session_id, "status": "active", "committed": True, "files_created": files_created}

    def apply_bootstrap_result(self, session_id: str, bootstrap_json: dict[str, Any]) -> dict[str, Any]:
        required = [
            "protagonist",
            "characters",
            "relationships",
            "knowledge",
            "story_plan",
            "current_state",
        ]
        missing = [key for key in required if key not in bootstrap_json]
        if missing:
            raise ValueError(f"Bootstrap result missing required keys: {missing}")
        self._write_bootstrap_files(session_id, bootstrap_json)
        return {"session_id": session_id, "status": "active"}

    def get_memory(self, session_id: str) -> dict[str, Any]:
        return self.storage.read_session_bundle(session_id)

    def list_sessions(self) -> list[str]:
        return self.storage.list_sessions()

    def get_latest_session_id(self, prefer_active: bool = True) -> str | None:
        sessions = self.storage.list_sessions()
        if not sessions:
            return None

        records: list[tuple[str, str, str]] = []
        for session_id in sessions:
            try:
                session = self.storage.read_json(session_id, "session.json")
            except FileNotFoundError:
                continue
            records.append((session.get("created_at") or session_id, session.get("status") or "", session_id))

        records.sort(reverse=True)
        if prefer_active:
            for _, status, session_id in records:
                if status == "active":
                    return session_id
        return records[0][2] if records else None
