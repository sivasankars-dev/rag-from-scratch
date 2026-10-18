
from services.hybrid_retrieval import HybridRetriever


class FakeVectorRetriever:
    def __init__(self, results):
        self.results = results

    def retrieve(self, query, top_k=3):
        return self.results[:top_k]


class FakeBM25Retriever:
    def __init__(self, results):
        self.results = results

    def search(self, query, top_k=3):
        return self.results[:top_k]


def chunk(index, document):
    return {
        "document": document,
        "metadata": {
            "source": "handbook.pdf",
            "chunk_index": index,
        },
    }


def test_hybrid_retrieval_combines_vector_and_bm25_results():
    vector_results = [
        chunk(1, "Annual leave policy"),
        chunk(2, "Production credentials"),
    ]
    bm25_results = [
        chunk(2, "Production credentials"),
        chunk(3, "Travel approval"),
    ]

    retriever = HybridRetriever(
        vector_retriever=FakeVectorRetriever(vector_results),
        bm25_retriever=FakeBM25Retriever(bm25_results),
    )

    results = retriever.retrieve("production credentials", top_k=3)

    result_ids = [
        (item["metadata"]["source"], item["metadata"]["chunk_index"])
        for item in results
    ]

    assert len(result_ids) == 3
    assert len(set(result_ids)) == 3
    assert ("handbook.pdf", 2) in result_ids


def test_hybrid_retrieval_returns_ranked_results():
    vector_results = [
        chunk(1, "Annual leave policy"),
        chunk(2, "Production credentials"),
    ]
    bm25_results = [
        chunk(2, "Production credentials"),
        chunk(1, "Annual leave policy"),
    ]

    retriever = HybridRetriever(
        vector_retriever=FakeVectorRetriever(vector_results),
        bm25_retriever=FakeBM25Retriever(bm25_results),
    )

    results = retriever.retrieve("annual leave", top_k=2)

    assert results[0]["metadata"]["chunk_index"] in {1, 2}


def test_hybrid_retrieval_handles_empty_results():
    retriever = HybridRetriever(
        vector_retriever=FakeVectorRetriever([]),
        bm25_retriever=FakeBM25Retriever([]),
    )

    assert retriever.retrieve("unknown query", top_k=3) == []


def test_hybrid_retrieval_respects_top_k():
    retriever = HybridRetriever(
        vector_retriever=FakeVectorRetriever([
            chunk(1, "Annual leave"),
            chunk(2, "Credentials"),
        ]),
        bm25_retriever=FakeBM25Retriever([
            chunk(2, "Credentials"),
            chunk(3, "Travel"),
        ]),
    )

    results = retriever.retrieve("leave", top_k=1)

    assert len(results) == 1
