import logging
import time
from uuid import uuid4

from fastapi import FastAPI, Request

logger = logging.getLogger("uvicorn.error")


def register_middleware(application: FastAPI):
    @application.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = str(uuid4())
        request.state.request_id = request_id

        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - started) * 1000

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-Ms"] = f"{duration_ms:.2f}"

        logger.info(
            "Request completed; request_id=%s method=%s path=%s "
            "status=%d duration_ms=%.2f",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )

        return response