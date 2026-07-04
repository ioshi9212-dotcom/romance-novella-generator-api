from functools import lru_cache
from pathlib import Path
from pydantic import BaseModel
import os


class Settings(BaseModel):
    data_dir: Path = Path(os.getenv("DATA_DIR", "./data"))
    engine_version: str = os.getenv("ENGINE_VERSION", "novella-generator-gpt-actions-v9")
    default_language: str = os.getenv("DEFAULT_LANGUAGE", "ru")
    api_key: str | None = os.getenv("API_KEY") or None


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "sessions").mkdir(parents=True, exist_ok=True)
    return settings
