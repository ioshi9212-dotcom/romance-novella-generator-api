from typing import Any
from pathlib import Path
from app.scene_contract_builder import build_scene_contract


def build_scene_prompt(scene_contract: dict[str, Any]) -> str:
    prompt_path = Path(__file__).resolve().parent.parent / "prompts" / "scene_writer.md"
    rules = prompt_path.read_text(encoding="utf-8")
    return f"{rules}\n\nSCENE_CONTRACT_JSON:\n{scene_contract}"


def process_turn_manual(bundle: dict[str, Any], player_input: str) -> dict[str, Any]:
    contract = build_scene_contract(bundle, player_input=player_input)
    return {
        "status": "manual_prompt_ready",
        "scene_prompt": build_scene_prompt(contract),
        "diagnostics": {
            "loaded_character_count": len(contract.get("loaded_characters", [])),
            "loaded_relationship_count": len(contract.get("loaded_relationships", [])),
        },
    }


def process_turn_local_stub(bundle: dict[str, Any], player_input: str) -> dict[str, Any]:
    contract = build_scene_contract(bundle, player_input=player_input)
    pov_id = contract["current_frame"]["pov_character_id"]
    pov_card = next((c["card"] for c in contract["loaded_characters"] if c["character_id"] == pov_id), {})
    name = pov_card.get("name", "Героиня")
    location = contract["current_frame"].get("location") or "место сцены"

    scene = (
        f"*{name} остаётся в точке: {location}. Последнее действие игрока принято как якорь сцены: "
        f"{player_input!r}. Воздух вокруг держит паузу, а история пока не делает выбор за неё.*"
    )

    scene_response = {
        "response_version": "novella.scene_response.v1",
        "player_input": player_input,
        "scene": {
            "body": scene,
            "footer": {
                "state": ["Ход обработан local_stub."],
                "relationships": []
            }
        },
        "summary": "Тестовый ход local_stub без настоящей генерации сцены.",
        "important_facts": [],
        "witnesses": contract["current_frame"].get("active_character_ids", []),
        "proposed_updates": {
            "scene_state_patch": {
                "scene_goal": "Продолжить сцену после последнего действия игрока."
            },
            "relationship_patches": [],
            "knowledge_patches": [],
            "new_or_updated_characters": []
        },
        "safety_checks": {
            "used_only_loaded_characters": True,
            "respected_knowledge_boundaries": True,
            "no_hidden_future_reveal": True,
            "no_major_pov_choice_for_player": True,
            "notes": ["local_stub не является полноценным писателем сцены"]
        }
    }

    return {
        "status": "scene_ready",
        "scene": scene,
        "scene_response": scene_response,
        "diagnostics": {
            "loaded_character_count": len(contract.get("loaded_characters", [])),
            "loaded_relationship_count": len(contract.get("loaded_relationships", [])),
        },
    }
