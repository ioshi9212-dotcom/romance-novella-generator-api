from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
path = ROOT / "tests" / "test_openapi_actions_contract.py"
text = path.read_text(encoding="utf-8")
old = '    assert set(preview_request["properties"]) == {"bootstrap_json"}\n'
new = '''    assert set(preview_request["properties"]) == {
        "bootstrap_json",
        "protagonist",
        "characters",
        "relationships",
        "knowledge",
        "story_plan",
        "director_bible",
        "current_state",
        "npc_state",
        "future_locks",
        "continuity",
        "scene_history",
        "turns",
    }
'''
if new not in text:
    if old not in text:
        raise RuntimeError("BootstrapPreviewRequest property assertion not found")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
