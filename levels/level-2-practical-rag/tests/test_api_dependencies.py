from app.dependencies import get_context_builder
from unittest.mock import patch
from app.dependencies import (get_llm_service, get_grounded_rag_service)


def test_get_context_builder_returns_context_builder():
    from services.context_builder import ContextBuilder

    context_builder = get_context_builder()

    assert isinstance(context_builder, ContextBuilder)


def test_get_llm_service_returns_llm_client():
    with patch("app.dependencies.OpenAILLMClient") as mock_llm_client:
        llm_service = get_llm_service()

        mock_llm_client.assert_called_once()
        assert llm_service == mock_llm_client.return_value

def test_get_grounded_rag_service_uses_dependencies():
    with (
        patch("app.dependencies.get_context_builder") as mock_context,
        patch("app.dependencies.get_llm_service") as mock_llm,
        patch("app.dependencies.GroundedRAGService") as mock_rag_service,
    ):
        result = get_grounded_rag_service()

        mock_context.assert_called_once()
        mock_llm.assert_called_once()
        mock_rag_service.assert_called_once_with(
            context_builder=mock_context.return_value,
            llm_service=mock_llm.return_value,
        )
        assert result == mock_rag_service.return_value

def test_get_embedding_service_returns_embedding_service():
    from app.dependencies import get_embedding_service
    from services.embedding_service import EmbeddingService

    embedding_service = get_embedding_service()

    assert isinstance(embedding_service, EmbeddingService)


def test_get_vector_store_returns_vector_store():
    from app.dependencies import get_vector_store
    from services.vector_store import VectorStore

    vector_store = get_vector_store()

    assert isinstance(vector_store, VectorStore)

def test_get_retrieval_service_uses_vector_store():
    from unittest.mock import patch

    from app.dependencies import get_retrieval_service
    from services.retrieval import RetrievalService

    with patch("app.dependencies.get_vector_store") as mock_get_vector_store:
        retrieval_service = get_retrieval_service()

    assert isinstance(retrieval_service, RetrievalService)
    mock_get_vector_store.assert_called_once_with()
    assert retrieval_service.vector_store is mock_get_vector_store.return_value
