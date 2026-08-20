from functools import lru_cache
from pathlib import Path
from pydantic import BaseModel
import os


class Settings(BaseModel):
    data_dir: Path
    engine_version: str
    default_language: str
    api_key: str | None


@lru_cache
def get_settings() -> Settings:
    # Read the environment when the cached settings object is created, not when
    # this module is imported.  Railway still receives one cached object per
    # process, while tests and maintenance tools can safely switch DATA_DIR and
    # call cache_clear() without writing into another session store.
    settings = Settings(
        data_dir=Path(os.getenv("DATA_DIR", "./data")),
        engine_version=os.getenv(
            "ENGINE_VERSION",
            "novella-generator-gpt-actions-v9.4-session-chunks",
        ),
        default_language=os.getenv("DEFAULT_LANGUAGE", "ru"),
        api_key=os.getenv("API_KEY") or None,
    )
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "sessions").mkdir(parents=True, exist_ok=True)
    return settings
