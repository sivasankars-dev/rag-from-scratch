
import json
from pathlib import Path

from services.embedding_service import EmbeddingService
from services.retrieval import RetrievalService
from services.retrieval_evaluator import (
    calculate_hit_rate,
    calculate_mrr,
    calculate_reciprocal_rank,
    find_expected_chunk_rank,
)
from services.vector_store import VectorStore


BASE_DIR = Path(__file__).resolve().parents[1]
DATASET_PATH = BASE_DIR / "data" / "employee_handbook_evaluation.json"
CHROMA_PATH = BASE_DIR / "data" / "chroma_employee_handbook"


def main():
    with DATASET_PATH.open("r", encoding="utf-8") as file:
        evaluation_cases = json.load(file)

    vector_store = VectorStore(
        persist_directory=str(CHROMA_PATH),
        collection_name="employee_handbook_evaluation",
    )
    stored = vector_store.collection.get(include=["metadatas"])
    stored_labels = {
        (metadata["source"], metadata["chunk_index"])
        for metadata in stored["metadatas"]
    }
    for case in evaluation_cases:
        label = (case["expected_source"], case["expected_chunk"])
        if label not in stored_labels:
            raise ValueError(
                f"Expected label {label} is missing from the collection. "
                "Run scripts/run_handbook_ingestion.py before evaluation."
            )

    embedding_service = EmbeddingService()
    retrieval_service = RetrievalService(vector_store)

    top_k = 3
    hit_results = []
    reciprocal_ranks = []

    for case in evaluation_cases:
        query_embedding = embedding_service.embed_text(case["question"])

        results = retrieval_service.retrieve(
            query_embedding=query_embedding,
            top_k=top_k,
        )

        retrieved_metadata = results["metadatas"][0]

        # Indices are displayed for readability; scoring matches source too.
        retrieved_chunks = [
            metadata["chunk_index"]
            for metadata in retrieved_metadata
        ]

        rank = find_expected_chunk_rank(
            retrieved_metadata,
            case["expected_chunk"],
            case["expected_source"],
        )

        hit = rank is not None
        reciprocal_rank = calculate_reciprocal_rank(rank)

        hit_results.append(hit)
        reciprocal_ranks.append(reciprocal_rank)

        print(f"\nQuestion: {case['question']}")
        print(f"Expected source: {case['expected_source']}")
        print(f"Expected chunk: {case['expected_chunk']}")
        print(f"Retrieved chunks: {retrieved_chunks}")
        print(f"Expected chunk rank: {rank}")
        print(f"Hit: {hit}")
        print(f"Reciprocal rank: {reciprocal_rank:.4f}")

    hit_rate = calculate_hit_rate(hit_results)
    mrr = calculate_mrr(reciprocal_ranks)

    print("\n--- Evaluation Summary ---")
    print(f"Questions evaluated: {len(evaluation_cases)}")
    print(f"Top-K: {top_k}")
    print(f"Hits: {sum(hit_results)}")
    print(f"Hit Rate@{top_k}: {hit_rate:.2%}")
    print(f"MRR@{top_k}: {mrr:.4f}")


if __name__ == "__main__":
    main()
