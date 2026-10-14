"""Source-backed initial relationship review, before starting a novel.

No fixed emotion names and no artificial minimum number of metrics. The model
must list each distinct canon-grounded facet *before* calling verify. We can
verify the mapping and its exact source evidence, but not infer from prose any
unlisted feelings: this distinction is important and documented.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value).casefold()).strip()


def verify_initial_relationship_review(
    folder: Path, roster: list[dict[str, Any]], relationships: dict[str, Any],
    pov_id: str,
) -> list[str]:
    issues: list[str] = []
    expected = {
        member["id"] for member in roster
        if isinstance(member, dict) and isinstance(member.get("id"), str)
        and member["id"] != pov_id
    }
    review = relationships.get("стартовая_сверка")
    if not isinstance(review, dict):
        return [
            "RELATIONSHIP_REVIEW_REQUIRED: Нет стартовая_сверка в отношения.json. "
            "Сначала для КАЖДОГО NPC разберись с RAW, отдельно перечисли все "
            "независимые грани сложившихся отношений и свяжи их с показателями. "
            "Для незнакомых укажи не_знакомы с пустыми аспектами и параметрами."
        ]

    skipped = sorted(expected - set(review))
    unexpected = sorted(set(review) - expected)
    if skipped:
        issues.append("RELATIONSHIP_REVIEW_INCOMPLETE: Не проверены NPC: " + ", ".join(skipped))
    if unexpected:
        issues.append("RELATIONSHIP_REVIEW_INVALID: Неизвестные или POV ID: " + ", ".join(unexpected))

    try:
        raw = _normalized((folder / "raw.txt").read_text(encoding="utf-8"))
    except OSError:
        return ["RELATIONSHIP_REVIEW_REQUIRED: Исходный RAW недоступен для сверки."]
    owners = relationships.get("персонажи")
    if not isinstance(owners, dict):
        return issues  # Structural foundation check reports malformed owners.

    for cid in sorted(expected & set(review)):
        item = review[cid]
        if not isinstance(item, dict):
            issues.append(f"Стартовая сверка {cid}: требуется объект")
            continue
        status = item.get("статус")
        facets = item.get("аспекты")
        if status not in {"есть_история", "не_знакомы"}:
            issues.append(f"Стартовая сверка {cid}: статус должен быть есть_история или не_знакомы")
            continue
        if not isinstance(facets, list):
            issues.append(f"Стартовая сверка {cid}: аспекты должны быть списком")
            continue
        owner = owners.get(cid, {})
        if not isinstance(owner, dict):
            continue
        pov = owner.get("к_POV", {})
        if not isinstance(pov, dict):
            continue
        metrics = pov.get("параметры", {})
        if not isinstance(metrics, dict):
            continue

        if status == "не_знакомы":
            if facets or metrics:
                issues.append(
                    f"Стартовая сверка {cid}: для незнакомых не создавай "
                    "доканонические чувства, аспекты или числа."
                )
            continue

        extracted: set[str] = set()
        source_quotes: set[str] = set()
        for n, facet in enumerate(facets):
            if not isinstance(facet, dict):
                issues.append(f"Стартовая сверка {cid}, аспект {n}: требуется объект")
                continue
            metric = facet.get("показатель")
            evidence = facet.get("цитата_из_RAW")
            if not isinstance(metric, str) or not metric.strip():
                issues.append(f"Стартовая сверка {cid}, аспект {n}: нет названия показателя")
                continue
            if metric in extracted:
                issues.append(f"Стартовая сверка {cid}: показатель {metric!r} повторяется")
            extracted.add(metric)
            if not isinstance(evidence, str) or len(_normalized(evidence)) < 12:
                issues.append(f"Стартовая сверка {cid}, {metric}: нужна точная цитата из RAW (от 12 символов)")
                continue
            quote = _normalized(evidence)
            if quote not in raw:
                issues.append(
                    f"Стартовая сверка {cid}, {metric}: цитата не найдена дословно в RAW. "
                    "Не придумывай основание, перечитай оригинал."
                )
            if quote in source_quotes:
                issues.append(
                    f"Стартовая сверка {cid}: одна и та же цитата использована для "
                    "нескольких показателей. Выдели самостоятельные источники."
                )
            source_quotes.add(quote)

        if set(metrics) != extracted:
            lost = sorted(extracted - set(metrics))
            unsupported = sorted(set(metrics) - extracted)
            issues.append(
                f"RELATIONSHIP_REVIEW_INCOMPLETE {cid}: "
                f"не перенесены в параметры {lost}; нет подтверждённых аспектов для {unsupported}."
            )

    return issues
