from pathlib import Path


path = Path("app/main.py")
text = path.read_text(encoding="utf-8")

old_import = "from app.npc_state_updates import apply_npc_state_patches"
new_import = "from app.npc_state_updates import apply_npc_state_patches, scene_response_for_base_updater"
old_call = "result = updater.apply_scene_response(session_id, normalized_scene_response)"
new_call = "result = updater.apply_scene_response(session_id, scene_response_for_base_updater(normalized_scene_response))"

if old_import in text:
    text = text.replace(old_import, new_import, 1)
elif new_import not in text:
    raise SystemExit("Expected npc_state_updates import not found")

if old_call in text:
    text = text.replace(old_call, new_call, 1)
elif new_call not in text:
    raise SystemExit("Expected StateUpdater call not found")

path.write_text(text, encoding="utf-8")
