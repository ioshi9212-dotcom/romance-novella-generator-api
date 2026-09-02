import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field


class Settings(BaseModel):
    data_dir: Path = Field(default=Path("./data"))
    public_base_url: str = Field(default="https://web-production-4310e.up.railway.app")
    packet_chunk_chars: int = Field(default=20_000, ge=4_000, le=50_000)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        data_dir=Path(os.getenv("DATA_DIR", "./data")),
        public_base_url=os.getenv(
            "PUBLIC_BASE_URL",
            "https://web-production-4310e.up.railway.app",
        ).rstrip("/"),
        packet_chunk_chars=int(os.getenv("PACKET_CHUNK_CHARS", "20000")),
    )
