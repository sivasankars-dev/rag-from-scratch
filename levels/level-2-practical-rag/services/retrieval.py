from services.vector_store import VectorStore


class RetrievalService:
    def __init__(self, vector_store):
        self.vector_store = vector_store

    def retrieve(
        self,
        query_embedding,
        top_k=2,
        metadata_filter=None,
    ):
        return self.vector_store.search(
            query_embedding=query_embedding,
            top_k=top_k,
            where=metadata_filter,
        )