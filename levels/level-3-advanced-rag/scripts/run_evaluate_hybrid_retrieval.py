import argparse
import importlib.util
import json
import sys
from pathlib import Path
import time
import math

from services.cross_encoder_reranker import CrossEncoderReranker
from services.bm25_retrieval import BM25Retriever
from services.hybrid_retrieval import HybridRetriever
from services.retrieval_adapter import RetrievalAdapter

ROOT = Path(__file__).resolve().parents[3]
LEVEL2 = ROOT / "levels" / "level-2-practical-rag"
LEVEL3 = ROOT / "levels" / "level-3-advanced-rag"

DATASETS = {
    "original": LEVEL2 / "data" / "employee_handbook_evaluation.json",
    "challenging": LEVEL3 / "data" / "employee_handbook_challenging_evaluation.json",
}

CHROMA_PATH = LEVEL2 / "data" / "chroma_employee_handbook"
COLLECTION_NAME = "employee_handbook_evaluation"


class EmbeddedVectorRetriever:
    def __init__(self, adapter, embedding_service):
        self.adapter = adapter
        self.embedding_service = embedding_service

    def retrieve(self, query, top_k=3):
        embedding = self.embedding_service.embed_text(query)
        return self.adapter.retrieve(embedding, top_k=top_k)


def load_module(module_name, file_path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module: {file_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def chunk_id(chunk):
    metadata = chunk["metadata"]
    return metadata["source"], metadata["chunk_index"]


def evaluate_results(
    cases,
    retrieve,
    evaluator,
    top_k,
    warmup_queries=3,
):
    if warmup_queries < 0:
        raise ValueError("warmup_queries must be non-negative")

    if not cases:
        raise ValueError("cases must not be empty")

    # Warm-up runs are excluded from quality and latency metrics.
    warmup_count = min(warmup_queries, len(cases))

    for case in cases[:warmup_count]:
        retrieve(case["question"], top_k)

    hits = []
    reciprocal_ranks = []
    details = []
    latencies_ms = []

    for case in cases:
        start = time.perf_counter()
        results = retrieve(case["question"], top_k)
        elapsed_ms = (time.perf_counter() - start) * 1000
        latencies_ms.append(elapsed_ms)

        metadata = [result["metadata"] for result in results]

        rank = evaluator.find_expected_chunk_rank(
            metadata,
            case["expected_chunk"],
            case["expected_source"],
        )

        hits.append(rank is not None)
        reciprocal_ranks.append(evaluator.calculate_reciprocal_rank(rank))

        details.append(
            {
                "question": case["question"],
                "expected_source": case["expected_source"],
                "expected_chunk": case["expected_chunk"],
                "rank": rank,
                "hit": rank is not None,
            }
        )

    sorted_latencies = sorted(latencies_ms)
    average_latency_ms = sum(latencies_ms) / len(latencies_ms)

    # Nearest-rank percentile: rank = ceil(p * N).
    p95_index = math.ceil(0.95 * len(sorted_latencies)) - 1
    p95_latency_ms = sorted_latencies[p95_index]

    return (
        evaluator.calculate_hit_rate(hits),
        evaluator.calculate_mrr(reciprocal_ranks),
        details,
        average_latency_ms,
        p95_latency_ms,
    )


def diagnose_query(
    question,
    expected_source,
    expected_chunk,
    vector_retriever,
    bm25_retriever,
    hybrid_retriever,
    top_k,
):
    expected_id = (expected_source, expected_chunk)

    rankings = {
        "Vector-only": vector_retriever.retrieve(question, top_k=top_k),
        "BM25-only": bm25_retriever.search(question, top_k=top_k),
        "Hybrid (RRF)": hybrid_retriever.retrieve(question, top_k=top_k),
    }

    print(f"\nQuestion: {question}")
    print(f"Expected chunk: {expected_id}")

    for strategy, results in rankings.items():
        print(f"\n{strategy}:")

        expected_rank = None

        for rank, result in enumerate(results, start=1):
            metadata = result["metadata"]
            chunk_id = (metadata["source"], metadata["chunk_index"])

            if chunk_id == expected_id:
                expected_rank = rank

            print(f"  Rank {rank}: {chunk_id}, " f"score={result.get('score', 'N/A')}")

        print(f"  Expected chunk rank: {expected_rank or 'MISS'}")

    print("\nHybrid: Full RRF Candidate Score Breakdown")

    all_candidates = hybrid_retriever.diagnose(
        question,
        top_k=top_k,
    )

    for rank, item in enumerate(all_candidates, start=1):
        chunk_id = item["chunk_id"]
        vector_rank = item["vector_rank"]
        bm25_rank = item["bm25_rank"]

        print(
            f"  Rank {rank}: {chunk_id}, "
            f"vector_rank={vector_rank}, "
            f"bm25_rank={bm25_rank}, "
            f"rrf_score={item['rrf_score']:.6f}"
        )


def main():
    parser = argparse.ArgumentParser(
        description="Compare vector, BM25, and hybrid retrieval."
    )
    parser.add_argument(
        "--dataset",
        choices=["original", "challenging"],
        default="original",
    )
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument(
        "--candidate-k",
        type=int,
        default=10,
        help="Number of hybrid candidates to rerank.",
    )
    parser.add_argument(
        "--warmup-queries",
        type=int,
        default=3,
        help="Number of warm-up queries excluded from evaluation metrics.",
    )
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="Print candidate rankings for questions 9 and 18.",
    )
    args = parser.parse_args()

    if args.top_k <= 0:
        parser.error("--top-k must be greater than zero")
    if args.candidate_k < args.top_k:
        parser.error("--candidate-k must be >= --top-k")
    if args.warmup_queries < 0:
        parser.error("--warmup-queries must be non-negative")

    sys.path.insert(0, str(LEVEL3))

    vector_store_module = load_module(
        "services.vector_store",
        LEVEL2 / "services" / "vector_store.py",
    )
    embedding_module = load_module(
        "level2_embedding_service",
        LEVEL2 / "services" / "embedding_service.py",
    )
    retrieval_module = load_module(
        "level2_retrieval_service",
        LEVEL2 / "services" / "retrieval.py",
    )
    evaluator_module = load_module(
        "level2_retrieval_evaluator",
        LEVEL2 / "services" / "retrieval_evaluator.py",
    )

    with DATASETS[args.dataset].open(encoding="utf-8") as file:
        cases = json.load(file)

    vector_store = vector_store_module.VectorStore(
        persist_directory=str(CHROMA_PATH),
        collection_name=COLLECTION_NAME,
    )

    # Read the complete corpus so BM25 and vector search use the same data.
    stored = vector_store.collection.get(include=["documents", "metadatas"])

    corpus = [
        {"document": document, "metadata": metadata}
        for document, metadata in zip(stored["documents"], stored["metadatas"])
    ]

    if not corpus:
        raise ValueError("The Chroma collection is empty.")

    available_ids = {chunk_id(chunk) for chunk in corpus}
    for case in cases:
        expected_id = (
            case["expected_source"],
            case["expected_chunk"],
        )
        if expected_id not in available_ids:
            raise ValueError(f"Expected chunk {expected_id} is missing from Chroma.")

    embedding_service = embedding_module.EmbeddingService()
    raw_retrieval = retrieval_module.RetrievalService(vector_store)
    adapter = RetrievalAdapter(raw_retrieval)

    vector_retriever = EmbeddedVectorRetriever(
        adapter,
        embedding_service,
    )
    bm25 = BM25Retriever(corpus)
    hybrid = HybridRetriever(vector_retriever, bm25)
    reranker = CrossEncoderReranker.from_pretrained()

    def retrieve_hybrid_reranked(query, top_k):
        candidates = hybrid.retrieve(
            query,
            top_k=args.candidate_k,
        )

        return reranker.rerank(
            query,
            candidates,
            top_n=top_k,
        )

    def retrieve_vector(query, top_k):
        return vector_retriever.retrieve(query, top_k=top_k)

    def retrieve_bm25(query, top_k):
        return bm25.search(query, top_k=top_k)

    strategies = {
        "Vector-only": retrieve_vector,
        "BM25-only": retrieve_bm25,
        "Hybrid (RRF)": hybrid.retrieve,
        "Hybrid + Cross-Encoder": retrieve_hybrid_reranked,
    }

    print(f"Dataset: {args.dataset}")
    print(f"Questions: {len(cases)}")
    print(f"Corpus chunks: {len(corpus)}")
    print(f"Top-K: {args.top_k}")

    print("\n--- Evaluation Summary ---")
    print(
        f"{'Strategy':<26} "
        f"{'Hit Rate@K':>12} "
        f"{'MRR@K':>10} "
        f"{'Avg Latency':>14} "
        f"{'P95 Latency':>14}"
    )

    all_details = {}

    for name, retrieve in strategies.items():
        hit_rate, mrr, details, latency_ms, p95_latency_ms = evaluate_results(
            cases,
            retrieve,
            evaluator_module,
            args.top_k,
            warmup_queries=args.warmup_queries,
        )

        all_details[name] = details

        print(
            f"{name:<26} "
            f"{hit_rate:>11.2%} "
            f"{mrr:>10.4f} "
            f"{latency_ms:>11.2f} ms "
            f"{p95_latency_ms:>11.2f} ms"
        )
    print(f"Warm-up queries per strategy: {min(args.warmup_queries, len(cases))}")

    print("\n--- Per-question Diagnostics ---")

    for index, case in enumerate(cases):
        print(f"\nQ{index + 1}: {case['question']}")

        for name, details in all_details.items():
            detail = details[index]
            rank = detail["rank"]
            rank_label = f"rank {rank}" if rank is not None else "MISS"
            print(f"  {name:<18} {rank_label}")

    if args.diagnose:
        for question_number in (9, 18):
            if question_number > len(cases):
                continue

            case = cases[question_number - 1]

            diagnose_query(
                question=case["question"],
                expected_source=case["expected_source"],
                expected_chunk=case["expected_chunk"],
                vector_retriever=vector_retriever,
                bm25_retriever=bm25,
                hybrid_retriever=hybrid,
                top_k=args.top_k,
            )


if __name__ == "__main__":
    main()
