import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    embedding_model: str


def load_settings() -> Settings:
    model = os.getenv(
        "EMBEDDING_MODEL",
        "all-MiniLM-L6-v2",
    ).strip()

    if not model:
        raise ValueError("EMBEDDING_MODEL must not be empty")

    return Settings(embedding_model=model)