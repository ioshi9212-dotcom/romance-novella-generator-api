from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models import BootstrapPreviewRequest
from app.novella_openapi_actions import build_openapi_actions


def test_actions_schema_exposes_only_nested_bootstrap_json():
    contract = build_openapi_actions("https://example.invalid")
    schema = contract["components"]["schemas"]["BootstrapPreviewRequest"]

    assert set(schema["required"]) == {"bootstrap_json"}
    assert set(schema["properties"]) == {"bootstrap_json"}
    operation = contract["paths"]["/api/v1/sessions/{session_id}/bootstrap-preview"]["post"]
    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert request_schema == {"$ref": "#/components/schemas/BootstrapPreviewRequest"}


def test_backend_folds_legacy_spilled_fields_back_inside_bootstrap_json():
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


def test_backend_allows_identical_duplicate_but_rejects_conflict():
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


def test_backend_still_rejects_unknown_top_level_garbage():
    with pytest.raises(ValidationError):
        BootstrapPreviewRequest(bootstrap_json={}, unrelated_field="nope")
