After writing the scene, propose only minimal state updates that are actually supported by the scene.

Return JSON patches for:
- state_update: time, location, active_characters, scene_goal, last_player_input, environment changes.
- knowledge_update: only add knowledge to characters who were present, were told, saw evidence, or logically inferred something imperfectly.
- npc_life_update: update NPC location, mood, activity, plans, or private events only when the scene justifies it.

Do not update absent NPC knowledge unless there is a messenger, report, visible evidence, or delayed offscreen event.
Do not overwrite fixed character canon unless the story explicitly reveals a disguise, injury, or real change.
Do not mark emotional intimacy, trust, romance, forgiveness, or loyalty unless the player clearly chose it or the scene strongly supports it.

Suggested JSON shape:
{
  "state_update": {},
  "knowledge_update": {
    "character_id": {
      "add_knows": [],
      "remove_does_not_know": []
    }
  },
  "npc_life_update": {
    "character_id": {}
  }
}
