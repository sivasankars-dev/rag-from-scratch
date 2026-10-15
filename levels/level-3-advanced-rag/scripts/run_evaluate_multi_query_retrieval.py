
import importlib.util
import argparse
import json
import sys
from pathlib import Path
from services.multi_query_generator import MultiQueryGenerator
from services.multi_query_retrieval import MultiQueryRetrievalService
from services.retrieval_adapter import RetrievalAdapter


ROOT = Path(__file__).resolve().parents[3]
LEVEL2 = ROOT / "levels" / "level-2-practical-rag"
LEVEL3 = ROOT / "levels" / "level-3-advanced-rag"

ORIGINAL_DATASET_PATH = (
    LEVEL2 / "data" / "employee_handbook_evaluation.json"
)
CHALLENGING_DATASET_PATH = (
    LEVEL3 / "data" / "employee_handbook_challenging_evaluation.json"
)
CHROMA_PATH = LEVEL2 / "data" / "chroma_employee_handbook"
COLLECTION_NAME = "employee_handbook_evaluation"


def load_module(module_name, file_path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module: {file_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(
        description="Compare baseline and multi-query retrieval."
    )
    parser.add_argument(
        "--dataset",
        choices=["original", "challenging"],
        default="original",
        help="Evaluation dataset to use.",
    )
    args = parser.parse_args()

    dataset_paths = {
        "original": ORIGINAL_DATASET_PATH,
        "challenging": CHALLENGING_DATASET_PATH,
    }

    dataset_path = dataset_paths[args.dataset]

    # Load Level 3 modules using the Level 3 services package.
    sys.path.insert(0, str(LEVEL3))

    # Load Level 2 vector store first, so retrieval.py resolves it correctly.
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
    llm_module = load_module(
        "level2_llm_client",
        LEVEL2 / "services" / "llm_client.py",
    )
    evaluator_module = load_module(
        "level2_retrieval_evaluator",
        LEVEL2 / "services" / "retrieval_evaluator.py",
    )

    with dataset_path.open("r", encoding="utf-8") as file:
        cases = json.load(file)

    vector_store = vector_store_module.VectorStore(
        persist_directory=str(CHROMA_PATH),
        collection_name=COLLECTION_NAME,
    )

    stored = vector_store.collection.get(include=["metadatas"])
    stored_labels = {
        (metadata["source"], metadata["chunk_index"])
        for metadata in stored["metadatas"]
    }

    for case in cases:
        expected = (case["expected_source"], case["expected_chunk"])
        if expected not in stored_labels:
            raise ValueError(
                f"Expected chunk {expected} is missing from Chroma."
            )

    embedding_service = embedding_module.EmbeddingService()
    raw_retrieval = retrieval_module.RetrievalService(vector_store)
    adapter = RetrievalAdapter(raw_retrieval)

    # Keep the baseline and multi-query retrieval on the same database.
    generator = MultiQueryGenerator(
        llm_client=llm_module.OpenAILLMClient(),
        num_queries=3,
    )
    multi_query_service = MultiQueryRetrievalService(
        query_generator=generator,
        embedding_service=embedding_service,
        retrieval_service=adapter,
    )

    top_k = 3
    baseline_hits = []
    baseline_rrs = []
    multi_hits = []
    multi_rrs = []

    for case in cases:
        question = case["question"]
        expected_source = case["expected_source"]
        expected_chunk = case["expected_chunk"]

        # Baseline: retrieve with the original query only.
        query_embedding = embedding_service.embed_text(question)
        raw_results = raw_retrieval.retrieve(
            query_embedding=query_embedding,
            top_k=top_k,
        )
        baseline_metadata = raw_results["metadatas"][0]

        baseline_rank = evaluator_module.find_expected_chunk_rank(
            baseline_metadata,
            expected_chunk,
            expected_source,
        )
        baseline_hits.append(baseline_rank is not None)
        baseline_rrs.append(
            evaluator_module.calculate_reciprocal_rank(baseline_rank)
        )

        # Multi-query: original question + generated alternatives + RRF.
        multi_results = multi_query_service.retrieve(
            question,
            top_k=top_k,
        )
        multi_metadata = [item["metadata"] for item in multi_results]

        multi_rank = evaluator_module.find_expected_chunk_rank(
            multi_metadata,
            expected_chunk,
            expected_source,
        )
        multi_hits.append(multi_rank is not None)
        multi_rrs.append(
            evaluator_module.calculate_reciprocal_rank(multi_rank)
        )

        print(f"\nQuestion: {question}")
        print(f"Expected chunk: {expected_chunk}")
        print(f"Baseline rank: {baseline_rank}")
        print(f"Multi-query rank: {multi_rank}")
        print(f"Multi-query unique chunks: {len(multi_results)}")

    calculate_hit_rate = evaluator_module.calculate_hit_rate
    calculate_mrr = evaluator_module.calculate_mrr

    print("\n--- Evaluation Summary ---")
    print(f"Questions evaluated: {len(cases)}")
    print(f"Top-K: {top_k}")
    print(
        f"Baseline Hit Rate@{top_k}: "
        f"{calculate_hit_rate(baseline_hits):.2%}"
    )
    print(
        f"Multi-query Hit Rate@{top_k}: "
        f"{calculate_hit_rate(multi_hits):.2%}"
    )
    print(
        f"Baseline MRR@{top_k}: {calculate_mrr(baseline_rrs):.4f}"
    )
    print(
        f"Multi-query MRR@{top_k}: {calculate_mrr(multi_rrs):.4f}"
    )


if __name__ == "__main__":
    main()
