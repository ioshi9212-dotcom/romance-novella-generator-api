from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def read_runtime_rules() -> str:
    base = (PROJECT_ROOT / "rules" / "rules.md").read_text(encoding="utf-8")
    knowledge = (PROJECT_ROOT / "rules" / "knowledge_boundaries.md").read_text(
        encoding="utf-8"
    )
    return base.rstrip() + "\n\n" + knowledge.strip() + "\n"


def read_scene_builder() -> str:
    return (PROJECT_ROOT / "rules" / "scene_builder.md").read_text(encoding="utf-8")
