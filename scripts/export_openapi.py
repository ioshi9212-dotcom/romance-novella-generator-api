"""Export the canonical Custom GPT Actions contract to the tracked YAML file."""

from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.novella_openapi_actions import DEFAULT_PUBLIC_URL, build_openapi_actions  # noqa: E402


def main() -> None:
    contract = build_openapi_actions(DEFAULT_PUBLIC_URL)
    payload = yaml.safe_dump(contract, allow_unicode=True, sort_keys=False, width=100)
    (ROOT / "openapi.yaml").write_text(payload, encoding="utf-8")


if __name__ == "__main__":
    main()
