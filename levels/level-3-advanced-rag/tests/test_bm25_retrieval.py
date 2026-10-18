import pytest
from services.bm25_retrieval import BM25Retriever


@pytest.fixture
def chunks():
    return [
        {
            "document": "Employees receive 20 annual leave days.",
            "metadata": {
                "source": "handbook.pdf",
                "chunk_index": 1,
            },
        },
        {
            "document": "Production credentials must not be committed to Git.",
            "metadata": {
                "source": "handbook.pdf",
                "chunk_index": 2,
            },
        },
        {
            "document": "Business travel requires approval before booking.",
            "metadata": {
                "source": "handbook.pdf",
                "chunk_index": 3,
            },
        },
    ]


def test_exact_keyword_query_ranks_relevant_chunk_first(chunks):
    retriever = BM25Retriever(chunks)

    results = retriever.search(
        "production credentials committed Git",
        top_k=2,
    )

    assert results
    assert results[0]["metadata"]["chunk_index"] == 2


def test_results_include_document_and_metadata(chunks):
    retriever = BM25Retriever(chunks)

    results = retriever.search("annual leave", top_k=2)

    assert results
    assert "document" in results[0]
    assert "metadata" in results[0]
    assert "score" in results[0]


def test_unrelated_query_returns_no_results(chunks):
    retriever = BM25Retriever(chunks)

    assert retriever.search("quantum spacecraft", top_k=3) == []


def test_empty_corpus_returns_no_results():
    retriever = BM25Retriever([])

    assert retriever.search("annual leave", top_k=3) == []


def test_top_k_limits_results(chunks):
    retriever = BM25Retriever(chunks)

    results = retriever.search(
        "employees production business",
        top_k=1,
    )

    assert len(results) <= 1