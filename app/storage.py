import json
from pathlib import Path
from typing import Any


class JsonStorage:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def read_json(self, path: Path, default: Any | None = None) -> Any:
        if not path.exists():
            if default is not None:
                return default
            raise FileNotFoundError(str(path))
        return json.loads(path.read_text(encoding="utf-8"))

    def write_json(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list_dirs(self, path: Path) -> list[Path]:
        if not path.exists():
            return []
        return sorted([item for item in path.iterdir() if item.is_dir()])

    def list_files(self, path: Path, pattern: str = "*.json") -> list[Path]:
        if not path.exists():
            return []
        return sorted(path.glob(pattern))
