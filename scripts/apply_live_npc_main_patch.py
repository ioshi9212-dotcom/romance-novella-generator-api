from pathlib import Path


path = Path("app/main.py")
text = path.read_text(encoding="utf-8")

old_import = "from app.models import ApplyTurnResultRequest, ApplyTurnResultResponse, BootstrapPreviewRequest, BootstrapPreviewResponse, BootstrapConfirmRequest, BootstrapConfirmResponse, CreateSessionRequest, CreateSessionResponse, DebugSessionDumpResponse, TurnPromptChunkResponse, TurnRequest, TurnResponse\nfrom app.scene_response_normalizer import normalize_scene_response\n"
new_import = "from app.models import ApplyTurnResultRequest, ApplyTurnResultResponse, BootstrapPreviewRequest, BootstrapPreviewResponse, BootstrapConfirmRequest, BootstrapConfirmResponse, CreateSessionRequest, CreateSessionResponse, DebugSessionDumpResponse, TurnPromptChunkResponse, TurnRequest, TurnResponse\nfrom app.npc_state_updates import apply_npc_state_patches\nfrom app.scene_response_normalizer import normalize_scene_response\n"

old_apply = "            result = updater.apply_scene_response(session_id, normalized_scene_response)\n            _mark_pending_turn_applied(manager, session_id, pending)\n"
new_apply = "            result = updater.apply_scene_response(session_id, normalized_scene_response)\n            result = apply_npc_state_patches(\n                manager.storage,\n                session_id,\n                normalized_scene_response,\n                bundle,\n                result,\n            )\n            _mark_pending_turn_applied(manager, session_id, pending)\n"

if old_import not in text:
    raise SystemExit("expected main import block not found")
if old_apply not in text:
    raise SystemExit("expected apply-turn block not found")

text = text.replace(old_import, new_import, 1).replace(old_apply, new_apply, 1)
path.write_text(text, encoding="utf-8")
