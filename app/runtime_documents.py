from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def read_runtime_rules() -> str:
    return (PROJECT_ROOT / "rules" / "rules.md").read_text(encoding="utf-8")


def read_scene_builder() -> str:
    base = (PROJECT_ROOT / "rules" / "scene_builder.md").read_text(encoding="utf-8").rstrip()
    cinematic = (PROJECT_ROOT / "rules" / "cinematic_coverage.md").read_text(encoding="utf-8").strip()
    return base + "\n\n" + cinematic + "\n"
