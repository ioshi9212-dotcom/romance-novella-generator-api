import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.main import app


def main() -> None:
    schema = app.openapi()
    target = ROOT / "openapi.yaml"
    target.write_text(
        yaml.safe_dump(
            schema,
            allow_unicode=True,
            sort_keys=False,
            width=110,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
