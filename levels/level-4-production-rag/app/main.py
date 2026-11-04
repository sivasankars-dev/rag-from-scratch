import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, Depends
from sqlalchemy import text

from app.routers.embedding import router as embedding_router
from services.embedding_service import EmbeddingService
from app.config import load_settings
from app.middleware import register_middleware
from app.database import create_database_resources
from app.dependencies import get_db_session

logger = logging.getLogger("uvicorn.error")

def create_app(
    embedding_service_factory=None,
    database_resources_factory=None,
):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        started = time.perf_counter()

        settings = load_settings()
        app.state.settings = settings

        db_factory = database_resources_factory
        if db_factory is None:
            db_factory = create_database_resources

        with db_factory() as (engine, session_factory):
            app.state.db_engine = engine
            app.state.session_factory = session_factory

            try:
                logger.info("Database startup check completed")

                logger.info(
                    "Loading embedding model: %s",
                    settings.embedding_model,
                )

                if embedding_service_factory is None:
                    service = EmbeddingService(
                        model=settings.embedding_model,
                    )
                else:
                    service = embedding_service_factory()

                service.embed_text("Startup warm-up.")
                app.state.embedding_service = service

                logger.info(
                    "Application resources ready; startup_ms=%.2f",
                    (time.perf_counter() - started) * 1000,
                )

                yield
            finally:
                app.state.embedding_service = None
                app.state.session_factory = None
                app.state.db_engine = None
                logger.info("Application resources shutting down")

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

    @application.get("/debug/database")
    def check_database(session=Depends(get_db_session)):
        result = session.execute(
            text("SELECT current_database(), current_user")
        ).one()

        return {
            "database": result[0],
            "user": result[1],
        }

    return application

app = create_app()