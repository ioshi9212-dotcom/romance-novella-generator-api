from __future__ import annotations

from typing import Any


QUESTIONNAIRE_COMPLETION_POLICY: dict[str, Any] = {
    "preserve_explicit_user_data": True,
    "user_may_skip_questionnaire_items": True,
    "ordinary_missing_fields": "director_invents_and_saves",
    "ask_user_only_for": [
        "material contradictions",
        "unresolved boundaries",
        "choices that materially change the requested novel",
    ],
}
