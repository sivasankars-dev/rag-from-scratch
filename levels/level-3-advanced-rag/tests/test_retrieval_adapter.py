import pytest

from services.retrieval_adapter import RetrievalAdapter


class FakeRetrievalService:
    def __init__(self, response):
        self.response = response
        self.received_arguments = None

    def retrieve(self, query_embedding, top_k=2, metadata_filter=None):
        self.received_arguments = {
            "query_embedding": query_embedding,
            "top_k": top_k,
            "metadata_filter": metadata_filter,
        }
        return self.response


def test_converts_chroma_response_into_individual_chunks():
    chroma_response = {
        "documents": [
            ["Annual leave is 18 days.", "Manager approval is required."]
        ],
        "metadatas": [
            [
                {"source": "handbook.pdf", "chunk_index": 1},
                {"source": "handbook.pdf", "chunk_index": 2},
            ]
        ],
        "distances": [[0.1, 0.3]],
    }

    adapter = RetrievalAdapter(FakeRetrievalService(chroma_response))

    results = adapter.retrieve(
        query_embedding=[0.1, 0.2],
        top_k=2,
    )

    assert results == [
        {
            "document": "Annual leave is 18 days.",
            "metadata": {"source": "handbook.pdf", "chunk_index": 1},
            "distance": 0.1,
        },
        {
            "document": "Manager approval is required.",
            "metadata": {"source": "handbook.pdf", "chunk_index": 2},
            "distance": 0.3,
        },
    ]


def test_passes_arguments_to_level_2_retrieval_service():
    fake_retrieval = FakeRetrievalService(
        {"documents": [[]], "metadatas": [[]], "distances": [[]]}
    )
    adapter = RetrievalAdapter(fake_retrieval)

    adapter.retrieve(
        query_embedding=[0.5, 0.8],
        top_k=5,
        metadata_filter={"source": "handbook.pdf"},
    )

    assert fake_retrieval.received_arguments == {
        "query_embedding": [0.5, 0.8],
        "top_k": 5,
        "metadata_filter": {"source": "handbook.pdf"},
    }


def test_returns_empty_list_when_no_documents_are_found():
    chroma_response = {
        "documents": [[]],
        "metadatas": [[]],
        "distances": [[]],
    }
    adapter = RetrievalAdapter(FakeRetrievalService(chroma_response))

    assert adapter.retrieve([0.1, 0.2]) == []


def test_raises_error_when_chroma_result_fields_are_misaligned():
    chroma_response = {
        "documents": [["Annual leave is 18 days."]],
        "metadatas": [[]],
        "distances": [[0.1]],
    }
    adapter = RetrievalAdapter(FakeRetrievalService(chroma_response))

    with pytest.raises(ValueError, match="result counts do not match"):
        adapter.retrieve([0.1, 0.2])
