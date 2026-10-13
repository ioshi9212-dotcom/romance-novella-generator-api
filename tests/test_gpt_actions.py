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
    assert spec["components"]["securitySchemes"]["ApiKeyAuth"]["name"] == "X-API-Key"

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


def test_gpt_instructions_under_8000_chars():
    text = (ROOT / "gpt/custom_gpt_instructions.md").read_text(encoding="utf-8")
    assert len(text) <= 8000
    assert "Rules" in text and "Skin Builder" in text
    assert "getRuntimeInstructions" in text


def test_runtime_documents_are_authenticated_and_cachable(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-secret")
    client = TestClient(app)
    assert client.get("/runtime").status_code == 401
    first = client.get("/runtime", headers={"X-API-Key": "test-secret"})
    assert first.status_code == 200
    data = first.json()
    assert data["changed"] is True
    assert data["rules"].startswith("# Rules")
    assert data["skin_builder"].startswith("# Skin Builder")
    assert len(data["sha256"]) == 64
    second = client.get("/runtime", headers={"X-API-Key": "test-secret"},
                        params={"known_sha256": data["sha256"]})
    assert second.status_code == 200
    assert second.json() == {
        "sha256": data["sha256"], "changed": False, "rules": "", "skin_builder": ""
    }
