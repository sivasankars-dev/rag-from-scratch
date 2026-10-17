
from services.parent_child_retrieval import ParentChildRetrievalService


class FakeEmbeddingService:
    def embed_text(self, text):
        return [0.1, 0.2, 0.3]


class FakeChildVectorStore:
    def search(self, query_embedding, top_k=2):
        return [
            {
                "child_id": "handbook_child_0",
                "text": "Employees receive annual leave.",
                "metadata": {
                    "parent_id": "handbook_parent_0",
                },
                "distance": 0.1,
            },
            {
                "child_id": "handbook_child_1",
                "text": "Annual leave must be requested.",
                "metadata": {
                    "parent_id": "handbook_parent_0",
                },
                "distance": 0.2,
            },
        ]


class FakeParentStore:
    def get_parent(self, parent_id):
        parents = {
            "handbook_parent_0": {
                "parent_id": "handbook_parent_0",
                "text": (
                    "Employees receive annual leave. "
                    "Leave must be requested through the HR system."
                ),
                "source": "handbook.pdf",
                "page_number": 1,
            }
        }
        return parents.get(parent_id)


def test_retrieve_returns_parent_context():
    service = ParentChildRetrievalService(
        embedding_service=FakeEmbeddingService(),
        child_vector_store=FakeChildVectorStore(),
        parent_store=FakeParentStore(),
    )

    results = service.retrieve(
        question="How does annual leave work?",
        top_k=2,
    )

    assert len(results) == 1
    assert results[0]["parent_id"] == "handbook_parent_0"
    assert "Leave must be requested through the HR system." in results[0]["text"]


def test_retrieval_deduplicates_parent_context():
    service = ParentChildRetrievalService(
        embedding_service=FakeEmbeddingService(),
        child_vector_store=FakeChildVectorStore(),
        parent_store=FakeParentStore(),
    )

    results = service.retrieve(
        question="How does annual leave work?",
        top_k=2,
    )

    # Two children belong to the same parent.
    # We should return that parent only once.
    assert len(results) == 1


def test_retrieval_returns_empty_list_when_no_children():
    class EmptyChildVectorStore:
        def search(self, query_embedding, top_k=2):
            return []

    service = ParentChildRetrievalService(
        embedding_service=FakeEmbeddingService(),
        child_vector_store=EmptyChildVectorStore(),
        parent_store=FakeParentStore(),
    )

    results = service.retrieve(
        question="Unknown topic",
        top_k=2,
    )

    assert results == []
