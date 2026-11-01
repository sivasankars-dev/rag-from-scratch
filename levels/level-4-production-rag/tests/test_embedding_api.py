from uuid import UUID
from fastapi.testclient import TestClient
from app.main import create_app

class FakeEmbeddingService:
    def embed_text(self, text):
        return [0.1] * 384

class FailsAfterWarmupEmbeddingService:
    def __init__(self):
        self.calls = 0

    def embed_text(self, text):
        self.calls += 1

        if self.calls == 1:
            return [0.1] * 384  # Startup warm-up succeeds.

        raise RuntimeError("Simulated inference failure")


app = create_app(
    embedding_service_factory=FakeEmbeddingService,
)

def test_rejects_whitespace_texts():
    with TestClient(app) as client:
        response = client.post(
            "/debug/embedding",
            json={"text": "    "}
        )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Text must not be empty"
    }

def test_missing_input_text():
    with TestClient(app) as client:
        response = client.post(
            "/debug/embedding",
            json={}
        )

    assert response.status_code == 422

    error = response.json()["detail"][0]

    assert error["type"] == "missing"
    assert error["loc"] == ["body", "text"]

def test_valid_input_text():
    with TestClient(app) as client:
        response = client.post(
            "/debug/embedding",
            json={"text": "Hello world"}
        )

    assert response.status_code == 200

    data = response.json()
    assert data["dimensions"] == 384
    assert len(data["preview"]) == 5
    assert data["embedding_ms"] >= 0
    assert data["preview"] == [0.1] * 5

def test_returns_503_when_embedding_generation_fails():
    app = create_app(
        embedding_service_factory=FailsAfterWarmupEmbeddingService,
    )

    with TestClient(app) as client:
        response = client.post(
            "/debug/embedding",
            json={"text": "Hello world"},
        )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Embedding service unavailable"
    }

def test_request_ids_are_valid_and_unique():
    app = create_app(
        embedding_service_factory=FakeEmbeddingService,
    )

    with TestClient(app) as client:
        first = client.get("/health")
        second = client.get("/health")

    first_id = first.headers["X-Request-ID"]
    second_id = second.headers["X-Request-ID"]

    UUID(first_id)
    UUID(second_id)

    assert first_id != second_id