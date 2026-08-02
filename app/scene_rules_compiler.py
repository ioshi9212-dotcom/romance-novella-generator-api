from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Iterable


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
MAX_COMPILED_RULE_CHARS = 18_000


@dataclass(frozen=True)
class RuleSource:
    section_id: str
    relative_path: str
    required_anchors: tuple[str, ...]


RULE_SOURCES: tuple[RuleSource, ...] = (
    RuleSource(
        "PLAYER_INPUT",
        "prompts/player_input_rules.md",
        ("Вне скобок", "В скобках", "порядок", "бытовой ответ"),
    ),
    RuleSource(
        "PLAYER_AGENCY",
        "rules/player_agency.md",
        ("личные решения", "NPC", "не ставит мир на паузу"),
    ),
    RuleSource(
        "NPC_BEHAVIOR",
        "prompts/npc_rules.md",
        ("свои цели", "не консультанты", "не читают мысли", "не замораживаются"),
    ),
    RuleSource(
        "KNOWLEDGE",
        "prompts/knowledge_rules.md",
        ("источник", "wrong_belief", "source_in_scene"),
    ),
    RuleSource(
        "RELATIONSHIPS",
        "prompts/relationship_rules.md",
        ("a_to_b", "b_to_a", "direction_patch", "не зеркал"),
    ),
    RuleSource(
        "HIDDEN_CONTENT",
        "rules/hidden_character_rules.md",
        ("hidden_core", "полная карточка", "не раскры"),
    ),
    RuleSource(
        "DIRECTOR_BIBLE",
        "rules/director_bible_rules.md",
        ("director_guidance", "event_queue", "author_only", "director_bible_patches"),
    ),
    RuleSource(
        "SCENE_STYLE",
        "rules/scene_style.md",
        ("meaningful beat", "показывай", "подтекст", "психологическая инерция"),
    ),
    RuleSource(
        "NO_MICRO_CHOICE",
        "rules/no_micro_choice.md",
        ("микровыбор", "последствия", "границ"),
    ),
    RuleSource(
        "TIME_SKIP",
        "rules/time_skip_rules.md",
        ("time_skip_control", "advanceTime", "time_skip_result", "event_queue"),
    ),
    RuleSource(
        "SCENE_FORMAT",
        "prompts/scene_format_rules.md",
        ("rendered_text", "ровно 3", "relationships_panel", "proposed_updates"),
    ),
)


class SceneRulesCompileError(RuntimeError):
    pass


def _normalise_markdown(text: str) -> str:
    """Compact canonical markdown without changing rule meaning."""
    output: list[str] = []
    seen_rule_lines: set[str] = set()
    blank_pending = False

    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            blank_pending = bool(output)
            continue
        if stripped.startswith("# "):
            # The compiler supplies a stable section header.
            continue

        comparison = " ".join(stripped.lower().split())
        is_rule_line = stripped.startswith(("- ", "1. ", "2. ", "3. ", "4. ", "5. ", "6. ", "7. ", "8. ", "9. "))
        if is_rule_line and comparison in seen_rule_lines:
            continue
        if is_rule_line:
            seen_rule_lines.add(comparison)

        if blank_pending and output and output[-1] != "":
            output.append("")
        blank_pending = False
        output.append(stripped)

    while output and output[-1] == "":
        output.pop()
    return "\n".join(output)


def _read_source(root: Path, source: RuleSource) -> tuple[str, str]:
    path = root / source.relative_path
    if not path.is_file():
        raise SceneRulesCompileError(f"Missing scene rule source: {source.relative_path}")
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    missing = [anchor for anchor in source.required_anchors if anchor.lower() not in lowered]
    if missing:
        raise SceneRulesCompileError(
            f"Scene rule source {source.relative_path} is stale; missing anchors: {missing}"
        )
    compact = _normalise_markdown(text)
    if not compact:
        raise SceneRulesCompileError(f"Empty scene rule source: {source.relative_path}")
    return compact, sha256(text.encode("utf-8")).hexdigest()


def compile_scene_rules(root: Path | None = None) -> str:
    root = Path(root) if root is not None else REPOSITORY_ROOT
    sections: list[str] = []
    for source in RULE_SOURCES:
        compact, _ = _read_source(root, source)
        sections.append(f"## {source.section_id}\nSOURCE: {source.relative_path}\n{compact}")

    compiled = "\n\n".join(sections).strip()
    if len(compiled) > MAX_COMPILED_RULE_CHARS:
        raise SceneRulesCompileError(
            f"Compiled scene rules are too large: {len(compiled)} > {MAX_COMPILED_RULE_CHARS}"
        )
    return compiled


def scene_rules_diagnostics(root: Path | None = None) -> dict[str, object]:
    root = Path(root) if root is not None else REPOSITORY_ROOT
    hashes: dict[str, str] = {}
    for source in RULE_SOURCES:
        _, digest = _read_source(root, source)
        hashes[source.relative_path] = digest
    compiled = compile_scene_rules(root)
    return {
        "source_count": len(RULE_SOURCES),
        "sources": [source.relative_path for source in RULE_SOURCES],
        "source_sha256": hashes,
        "compiled_chars": len(compiled),
        "compiled_sha256": sha256(compiled.encode("utf-8")).hexdigest(),
        "max_compiled_chars": MAX_COMPILED_RULE_CHARS,
    }
