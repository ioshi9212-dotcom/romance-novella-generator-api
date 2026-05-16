from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings.

    The OpenAI key is intentionally optional. The MVP can work in manual GPT mode:
    the backend stores memory and builds prompts that the user can paste into ChatGPT.
    """

    app_name: str = "Romance Novella Generator API"
    data_dir: Path = Path("data/runtime")
    templates_dir: Path = Path("data/templates")
    prompts_dir: Path = Path("prompts")
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.1-mini"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
