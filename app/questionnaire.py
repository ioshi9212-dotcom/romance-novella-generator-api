from __future__ import annotations

import hashlib
from typing import Any

from app.models import QuestionnaireRequest
from app.policies import QUESTIONNAIRE_COMPLETION_POLICY
from app.storage import json_text, utc_now


def new_questionnaire_document(
    request: QuestionnaireRequest | None = None,
    *,
    confirmed_questionnaire: str | None = None,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "completion_policy": QUESTIONNAIRE_COMPLETION_POLICY,
        "entries": [],
    }
    if confirmed_questionnaire is not None:
        document["confirmation"] = {
            "status": "confirmed",
            "confirmed_at": utc_now(),
            "questionnaire": confirmed_questionnaire,
        }
    if request is not None:
        append_questionnaire_entry(document, request)
    return document


def append_questionnaire_entry(
    document: dict[str, Any],
    request: QuestionnaireRequest,
) -> tuple[str, bool]:
    document["completion_policy"] = QUESTIONNAIRE_COMPLETION_POLICY
    entries = document.setdefault("entries", [])
    if not isinstance(entries, list):
        entries = []
        document["entries"] = entries

    request_data = request.model_dump()
    entry_id = hashlib.sha256(json_text(request_data).encode("utf-8")).hexdigest()[:20]
    if any(
        isinstance(entry, dict) and entry.get("entry_id") == entry_id
        for entry in entries
    ):
        return entry_id, False

    entries.append(
        {
            "entry_id": entry_id,
            "saved_at": utc_now(),
            **request_data,
        }
    )
    return entry_id, True
