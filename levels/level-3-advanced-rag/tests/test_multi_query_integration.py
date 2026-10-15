from services.multi_query_retrieval import MultiQueryRetrievalService
from services.retrieval_adapter import RetrievalAdapter
from services.multi_query_generator import MultiQueryGenerator


class FakeQueryGenerator:
    def generate_queries(self, question):
        return ["annual leave entitlement"]

class FakeLLMClient:
    def generate(self, prompt):
        return (
            "annual leave entitlement\n"
            "paid vacation days"
        )

class FakeEmbeddingService:
    def embed_text(self, text):
        return [text]


class FakeLevel2RetrievalService:
    """Simulates the raw response returned by Level 2 / Chroma."""

    def retrieve(self, query_embedding, top_k=2, metadata_filter=None):
        query = query_embedding[0]

        if query in ("vacation days", "paid vacation days"):
            return {
                "documents": [
                    [
                        "Employees receive 18 days of annual leave.",
                        "Leave must be approved by a manager.",
                    ]
                ],
                "metadatas": [
                    [
                        {"source": "handbook.pdf", "chunk_index": 1},
                        {"source": "handbook.pdf", "chunk_index": 2},
                    ]
                ],
                "distances": [[0.1, 0.2]],
            }

        if query == "annual leave entitlement":
            return {
                "documents": [
                    [
                        "Employees receive 18 days of annual leave.",
                    ]
                ],
                "metadatas": [
                    [
                        {"source": "handbook.pdf", "chunk_index": 1},
                    ]
                ],
                "distances": [[0.15]],
            }

        return {"documents": [[]], "metadatas": [[]], "distances": [[]]}


def test_multi_query_retrieval_integrates_with_level2_response_format():
    level2_service = FakeLevel2RetrievalService()
    adapter = RetrievalAdapter(level2_service)

    service = MultiQueryRetrievalService(
        query_generator=FakeQueryGenerator(),
        embedding_service=FakeEmbeddingService(),
        retrieval_service=adapter,
    )

    results = service.retrieve("vacation days", top_k=2)

    assert len(results) == 2

    first_chunk = results[0]

    assert first_chunk["document"] == (
        "Employees receive 18 days of annual leave."
    )
    assert first_chunk["metadata"]["source"] == "handbook.pdf"
    assert first_chunk["metadata"]["chunk_index"] == 1
    assert first_chunk["retrieved_by"] == [
        "vacation days",
        "annual leave entitlement",
    ]
    assert first_chunk["retrieval_count"] == 2

def test_multi_query_generator_integrates_with_retrieval():
    level2_service = FakeLevel2RetrievalService()
    adapter = RetrievalAdapter(level2_service)

    generator = MultiQueryGenerator(
        llm_client=FakeLLMClient(),
        num_queries=2,
    )

    service = MultiQueryRetrievalService(
        query_generator=generator,
        embedding_service=FakeEmbeddingService(),
        retrieval_service=adapter,
    )

    results = service.retrieve("vacation days", top_k=2)

    assert len(results) == 2

    first_chunk = results[0]

    assert first_chunk["document"] == (
        "Employees receive 18 days of annual leave."
    )
    assert first_chunk["retrieval_count"] == 3
    assert first_chunk["retrieved_by"] == [
        "vacation days",
        "annual leave entitlement",
        "paid vacation days",
    ]
