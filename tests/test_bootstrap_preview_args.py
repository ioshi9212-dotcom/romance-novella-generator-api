from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models import BootstrapPreviewRequest
from app.novella_openapi_actions import build_openapi_actions


BOOTSTRAP_ROOT_FIELDS = {
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


def test_actions_schema_hides_spilled_bootstrap_fields_from_custom_gpt():
    contract = build_openapi_actions("https://example.invalid")
    schema = contract["components"]["schemas"]["BootstrapPreviewRequest"]

    assert schema["required"] == ["bootstrap_json"]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {"bootstrap_json"}
    assert BOOTSTRAP_ROOT_FIELDS.isdisjoint(schema["properties"])


def test_request_folds_spilled_fields_back_inside_bootstrap_json():
    request = BootstrapPreviewRequest(
        bootstrap_json={"protagonist": {"id": "hero"}},
        characters={"hero": {"id": "hero"}},
        director_bible={"version": 1},
        scene_history=[],
        turns=[],
    )

    assert request.bootstrap_json == {
        "protagonist": {"id": "hero"},
        "characters": {"hero": {"id": "hero"}},
        "director_bible": {"version": 1},
        "scene_history": [],
        "turns": [],
    }


def test_request_allows_identical_duplicate_but_rejects_conflict():
    identical = BootstrapPreviewRequest(
        bootstrap_json={"characters": {"hero": {"id": "hero"}}},
        characters={"hero": {"id": "hero"}},
    )
    assert identical.bootstrap_json["characters"] == {"hero": {"id": "hero"}}

    with pytest.raises(ValidationError, match="Conflicting bootstrap fields"):
        BootstrapPreviewRequest(
            bootstrap_json={"characters": {"hero": {"id": "nested"}}},
            characters={"hero": {"id": "spilled"}},
        )


def test_request_still_rejects_unknown_top_level_garbage():
    with pytest.raises(ValidationError):
        BootstrapPreviewRequest(bootstrap_json={}, unrelated_field="nope")
