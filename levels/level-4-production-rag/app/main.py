import logging
import time
from uuid import uuid4
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException

from app.routers.embedding import router as embedding_router
from services.embedding_service import EmbeddingService
from app.config import load_settings
from app.middleware import register_middleware

logger = logging.getLogger("uvicorn.error")

def create_app(embedding_service_factory=None):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        started = time.perf_counter()
        settings = load_settings()
        app.state.settings = settings

        if embedding_service_factory is None:
            service = EmbeddingService(
                model=settings.embedding_model,
            )
        else:
            service = embedding_service_factory()
        logger.info(
            "Loading embedding model: %s",
            settings.embedding_model,
        )
        service.embed_text("Startup warm-up.")
        startup_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "Embedding service ready; startup_ms=%.2f",
            startup_ms,
        )
        app.state.embedding_service = service

        try:
            yield
        finally:
            logger.info("Application shutting down")

    application = FastAPI(
        title="Level 4 Production RAG",
        lifespan=lifespan,
    )

    register_middleware(application)

    application.include_router(embedding_router)

    @application.get("/health")
    async def health():
        return {"success": "healthy"}

    @application.get("/ready")
    async def ready(request: Request):
        service = getattr(request.app.state, "embedding_service", None)

        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Embedding service unavailable",
            )
        return {"status": "ready"}

    return application


app = create_app()