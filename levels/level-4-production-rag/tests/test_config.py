import pytest
from app.config import load_settings

@pytest.fixture(autouse=True)
def jwt_test_settings(monkeypatch, tmp_path):
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        PublicFormat,
    )

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    public_key = private_key.public_key().public_bytes(
        encoding=Encoding.PEM,
        format=PublicFormat.SubjectPublicKeyInfo,
    )

    key_file = tmp_path / "public.pem"
    key_file.write_bytes(public_key)

    monkeypatch.setenv("JWT_PUBLIC_KEY_PATH", str(key_file))
    monkeypatch.setenv("JWT_ISSUER", "https://auth.example.test")
    monkeypatch.setenv("JWT_AUDIENCE", "production-rag-api")

def test_uses_default_embedding_model(monkeypatch):
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)

    settings = load_settings()

    assert settings.embedding_model == "all-MiniLM-L6-v2"

def test_with_invalid_embedding_model(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "example-model")

    settings = load_settings()

    assert settings.embedding_model == "example-model"

def test_rejects_blank_embedding_model(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "   ")

    with pytest.raises(
        ValueError,
        match="EMBEDDING_MODEL must not be empty",
    ):
        load_settings()

def test_rejects_missing_jwt_public_key(monkeypatch):
    monkeypatch.delenv("JWT_PUBLIC_KEY_PATH", raising=False)

    with pytest.raises(
        ValueError,
        match="JWT_PUBLIC_KEY_PATH is required",
    ):
        load_settings()