from pathlib import Path

import yaml

from app.novella_openapi_actions import DEFAULT_PUBLIC_URL, build_openapi_actions


def test_tracked_openapi_yaml_matches_canonical_action_generator():
    tracked = yaml.safe_load(Path("openapi.yaml").read_text(encoding="utf-8"))

    assert tracked == build_openapi_actions(DEFAULT_PUBLIC_URL)
