"""Check that ChatGPT Actions exactly reflects the supported FastAPI surface."""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


ROOT = Path(__file__).resolve().parents[1]


def test_actions_schema_matches_api_and_has_no_unused_endpoints():
    spec = json.loads((ROOT / "openapi.json").read_text(encoding="utf-8"))
    assert spec["openapi"].startswith("3.1.")
    assert spec["servers"][0]["url"] == "https://novella-yumikofv.waw0.amvera.tech"
    assert "security" not in spec
    assert not spec["components"].get("securitySchemes")

    methods = {"get", "post", "put", "patch", "delete"}
    actual = {
        (method, path) for path, item in app.openapi()["paths"].items()
        for method in item if method in methods and path != "/openapi.json"
    }
    declared = {
        (method, path) for path, item in spec["paths"].items()
        for method in item if method in methods
    }
    assert declared == actual
    ids = [
        endpoint["operationId"]
        for item in spec["paths"].values()
        for method, endpoint in item.items()
        if method in methods
    ]
    assert len(ids) == len(set(ids))
    assert len(ids) <= 30
    assert spec["paths"]["/sessions/{session_id}/data"]["get"]["parameters"][1]["required"] is True

    schemas = spec["components"]["schemas"]
    dynamic = app.openapi()["components"]["schemas"]
    for name in ("CreateNovel", "RawPart", "StageCommand", "SaveDocument",
                 "VerifyNovel", "PrepareTurn", "PatchOperation", "CommitTurn",
                 "AuditPrepare", "AuditCommit", "RollbackTurn", "CompactionCommit"):
        assert set(schemas[name]["properties"]) == set(dynamic[name]["properties"])
    for endpoint in (
        ep for item in spec["paths"].values()
        for method, ep in item.items() if method in methods
    ):
        for parameter in endpoint.get("parameters", []):
            if parameter["in"] == "path":
                assert parameter["required"] is True



def test_gpt_actions_operation_description_limits():
    """The GPT editor rejects operation descriptions and summaries over 300 chars."""
    spec = json.loads((ROOT / "openapi.json").read_text(encoding="utf-8"))
    operations = [
        (path, method, operation)
        for path, methods in spec["paths"].items()
        for method, operation in methods.items()
        if method in {"get", "post", "put", "patch", "delete"}
    ]
    assert len(operations) == 20
    assert not spec.get("security")
    assert not spec["components"].get("securitySchemes")
    for path, method, operation in operations:
        assert operation.get("operationId"), (path, method)
        for field in ("summary", "description"):
            assert len(operation.get(field, "")) <= 300, (path, method, field)
        for parameter in operation.get("parameters", []):
            assert len(parameter.get("description", "")) <= 700, (path, method)
    assert spec["paths"]["/chunks/{read_id}/{chunk_index}"]["get"]["operationId"] == "getResponseChunk"


def test_every_openapi_object_schema_declares_properties():
    """GPT Actions rejects otherwise-valid maps when 'properties' is absent.

    Include nested objects and every response, not just components/schemas.
    Dynamic maps must keep additionalProperties to preserve novel document IDs.
    """
    spec = json.loads((ROOT / "openapi.json").read_text(encoding="utf-8"))

    def visit(node, location):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert "properties" in node, f"Object schema missing properties: {location}"
                assert isinstance(node["properties"], dict)
            for name, value in node.items():
                visit(value, f"{location}/{name}")
        elif isinstance(node, list):
            for idx, value in enumerate(node):
                visit(value, f"{location}/{idx}")

    visit(spec, "$")
    methods = {"get", "post", "put", "patch", "delete"}
    for route, items in spec["paths"].items():
        for method, operation in items.items():
            if method not in methods:
                continue
            response = operation["responses"]["200"]["content"]["application/json"]["schema"]
            assert response["type"] == "object", (route, method)
            assert response["properties"], (route, method)
    for name, expected_type in (
        ("SaveDocument", "document"),
        ("CommitTurn", "updates"),
        ("AuditCommit", "updates"),
        ("CompactionCommit", "character_summaries"),
    ):
        dynamic = spec["components"]["schemas"][name]["properties"][expected_type]
        assert "additionalProperties" in dynamic, name


def test_gpt_instructions_under_8000_chars():
    text = (ROOT / "gpt/custom_gpt_instructions.md").read_text(encoding="utf-8")
    assert len(text) <= 8000
    assert "Rules" in text and "Skin Builder" in text
    assert "getRuntimeInstructions" in text


def test_runtime_documents_are_public_and_cachable(monkeypatch):
    client = TestClient(app)
    first = client.get("/runtime", headers={})
    assert first.status_code == 200
    data = first.json()
    if data.get("chunked"):
        chunks = {0: data["content"]}
        next_index = data["next_chunk_index"]
        while next_index is not None:
            result = client.get(
                f"/chunks/{data['read_id']}/{next_index}",
                headers={}
            )
            assert result.status_code == 200, result.text
            chunk = result.json()
            chunks[next_index] = chunk["content"]
            next_index = chunk["next_chunk_index"]
        data = json.loads("".join(chunks[index] for index in range(data["chunk_count"])))
    assert data["changed"] is True
    assert data["rules"].startswith("# Rules")
    assert data["skin_builder"] == (ROOT / "runtime/scene_builder.md").read_text(encoding="utf-8")
    assert len(data["sha256"]) == 64
    second = client.get("/runtime", headers={},
                        params={"known_sha256": data["sha256"]})
    assert second.status_code == 200
    assert second.json() == {
        "sha256": data["sha256"], "changed": False, "rules": "", "skin_builder": ""
    }
