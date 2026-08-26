from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def read_runtime_rules() -> str:
    return (PROJECT_ROOT / "rules" / "rules.md").read_text(encoding="utf-8")


def read_scene_builder() -> str:
    base = (PROJECT_ROOT / "rules" / "scene_builder.md").read_text(encoding="utf-8")
    pov_presence = (PROJECT_ROOT / "rules" / "pov_presence.md").read_text(encoding="utf-8")
    return base + "\n\n" + pov_presence
