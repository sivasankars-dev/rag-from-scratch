import os
from dataclasses import dataclass
from dotenv import load_dotenv
from pathlib import Path
from sqlalchemy.engine import make_url

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=ENV_FILE)

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

def load_database_url() -> str:
    database_url = os.getenv("DATABASE_URL", "").strip()

    if not database_url:
        raise ValueError("DATABASE_URL must not be empty")

    return database_url

def load_test_database_url() -> str:
    database_url = load_database_url()
    test_database_url = os.getenv("TEST_DATABASE_URL")

    if not test_database_url:
        raise RuntimeError("TEST_DATABASE_URL is required")

    development = make_url(database_url)
    testing = make_url(test_database_url)

    if development == testing:
        raise RuntimeError(
            "TEST_DATABASE_URL must differ from DATABASE_URL"
        )

    if not testing.database or not testing.database.endswith("_test"):
        raise RuntimeError(
            "Test database name must end with '_test'"
        )

    return test_database_url
