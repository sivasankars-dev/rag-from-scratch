
import logging
import re
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware import register_middleware


def test_middleware_logs_unhandled_exception(caplog):
    # Arrange: Create an isolated FastAPI application
    app = FastAPI()
    register_middleware(app)

    @app.get("/debug/crash")
    def crash_endpoint():
        raise RuntimeError("simulated failure")

    client = TestClient(app, raise_server_exceptions=False)

    # Act: Trigger an unhandled exception
    caplog.set_level(logging.ERROR, logger="uvicorn.error")
    response = client.get("/debug/crash")

    # 1. Verify HTTP response
    assert response.status_code == 500

    # 2. Verify failure log fields
    assert "Request failed" in caplog.text
    assert "simulated failure" in caplog.text
    assert "method=GET" in caplog.text
    assert "path=/debug/crash" in caplog.text
    assert "status=500" in caplog.text

    # 3. Verify request ID is a valid UUID
    request_id_match = re.search(
        r"request_id=([0-9a-f-]{36})",
        caplog.text,
    )

    assert request_id_match is not None

    request_id = UUID(request_id_match.group(1))
    assert request_id.version == 4

    # 4. Verify duration is numeric and non-negative
    duration_match = re.search(
        r"duration_ms=(\d+(?:\.\d+)?)",
        caplog.text,
    )

    assert duration_match is not None

    duration_ms = float(duration_match.group(1))
    assert duration_ms >= 0

    # 5. Verify original exception type and message
    error_records = [
        record
        for record in caplog.records
        if record.name == "uvicorn.error"
        and record.levelno == logging.ERROR
        and record.exc_info is not None
    ]

    assert len(error_records) == 1

    exception_type, exception_value, _ = error_records[0].exc_info

    assert exception_type is RuntimeError
    assert str(exception_value) == "simulated failure"
