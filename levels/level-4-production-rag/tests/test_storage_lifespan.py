from contextlib import contextmanager
from unittest.mock import Mock

from fastapi.testclient import TestClient

from app.main import create_app


@contextmanager
def fake_database_resources():
    engine = Mock()
    session_factory = Mock()
    yield engine, session_factory


def test_storage_initialized_during_lifespan():
    fake_storage = Mock()

    app = create_app(
        embedding_service_factory=lambda: Mock(),
        database_resources_factory=fake_database_resources,
        document_storage_factory=lambda: fake_storage,
    )

    with TestClient(app) as client:
        assert client.app.state.document_storage is fake_storage

    assert app.state.document_storage is None