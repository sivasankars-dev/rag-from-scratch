from fastapi import APIRouter, Depends, HTTPException, Request
from app.dependencies import get_embedding_service
from app.schemas.embedding import EmbeddingRequest, EmbeddingResponse
import time
import logging

logger = logging.getLogger("uvicorn.error")

router = APIRouter(
    prefix="/debug",
    tags=["Debug"],
)

@router.get("/embedding")
async def embedding(service=Depends(get_embedding_service)):
    return {"service": type(service).__name__}

@router.post("/embedding", response_model=EmbeddingResponse)
def generate_embedding(
    payload: EmbeddingRequest,
    request: Request,
    service=Depends(get_embedding_service)):
    text = payload.text.strip()

    if not text:
        raise HTTPException(
            status_code=422,
            detail="Text must not be empty",
        )
    started = time.perf_counter()

    try:
        vector = service.embed_text(text)
    except Exception:
        logger.exception(
            "Embedding generation failed; request_id=%s",
            request.state.request_id,
        )
        raise HTTPException(
            status_code=503,
            detail="Embedding service unavailable",
        ) from None

    embedding_ms = (time.perf_counter() - started) * 1000

    logger.info(
        "Embedding generated; request_id=%s dimensions=%d embedding_ms=%.2f",
        request.state.request_id,
        len(vector),
        embedding_ms,
    )

    return EmbeddingResponse(
        dimensions=len(vector),
        preview=vector[:5],
        embedding_ms=round(embedding_ms, 2),
    )