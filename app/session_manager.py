from pathlib import Path
from typing import Any
from app.bootstrapper import BASE_FILES, build_bootstrap_prompt, debug_stub_bootstrap
from app.config import get_settings
from app.id_utils import new_session_id, now_iso
from app.models import CreateSessionRequest
from app.storage import JsonStorage


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
            self.storage.write_json(session_id, "session.json", bundle["session"])
            self.storage.write_json(session_id, "user_request.json", bundle["user_request"])
            self.storage.write_json(session_id, "protagonist.json", bundle["protagonist"])
            self.storage.write_json(session_id, "story_plan.json", bundle["story_plan"])
            self.storage.write_json(session_id, "current_state.json", bundle["current_state"])
            self.storage.write_json(session_id, "npc_state.json", bundle.get("npc_state", {}))
            self.storage.write_json(session_id, "future_locks.json", bundle.get("future_locks", {}))
            self.storage.write_json(session_id, "continuity.json", bundle.get("continuity", {}))
            self.storage.write_json(session_id, "scene_history.json", bundle.get("scene_history", []))
            self.storage.write_json(session_id, "turns.json", bundle.get("turns", []))
            self.storage.write_json(session_id, "characters_index.json", {"ids": list(bundle.get("characters", {}).keys())})
            self.storage.write_json(session_id, "state/knowledge_index.json", {"ids": list(bundle.get("knowledge", {}).keys())})
            self.storage.write_json(session_id, "state/relationship_index.json", {"pair_ids": list(bundle.get("relationships", {}).keys())})
            for character_id, card in bundle.get("characters", {}).items():
                self.storage.write_character(session_id, character_id, card)
            for character_id, entry in bundle.get("knowledge", {}).items():
                self.storage.write_character_knowledge(session_id, character_id, entry)
            for pid, entry in bundle.get("relationships", {}).items():
                self.storage.write_relationship_pair(session_id, pid, entry)
            return {
                "session_id": session_id,
                "status": "active",
                "mode": request.mode,
                "bootstrap_prompt": None,
                "questionnaire": None,
                "files_created": BASE_FILES,
            }

        # gpt_actions: Custom GPT is the writer. Railway creates empty state files
        # and returns a bootstrap prompt for GPT to generate bootstrap JSON.
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
        # Create runtime directories for generated per-session data.
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

        session = self.storage.read_json(session_id, "session.json")
        session["status"] = "active"
        session["updated_at"] = now_iso()

        self.storage.write_json(session_id, "session.json", session)
        self.storage.write_json(session_id, "user_request.json", self.storage.read_json(session_id, "user_request.json", default={}))
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
