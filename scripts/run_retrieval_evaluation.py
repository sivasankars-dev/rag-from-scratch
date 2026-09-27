from app.services.embedding_service import EmbeddingService
from app.services.evaluation_dataset import EvaluationDataset
from app.services.retrieval_evaluator import RetrievalEvaluator
from app.services.vector_store import VectorStore


def main():
    dataset = EvaluationDataset(
        "data/evaluation_dataset.json"
    )

    evaluation_cases = dataset.load()

    embedding_service = EmbeddingService()

    vector_store = VectorStore()

    evaluator = RetrievalEvaluator()
    
    mrr = evaluator.mean_reciprocal_rank(
        evaluation_cases=evaluation_cases,
        embedding_service=embedding_service,
        vector_store=vector_store,
        k=3,
    )

    hit_rate = evaluator.hit_rate_at_k(
        evaluation_cases=evaluation_cases,
        embedding_service=embedding_service,
        vector_store=vector_store,
        k=3,
    )

    print("=" * 60)
    print("RAG Retrieval Evaluation")
    print("=" * 60)
    print(f"Evaluation cases: {len(evaluation_cases)}")
    print("Metric: Hit Rate@3")
    print(f"Hit Rate@3: {hit_rate:.2%}")
    print(f"MRR@3: {mrr:.2f}")

if __name__ == "__main__":
    main()