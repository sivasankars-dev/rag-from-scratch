from services.multi_query_retrieval import MultiQueryRetrievalService

class FakeQueryGenerator:
    def __init__(self, queries):
        self.queries = queries

    def generate_queries(self, question):
        return self.queries

class FakeEmbeddingService:
    def embed_text(self, text):
        return [text]

class FakeRetrievalService:
    def __init__(self, results_by_query):
        self.results_by_query = results_by_query
        self.searched_queries = []

    def retrieve(self, query_embedding, top_k=2, metadata_filter=None):
        query = query_embedding[0]
        self.searched_queries.append(query)
        return self.results_by_query.get(query, [])

def make_chunk(source, chunk_index, text):
    return {
        "document": text,
        "metadata": {
            "source": source,
            "chunk_index": chunk_index,
        },
        "distance": 0.1,
    }

def make_service(generated_queries, results_by_query):
    return MultiQueryRetrievalService(
        query_generator=FakeQueryGenerator(generated_queries),
        embedding_service=FakeEmbeddingService(),
        retrieval_service=FakeRetrievalService(results_by_query),
    )

def test_original_query_is_always_searched():
    service = make_service(
        generated_queries=["annual leave entitlement"],
        results_by_query={},
    )

    service.retrieve("How many leave days?", top_k=2)

    assert service.retrieval_service.searched_queries == [
        "How many leave days?",
        "annual leave entitlement",
    ]

def test_empty_and_duplicate_queries_are_removed():
    service = make_service(
        generated_queries=[
            "",
            "annual leave",
            "annual leave",
            "   ",
        ],
        results_by_query={},
    )

    service.retrieve("leave policy", top_k=2)

    assert service.retrieval_service.searched_queries == [
        "leave policy",
        "annual leave",
    ]


def test_duplicate_chunks_are_merged():
    shared_chunk = make_chunk(
        "employee_handbook.pdf",
        1,
        "Employees receive annual leave.",
    )
    second_chunk = make_chunk(
        "employee_handbook.pdf",
        2,
        "Annual leave must be approved.",
    )

    service = make_service(
        generated_queries=["leave entitlement"],
        results_by_query={
            "annual leave": [shared_chunk, second_chunk],
            "leave entitlement": [shared_chunk],
        },
    )

    results = service.retrieve("annual leave", top_k=2)

    assert len(results) == 2


def test_results_track_which_queries_retrieved_each_chunk():
    chunk = make_chunk(
        "employee_handbook.pdf",
        1,
        "Employees receive annual leave.",
    )

    service = make_service(
        generated_queries=["leave entitlement"],
        results_by_query={
            "annual leave": [chunk],
            "leave entitlement": [chunk],
        },
    )

    results = service.retrieve("annual leave", top_k=2)

    assert len(results) == 1
    assert results[0]["retrieved_by"] == [
        "annual leave",
        "leave entitlement",
    ]
    assert results[0]["retrieval_count"] == 2


def test_original_query_works_when_generator_returns_no_queries():
    service = make_service(
        generated_queries=[],
        results_by_query={
            "leave policy": [
                make_chunk("handbook.pdf", 0, "Leave policy details.")
            ],
        },
    )

    results = service.retrieve("leave policy", top_k=2)

    assert service.retrieval_service.searched_queries == ["leave policy"]
    assert len(results) == 1


def test_results_are_sorted_by_rrf_score():
    chunk_a = make_chunk(
        "handbook.pdf", 1, "Annual leave is 18 days."
    )
    chunk_b = make_chunk(
        "handbook.pdf", 2, "Leave requires approval."
    )

    service = make_service(
        generated_queries=["annual leave entitlement"],
        results_by_query={
            "vacation days": [chunk_a, chunk_b],
            "annual leave entitlement": [chunk_b, chunk_a],
        },
    )

    results = service.retrieve("vacation days", top_k=2)

    assert len(results) == 2
    assert results[0]["rrf_score"] == results[1]["rrf_score"]


def test_rrf_ranks_chunk_found_first_in_all_queries_higher():
    chunk_a = make_chunk(
        "handbook.pdf", 1, "Annual leave is 18 days."
    )
    chunk_b = make_chunk(
        "handbook.pdf", 2, "Leave requires approval."
    )

    service = make_service(
        generated_queries=[
            "annual leave entitlement",
            "employee holiday allowance",
        ],
        results_by_query={
            "vacation days": [chunk_a, chunk_b],
            "annual leave entitlement": [chunk_a, chunk_b],
            "employee holiday allowance": [chunk_a, chunk_b],
        },
    )

    results = service.retrieve("vacation days", top_k=2)

    assert results[0]["metadata"]["chunk_index"] == 1
    assert results[0]["rrf_score"] > results[1]["rrf_score"]

def test_results_are_limited_to_top_k():
    chunks = [
        make_chunk("handbook.pdf", index, f"Chunk {index}")
        for index in range(5)
    ]

    service = make_service(
        generated_queries=[],
        results_by_query={
            "question": chunks,
        },
    )

    results = service.retrieve("question", top_k=3)

    assert len(results) == 3
    assert [
        item["metadata"]["chunk_index"] for item in results
    ] == [0, 1, 2]
