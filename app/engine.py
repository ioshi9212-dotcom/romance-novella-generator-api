import json
from pathlib import Path


class PromptEngine:
    def __init__(self, prompts_dir: Path):
        self.prompts_dir = prompts_dir

    def _read_prompt(self, name: str) -> str:
        path = self.prompts_dir / name
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def build_manual_prompt(self, session_data: dict, player_input: str) -> str:
        scene_writer = self._read_prompt("scene_writer.md")
        logic_checker = self._read_prompt("logic_checker.md")
        state_updater = self._read_prompt("state_updater.md")

        payload = {
            "session": session_data["session"],
            "current_state": session_data["current_state"],
            "player_character": session_data["player_character"],
            "characters": session_data["characters"],
            "relationships": session_data["relationships"],
            "knowledge_map": session_data["knowledge_map"],
            "npc_life_state": session_data["npc_life_state"],
            "story_compass": session_data["story_compass"],
            "recent_scene_history": session_data["scene_history"][-5:],
            "player_input": player_input,
        }

        return (
            "Ты — движок живой интерактивной новеллы.\n"
            "Сначала строго учитывай память сессии, потом действие игрока.\n\n"
            "# SCENE WRITER RULES\n"
            f"{scene_writer}\n\n"
            "# LOGIC CHECKER RULES\n"
            f"{logic_checker}\n\n"
            "# STATE UPDATER RULES\n"
            f"{state_updater}\n\n"
            "# SESSION PAYLOAD JSON\n"
            "```json\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n"
            "```\n\n"
            "# OUTPUT FORMAT\n"
            "Верни результат строго в таком виде:\n\n"
            "## SCENE\n"
            "Текст сцены в формате новеллы.\n\n"
            "## STATE_UPDATE_JSON\n"
            "```json\n{}\n```\n\n"
            "## KNOWLEDGE_UPDATE_JSON\n"
            "```json\n{}\n```\n\n"
            "## NPC_LIFE_UPDATE_JSON\n"
            "```json\n{}\n```\n\n"
            "## LOGIC_NOTES\n"
            "Коротко перечисли, что было проверено.\n"
        )

    def local_stub_scene(self, session_data: dict, player_input: str) -> dict:
        current = session_data["current_state"]
        player = session_data["player_character"]
        name = player.get("name", "Noa")
        location = current.get("location", "unknown place")
        time = current.get("time", "unknown time")
        scene_text = (
            f"*{location}. {time}. Воздух кажется неподвижным, "
            "а мелкие детали вокруг требуют внимания: свет, тени, следы, чужие паузы.*\n\n"
            f"*{name} не делает резких выводов. Сначала — наблюдение. Потом решение.*\n\n"
            f"**System** — Получено действие игрока: {player_input}"
        )
        return {
            "scene_text": scene_text,
            "state_update": {
                "last_player_input": player_input,
            },
            "knowledge_update": {},
            "npc_life_update": {},
            "notes": ["Local stub used. Paste manual prompt into GPT for real generation."],
        }
