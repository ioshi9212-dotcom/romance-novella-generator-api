from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.models import CreateSessionRequest, ManualResultRequest
from app.storage import JsonStorage


class SessionManager:
    def __init__(self, data_dir: Path, templates_dir: Path):
        self.data_dir = data_dir
        self.templates_dir = templates_dir
        self.storage = JsonStorage(data_dir)
        self.sessions_dir = data_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def _session_dir(self, session_id: str) -> Path:
        return self.sessions_dir / session_id

    def _template(self) -> dict:
        template_path = self.templates_dir / "session_template.json"
        return JsonStorage(self.templates_dir).read_json(template_path)

    def create_session(self, request: CreateSessionRequest) -> dict:
        session_id = f"session_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
        session_dir = self._session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)

        template = deepcopy(self._template())
        now = datetime.now(timezone.utc).isoformat()

        template["session"]["session_id"] = session_id
        template["session"]["title"] = request.title
        template["session"]["genre"] = request.genre
        template["session"]["created_at"] = now
        template["session"]["updated_at"] = now
        template["player_character"]["name"] = request.player_name
        template["current_state"]["turn_number"] = 0

        for filename, content in {
            "session.json": template["session"],
            "current_state.json": template["current_state"],
            "player_character.json": template["player_character"],
            "characters.json": template["characters"],
            "relationships.json": template["relationships"],
            "knowledge_map.json": template["knowledge_map"],
            "npc_life_state.json": template["npc_life_state"],
            "story_compass.json": template["story_compass"],
            "scene_history.json": [],
            "turns.json": [],
        }.items():
            self.storage.write_json(session_dir / filename, content)

        return self.load_session(session_id)

    def list_sessions(self) -> list[dict]:
        sessions = []
        for session_dir in self.storage.list_dirs(self.sessions_dir):
            try:
                session = self.storage.read_json(session_dir / "session.json")
                current_state = self.storage.read_json(session_dir / "current_state.json", default={})
                sessions.append({
                    "session_id": session["session_id"],
                    "title": session.get("title", "Untitled"),
                    "genre": session.get("genre", "unknown"),
                    "turn_number": current_state.get("turn_number", 0),
                    "current_location": current_state.get("location"),
                    "current_time": current_state.get("time"),
                })
            except FileNotFoundError:
                continue
        return sessions

    def load_session(self, session_id: str) -> dict:
        session_dir = self._session_dir(session_id)
        if not session_dir.exists():
            raise FileNotFoundError(session_id)
        return {
            "session": self.storage.read_json(session_dir / "session.json"),
            "current_state": self.storage.read_json(session_dir / "current_state.json"),
            "player_character": self.storage.read_json(session_dir / "player_character.json"),
            "characters": self.storage.read_json(session_dir / "characters.json"),
            "relationships": self.storage.read_json(session_dir / "relationships.json"),
            "knowledge_map": self.storage.read_json(session_dir / "knowledge_map.json"),
            "npc_life_state": self.storage.read_json(session_dir / "npc_life_state.json"),
            "story_compass": self.storage.read_json(session_dir / "story_compass.json"),
            "scene_history": self.storage.read_json(session_dir / "scene_history.json", default=[]),
            "turns": self.storage.read_json(session_dir / "turns.json", default=[]),
        }

    def save_manual_result(self, session_id: str, request: ManualResultRequest) -> dict:
        data = self.load_session(session_id)
        session_dir = self._session_dir(session_id)
        now = datetime.now(timezone.utc).isoformat()

        current_state = data["current_state"]
        current_state.update(request.state_update)
        current_state["turn_number"] = int(current_state.get("turn_number", 0)) + 1
        current_state["last_player_input"] = request.player_input

        scene_history = data["scene_history"]
        scene_history.append({
            "turn_number": current_state["turn_number"],
            "player_input": request.player_input,
            "scene_text": request.scene_text,
            "created_at": now,
            "notes": request.notes,
        })

        turns = data["turns"]
        turns.append({
            "turn_number": current_state["turn_number"],
            "player_input": request.player_input,
            "scene_text": request.scene_text,
            "state_update": request.state_update,
            "knowledge_update": request.knowledge_update,
            "npc_life_update": request.npc_life_update,
            "created_at": now,
        })

        knowledge_map = data["knowledge_map"]
        for character_id, patch in request.knowledge_update.items():
            character_memory = knowledge_map.setdefault(character_id, {"knows": [], "does_not_know": []})
            for item in patch.get("add_knows", []):
                if item not in character_memory.setdefault("knows", []):
                    character_memory["knows"].append(item)
            for item in patch.get("remove_does_not_know", []):
                if item in character_memory.setdefault("does_not_know", []):
                    character_memory["does_not_know"].remove(item)

        npc_life_state = data["npc_life_state"]
        for npc_id, patch in request.npc_life_update.items():
            npc_life_state.setdefault(npc_id, {}).update(patch)

        session = data["session"]
        session["updated_at"] = now

        self.storage.write_json(session_dir / "session.json", session)
        self.storage.write_json(session_dir / "current_state.json", current_state)
        self.storage.write_json(session_dir / "knowledge_map.json", knowledge_map)
        self.storage.write_json(session_dir / "npc_life_state.json", npc_life_state)
        self.storage.write_json(session_dir / "scene_history.json", scene_history)
        self.storage.write_json(session_dir / "turns.json", turns)

        return self.load_session(session_id)
