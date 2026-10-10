from services.context_builder import ContextBuilder
from services.llm_client import OpenAILLMClient
from services.grounded_rag_service import GroundedRAGService
from services.embedding_service import EmbeddingService
from services.vector_store import VectorStore
from services.retrieval import RetrievalService

def get_context_builder():
    return ContextBuilder()

def get_llm_service():
    return OpenAILLMClient()

def get_grounded_rag_service():
    context_builder = get_context_builder()
    llm_service = get_llm_service()

    return GroundedRAGService(
        context_builder=context_builder,
        llm_service=llm_service,
    )

def get_embedding_service():
    return EmbeddingService()

def get_vector_store():
    return VectorStore()

def get_retrieval_service():
    vector_store = get_vector_store()
    return RetrievalService(vector_store=vector_store)