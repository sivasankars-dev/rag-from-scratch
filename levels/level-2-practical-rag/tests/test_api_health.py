
from fastapi.testclient import TestClient


def test_health_endpoint_returns_ok():
    from app.main import app

    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
