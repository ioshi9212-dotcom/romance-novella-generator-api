from pathlib import Path

import yaml

from app.main import app


def test_actions_have_no_auth_and_only_session_scoped_runtime_operations() -> None:
    app.openapi_schema = None
    schema = app.openapi()
    assert schema["security"] == []
    assert "securitySchemes" not in schema.get("components", {})

    operation_ids = {
        operation["operationId"]
        for path_item in schema["paths"].values()
        for operation in path_item.values()
    }
    assert operation_ids == {
        "createSession",
        "getTurnPacket",
        "getTurnPacketChunk",
        "commitTurn",
        "getAuditPacket",
        "getAuditPacketChunk",
        "commitAudit",
        "getChronologyPage",
    }
    assert not any("latest" in path.lower() for path in schema["paths"])
    assert not any("list" in operation.lower() for operation in operation_ids)
    for path_item in schema["paths"].values():
        for operation in path_item.values():
            assert operation["security"] == []


def test_every_openapi_array_has_items_and_object_has_properties() -> None:
    app.openapi_schema = None
    schema = app.openapi()

    def walk(value):
        if isinstance(value, dict):
            if value.get("type") == "array":
                assert "items" in value
            if value.get("type") == "object":
                assert "properties" in value
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(schema)


def test_committed_actions_schema_matches_application() -> None:
    app.openapi_schema = None
    generated = app.openapi()
    committed = yaml.safe_load(Path("openapi.yaml").read_text(encoding="utf-8"))
    assert committed == generated


def test_create_session_requires_positive_player_confirmation(
    client, session_payload
) -> None:
    missing = dict(session_payload)
    missing.pop("player_confirmation")
    assert client.post("/api/v1/sessions", json=missing).status_code == 422

    negative = {
        **session_payload,
        "player_confirmation": "Не подтверждаю, исправь превью",
    }
    response = client.post("/api/v1/sessions", json=negative)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PLAYER_CONFIRMATION_REQUIRED"
