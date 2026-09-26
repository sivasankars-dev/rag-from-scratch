from app.services.embedding_service import EmbeddingService
from app.services.retrieval_controls_vector_store import VectorStore


def get_embedding_service():
    return EmbeddingService()

def get_vector_store():
    return VectorStore()