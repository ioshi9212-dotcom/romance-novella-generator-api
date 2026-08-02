from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from app.main import app
from app.novella_openapi_actions import DEFAULT_PUBLIC_URL, build_openapi_actions


def test_tracked_openapi_yaml_matches_canonical_action_generator():
    tracked = yaml.safe_load(Path("openapi.yaml").read_text(encoding="utf-8"))

    assert tracked == build_openapi_actions(DEFAULT_PUBLIC_URL)


def test_stable_yaml_import_url_serves_the_canonical_contract():
    response = TestClient(app).get("/openapi-actions.yaml")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/yaml")
    assert yaml.safe_load(response.text) == build_openapi_actions(DEFAULT_PUBLIC_URL)
