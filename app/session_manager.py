from pathlib import Path
from typing import Any

from app.bootstrap_normalizer import normalize_bootstrap_json
from app.bootstrap_preview_transport import BOOTSTRAP_STAGING_TRANSPORT_RULES, build_bootstrap_preview_response, get_bootstrap_preview_chunk
from app.bootstrap_setup import build_bootstrap_prompt, build_setup_preview
from app.bootstrapper import BASE_FILES, debug_stub_bootstrap
from app.character_profiles import prepare_bootstrap_cast
from app.config import get_settings
from app.directional_relationships import BOOTSTRAP_DIRECTION_RULES, append_directional_preview, prepare_directional_relationships
from app.director_bible import prepare_director_bible
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
    "director_bible.json",
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
    raw = " ".join((request.raw_start_text or "").strip().lower().replace("ё", "е").split())
    start_command = raw.strip(" .!?")
    if start_command in {
        "начнем",
        "старт",
        "создай сессию",
        "новая сессия",
        "новая игра",
    }:
        return True

    # A non-command raw message is the canonical questionnaire answer. It may be
    # deliberately incomplete: unspecified details are generated during bootstrap.
    if raw:
        return False

    meaningful_text = [
        (request.title or "").strip(),
        request.genre.strip(),
        request.setting_request.strip(),
        request.protagonist_request.strip(),
        (request.romance_request or "").strip(),
        (request.tone or "").strip(),
        (request.rating or "").strip(),
    ]
    has_explicit_input = any(meaningful_text) or bool(request.avoid) or bool(request.extra)
    return not has_explicit_input


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
            "director_bible.json": {},
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

        prompt = (
            build_bootstrap_prompt(user_request)
            + "\n\n"
            + BOOTSTRAP_DIRECTION_RULES
            + "\n\n"
            + BOOTSTRAP_STAGING_TRANSPORT_RULES
        )
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
        prepare_directional_relationships(bootstrap_json)
        prepare_npc_runtime_map(bootstrap_json)
        prepare_director_bible(bootstrap_json)

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
        self.storage.write_json(session_id, "director_bible.json", bootstrap_json.get("director_bible", {}))
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
        prepare_director_bible(bootstrap_json)
        session = self.storage.read_json(session_id, "session.json")
        if session.get("status") not in {"bootstrap_pending", "bootstrap_review_pending"}:
            raise ValueError(f"Cannot create bootstrap preview for session status: {session.get('status')}")

        user_request = self.storage.read_json(session_id, "user_request.json", default={})
        preview = append_directional_preview(
            build_setup_preview(
                bootstrap_json,
                user_request=user_request if isinstance(user_request, dict) else {},
            ),
            bootstrap_json,
        )
        self.storage.write_json(session_id, "pending_bootstrap.json", bootstrap_json)
        (self.storage.session_dir(session_id) / "pending_setup_preview.md").write_text(preview, encoding="utf-8")
        session["status"] = "bootstrap_review_pending"
        session["updated_at"] = now_iso()
        self.storage.write_json(session_id, "session.json", session)
        return build_bootstrap_preview_response(
            self.storage,
            session_id,
            preview,
            diagnostics={
                "character_count": len(bootstrap_json.get("characters", {}) or {}),
                "relationship_count": len(bootstrap_json.get("relationships", {}) or {}),
                "knowledge_count": len(bootstrap_json.get("knowledge", {}) or {}),
                "normalized": True,
                "cast_profiles_enabled": True,
                "npc_runtime_enabled": True,
                "directional_relationships_enabled": True,
                "director_bible_enabled": True,
                "event_queue_count": len((bootstrap_json.get("director_bible") or {}).get("event_queue", [])),
            },
        )

    def get_bootstrap_preview_chunk(
        self,
        session_id: str,
        chunk_index: int,
        *,
        preview_id: str | None = None,
    ) -> dict[str, Any]:
        return get_bootstrap_preview_chunk(
            self.storage,
            session_id,
            chunk_index,
            expected_preview_id=preview_id,
        )

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
