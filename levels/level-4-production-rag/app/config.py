import os
from dataclasses import dataclass
from dotenv import load_dotenv
from pathlib import Path
from sqlalchemy.engine import make_url
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=ENV_FILE)

@dataclass(frozen=True)
class Settings:
    embedding_model: str
    jwt_public_key: bytes
    jwt_issuer: str
    jwt_audience: str


def load_settings() -> Settings:
    model = os.getenv(
        "EMBEDDING_MODEL",
        "all-MiniLM-L6-v2",
    ).strip()

    if not model:
        raise ValueError("EMBEDDING_MODEL must not be empty")

    public_key_path = os.getenv("JWT_PUBLIC_KEY_PATH", "").strip()
    issuer = os.getenv("JWT_ISSUER", "").strip()
    audience = os.getenv("JWT_AUDIENCE", "").strip()

    if not public_key_path:
        raise ValueError("JWT_PUBLIC_KEY_PATH is required")

    if not issuer:
        raise ValueError("JWT_ISSUER is required")

    if not audience:
        raise ValueError("JWT_AUDIENCE is required")

    key_path = Path(public_key_path).expanduser()
    if not key_path.is_file():
        raise ValueError("JWT public key file does not exist")

    public_key = key_path.read_bytes()

    try:
        parsed_key = load_pem_public_key(public_key)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid JWT public key") from exc

    if not isinstance(parsed_key, RSAPublicKey):
        raise ValueError("JWT public key must be RSA")

    return Settings(
        embedding_model=model,
        jwt_public_key=public_key,
        jwt_issuer=issuer,
        jwt_audience=audience,
    )

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
