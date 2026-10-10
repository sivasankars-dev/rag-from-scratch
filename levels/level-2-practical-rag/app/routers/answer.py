from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.dependencies import (
    get_embedding_service,
    get_retrieval_service,
    get_grounded_rag_service
)
from services.embedding_service import EmbeddingService
from services.retrieval import RetrievalService
from services.grounded_rag_service import GroundedRAGService

router = APIRouter()


class AnswerRequest(BaseModel):
    question: str = Field(min_length=1)


class AnswerResponse(BaseModel):
    answer: str
    citations: list[str]


@router.post("/answer", response_model=AnswerResponse)
async def answer_question(
    request: AnswerRequest,
    embedding_service: EmbeddingService = Depends(get_embedding_service),
    retrieval_service: RetrievalService = Depends(get_retrieval_service),
    grounded_rag_service: GroundedRAGService = Depends(get_grounded_rag_service),
):
    query_embedding = embedding_service.embed_text(request.question)

    results = retrieval_service.retrieve(
        query_embedding=query_embedding,
    )

    return grounded_rag_service.answer(
        question=request.question,
        results=results,
    )
