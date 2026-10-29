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
from services.reviewed_retrieval_evaluator import (
    find_relevant_chunk_rank,
)
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[3]
LEVEL2 = ROOT / "levels" / "level-2-practical-rag"
LEVEL3 = ROOT / "levels" / "level-3-advanced-rag"

DATASETS = {
    "original": LEVEL2 / "data" / "employee_handbook_evaluation.json",
    "challenging": LEVEL3 / "data" / "employee_handbook_challenging_evaluation.json",
    "reviewed": LEVEL3 / "data" / "employee_handbook_reviewed_evaluation_v1.json",
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

        if "relevant_chunks" in case:
            rank = find_relevant_chunk_rank(
                metadata,
                relevant_chunks=case["relevant_chunks"],
                expected_source=case["expected_source"],
                top_k=top_k,
            )
        else:
            rank = evaluator.find_expected_chunk_rank(
                metadata[:top_k],
                case["expected_chunk"],
                case["expected_source"],
            )

        hits.append(rank is not None)
        reciprocal_ranks.append(evaluator.calculate_reciprocal_rank(rank))

        details.append(
            {
                "case_id": case.get("case_id"),
                "question": case["question"],
                "expected_source": case["expected_source"],
                "expected_chunk": case["expected_chunk"],
                "relevant_chunks": case.get(
                    "relevant_chunks",
                    [case["expected_chunk"]],
                ),
                "retrieved_metadata": metadata[:top_k],
                "rank": rank,
                "hit": rank is not None,
                "latency_ms": elapsed_ms,
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
    reranker,
    candidate_k,
):
    expected_id = (expected_source, expected_chunk)

    candidates = hybrid_retriever.retrieve(
        question,
        top_k=candidate_k,
    )

    reranked_candidates = reranker.rerank(
        question,
        candidates,
        top_n=candidate_k,
    )

    print(f"\n--- Reranking diagnostic: {question} ---")
    print(f"Expected chunk: {expected_id}")
    print(f"Final cutoff: top {top_k}")

    for label, results in (
        ("Hybrid candidates before reranking", candidates),
        ("All candidates after reranking", reranked_candidates),
    ):
        print(f"\n{label}:")
        expected_rank = None

        for rank, result in enumerate(results, start=1):
            metadata = result["metadata"]
            result_id = (
                metadata["source"],
                metadata["chunk_index"],
            )
            is_expected = result_id == expected_id

            if is_expected:
                expected_rank = rank

            marker = " <-- EXPECTED" if is_expected else ""
            score = result.get("reranker_score")
            score_label = (
                f", reranker_score={score:.4f}"
                if score is not None
                else ""
            )

            print(
                f"  Rank {rank}: {result_id}"
                f"{score_label}{marker}"
            )
            print(f"    Text: {result['document']}")

        if expected_rank is None:
            print("Expected chunk is absent from this candidate list.")
        else:
            print(f"Expected chunk rank: {expected_rank}")
            print(
                f"Within final top {top_k}: "
                f"{expected_rank <= top_k}"
            )

    rankings = {
        "Vector-only": vector_retriever.retrieve(
            question,
            top_k=top_k,
        ),
        "BM25-only": bm25_retriever.search(
            question,
            top_k=top_k,
        ),
        "Hybrid (RRF)": hybrid_retriever.retrieve(
            question,
            top_k=top_k,
        ),
    }

    for strategy, results in rankings.items():
        print(f"\n{strategy}:")
        expected_rank = None

        for rank, result in enumerate(results, start=1):
            metadata = result["metadata"]
            result_id = (
                metadata["source"],
                metadata["chunk_index"],
            )

            if result_id == expected_id:
                expected_rank = rank

            print(
                f"  Rank {rank}: {result_id}, "
                f"score={result.get('score', 'N/A')}"
            )

        print(f"  Expected chunk rank: {expected_rank or 'MISS'}")

    print("\nHybrid: Full RRF Candidate Score Breakdown")

    all_candidates = hybrid_retriever.diagnose(
        question,
        top_k=top_k,
    )

    for rank, item in enumerate(all_candidates, start=1):
        print(
            f"  Rank {rank}: {item['chunk_id']}, "
            f"vector_rank={item['vector_rank']}, "
            f"bm25_rank={item['bm25_rank']}, "
            f"rrf_score={item['rrf_score']:.6f}"
        )

def main():
    parser = argparse.ArgumentParser(
        description="Compare vector, BM25, and hybrid retrieval."
    )
    parser.add_argument(
        "--dataset",
        choices=["original", "challenging", "reviewed"],
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
        help="Print candidate and reranking diagnostics for questions 6 and 18.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Save a JSON report to a new file.",
    )
    args = parser.parse_args()

    if args.dataset == "reviewed" and args.diagnose:
        parser.error(
            "--diagnose currently supports only original/challenging "
            "single-label datasets; omit it for reviewed evaluation"
        )

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
        dataset = json.load(file)

    if args.dataset == "reviewed":
        if not isinstance(dataset, dict):
            raise ValueError("Reviewed dataset must be an object")

        dataset_version = dataset.get("dataset_version")
        if dataset_version != "handbook-reviewed-v1":
            raise ValueError("Unsupported reviewed dataset version")

        cases = dataset.get("cases")
    else:
        dataset_version = args.dataset
        cases = dataset

    if not isinstance(cases, list) or not cases:
        raise ValueError("Dataset must contain a nonempty cases list")

    for index, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            raise ValueError(f"Case {index} must be an object")

        for field in ("question", "expected_source"):
            value = case.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"Case {index}: {field} must be a nonempty string"
                )

        expected_chunk = case.get("expected_chunk")
        if (
            isinstance(expected_chunk, bool)
            or not isinstance(expected_chunk, int)
            or expected_chunk < 0
        ):
            raise ValueError(
                f"Case {index}: expected_chunk must be a nonnegative integer"
            )

        if args.dataset == "reviewed":
            # Validate labels using the same rules as the evaluator.
            find_relevant_chunk_rank(
                [],
                relevant_chunks=case.get("relevant_chunks"),
                expected_source=case["expected_source"],
                top_k=args.top_k,
            )

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
        required_indices = {case["expected_chunk"]}

        if args.dataset == "reviewed":
            required_indices.update(case["relevant_chunks"])

        for index in required_indices:
            expected_id = (case["expected_source"], index)

            if expected_id not in available_ids:
                raise ValueError(
                    f"Expected chunk {expected_id} is missing from Chroma."
                )

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

    print(f"Dataset version: {dataset_version}")
    print(
        "Relevance labels: "
        + (
            "reviewed multiple chunks"
            if args.dataset == "reviewed"
            else "original single chunk"
        )
    )
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
    
    report = {
        "report_schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": args.dataset,
        "dataset_version": dataset_version,
        "dataset_path": str(DATASETS[args.dataset].relative_to(ROOT)),
        "question_count": len(cases),
        "corpus_chunk_count": len(corpus),
        "collection_name": COLLECTION_NAME,
        "top_k": args.top_k,
        "candidate_k": args.candidate_k,
        "warmup_queries_per_strategy": min(
            args.warmup_queries,
            len(cases),
        ),
        "latency_unit": "milliseconds",
        "strategies": {},
    }

    for name, retrieve in strategies.items():
        hit_rate, mrr, details, latency_ms, p95_latency_ms = evaluate_results(
            cases,
            retrieve,
            evaluator_module,
            args.top_k,
            warmup_queries=args.warmup_queries,
        )

        all_details[name] = details
        
        report["strategies"][name] = {
            "hit_rate_at_k": hit_rate,
            "mrr_at_k": mrr,
            "average_latency_ms": latency_ms,
            "p95_latency_ms": p95_latency_ms,
            "cases": details,
        }

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

    if args.output is not None:
        save_evaluation_report(args.output, report)
        print(f"\nSaved report: {args.output}")
        
    if args.diagnose:
        for question_number in (6, 18):
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
                reranker=reranker,
                candidate_k=args.candidate_k,
            )

def save_evaluation_report(output_path, report):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("x", encoding="utf-8") as file:
        json.dump(
            report,
            file,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        file.write("\n")
        
if __name__ == "__main__":
    main()
