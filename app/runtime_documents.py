from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@lru_cache(maxsize=1)
def read_runtime_rules() -> str:
    return (PROJECT_ROOT / "rules" / "turn_runtime.md").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def read_scene_builder() -> str:
    return (PROJECT_ROOT / "rules" / "scene_builder.md").read_text(encoding="utf-8")
