import pytest
from fastapi.testclient import TestClient

from app.main import create_app

class FailingEmbeddingService:
    def embed_text(self, text):
        raise RuntimeError("Model warm-up failed")


class FakeEmbeddingService:
    def embed_text(self, text):
        return [0.1] * 384


def test_health_returns_ok():
    app = create_app(
        embedding_service_factory=FakeEmbeddingService,
    )

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"success": "healthy"}


def test_ready_when_embedding_service_exists():
    app = create_app(
        embedding_service_factory=FakeEmbeddingService,
    )

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_not_ready_when_embedding_service_is_missing():
    app = create_app(
        embedding_service_factory=FakeEmbeddingService,
    )

    with TestClient(app) as client:
        # Startup created the service; remove it to simulate missing state.
        del app.state.embedding_service

        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Embedding service unavailable"
    }


def test_startup_fails_when_model_warmup_fails():
    app = create_app(
        embedding_service_factory=FailingEmbeddingService,
    )

    with pytest.raises(RuntimeError, match="Model warm-up failed"):
        with TestClient(app):
            pass