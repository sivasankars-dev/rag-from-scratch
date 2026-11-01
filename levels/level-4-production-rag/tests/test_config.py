import pytest
from pydantic import ValidationError
from app.config import load_settings


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