from pathlib import Path
from typing import Any

from app.bootstrap_normalizer import normalize_bootstrap_json
from app.bootstrap_setup import build_bootstrap_prompt, build_setup_preview
from app.bootstrapper import BASE_FILES, debug_stub_bootstrap
from app.character_profiles import prepare_bootstrap_cast
from app.config import get_settings
from app.id_utils import new_session_id, now_iso
from app.models import CreateSessionRequest
from app.npc_runtime import prepare_npc_runtime_map
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
            "files_created": list(empty_files.keys())
            + ["characters/", "state/knowledge/", "state/relationship_pairs/", "pending_bootstrap_prompt.md"],
        }

    def _write_bootstrap_files(self, session_id: str, bootstrap_json: dict[str, Any]) -> list[str]:
        bootstrap_json = normalize_bootstrap_json(bootstrap_json)
        prepare_bootstrap_cast(bootstrap_json)
        prepare_npc_runtime_map(bootstrap_json)

        session = self.storage.read_json(session_id, "session.json", default=bootstrap_json.get("session", {}))
        session["status"] = "active"
        session["updated_at"] = now_iso()
        self.storage.write_json(session_id, "session.json", session)

        user_request = self.storage.read_json(
            session_id,
            "user_request.json",
            default=bootstrap_json.get("user_request", {}),
        )
        self.storage.write_json(session_id, "user_request.json", user_request)
        self.storage.write_json(session_id, "protagonist.json", bootstrap_json["protagonist"])

        characters = bootstrap_json.get("characters", {})
        self.storage.write_json(session_id, "characters_index.json", {"ids": list(characters.keys())})
        for character_id, card in characters.items():
            self.storage.write_character(
                session_id,
                character_id,
                {**card, "id": card.get("id") or character_id},
            )

        knowledge = bootstrap_json.get("knowledge", {})
        self.storage.write_json(
            session_id,
            "state/knowledge_index.json",
            {"ids": [character_id for character_id in knowledge.keys() if not character_id.startswith("_")]},
        )
        for character_id, entry in knowledge.items():
            if not character_id.startswith("_"):
                self.storage.write_character_knowledge(session_id, character_id, entry)

        relationships = bootstrap_json.get("relationships", {})
        self.storage.write_json(
            session_id,
            "state/relationship_index.json",
            {"pair_ids": list(relationships.keys())},
        )
        for relationship_id, entry in relationships.items():
            self.storage.write_relationship_pair(session_id, relationship_id, entry)

        self.storage.write_json(session_id, "story_plan.json", bootstrap_json["story_plan"])
        self.storage.write_json(session_id, "current_state.json", bootstrap_json["current_state"])
        self.storage.write_json(session_id, "npc_state.json", bootstrap_json.get("npc_state", {}))
        self.storage.write_json(session_id, "future_locks.json", bootstrap_json.get("future_locks", {}))
        self.storage.write_json(session_id, "continuity.json", bootstrap_json.get("continuity", {}))
        self.storage.write_json(session_id, "scene_history.json", bootstrap_json.get("scene_history", []))
        self.storage.write_json(session_id, "turns.json", bootstrap_json.get("turns", []))
        return FINAL_BOOTSTRAP_FILES

    def save_bootstrap_preview(self, session_id: str, bootstrap_json: dict[str, Any]) -> dict[str, Any]:
        bootstrap_json = normalize_bootstrap_json(bootstrap_json)
        prepare_bootstrap_cast(bootstrap_json)
        prepare_npc_runtime_map(bootstrap_json)
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
            "message_to_user": preview,
            "session_id": session_id,
            "status": "bootstrap_review_pending",
            "must_show_to_user": True,
            "wait_for_confirmation": True,
            "next_user_action": "Напиши `подтверждаю`, если всё подходит, или скажи, что изменить.",
            "preview": preview,
            "user_visible_preview": preview,
            "can_confirm": True,
            "diagnostics": {
                "character_count": len(bootstrap_json.get("characters", {}) or {}),
                "relationship_count": len(bootstrap_json.get("relationships", {}) or {}),
                "knowledge_count": len(bootstrap_json.get("knowledge", {}) or {}),
                "normalized": True,
                "cast_profiles_enabled": True,
                "npc_runtime_enabled": True,
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
        raise ValueError("Direct bootstrap-result is disabled in v9. Use bootstrap-preview and bootstrap-confirm.")

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
