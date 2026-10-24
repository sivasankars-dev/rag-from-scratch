"""Run Agentic RAG using the existing Level 2 handbook corpus."""
import argparse
import importlib.util
import sys
from pathlib import Path
from services.agentic_rag import AgenticRAGService
from services.bm25_retrieval import BM25Retriever
from services.hybrid_retrieval import HybridRetriever
from services.retrieval_adapter import RetrievalAdapter


ROOT = Path(__file__).resolve().parents[3]
LEVEL2 = ROOT / "levels" / "level-2-practical-rag"
LEVEL3 = ROOT / "levels" / "level-3-advanced-rag"

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


class EmbeddedVectorRetriever:
    """Adapt the existing vector retrieval service to the hybrid interface."""

    def __init__(self, adapter, embedding_service):
        self.adapter = adapter
        self.embedding_service = embedding_service

    def retrieve(self, query, top_k=3):
        query_embedding = self.embedding_service.embed_text(query)
        return self.adapter.retrieve(
            query_embedding,
            top_k=top_k,
        )


def build_agentic_service(top_k=3, max_attempts=2):
    """Load the existing corpus and compose the hybrid retriever and agent."""
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
    llm_module = load_module(
        "level2_llm_client",
        LEVEL2 / "services" / "llm_client.py",
    )

    vector_store = vector_store_module.VectorStore(
        persist_directory=str(CHROMA_PATH),
        collection_name=COLLECTION_NAME,
    )

    stored = vector_store.collection.get(
        include=["documents", "metadatas"],
    )

    corpus = [
        {"document": document, "metadata": metadata}
        for document, metadata in zip(
            stored["documents"],
            stored["metadatas"],
        )
    ]

    if not corpus:
        raise ValueError(
            f"The Chroma collection is empty: {COLLECTION_NAME}"
        )

    embedding_service = embedding_module.EmbeddingService()
    retrieval_service = retrieval_module.RetrievalService(vector_store)
    adapter = RetrievalAdapter(retrieval_service)

    vector_retriever = EmbeddedVectorRetriever(
        adapter,
        embedding_service,
    )
    bm25_retriever = BM25Retriever(corpus)
    hybrid_retriever = HybridRetriever(
        vector_retriever,
        bm25_retriever,
    )

    llm_client = llm_module.OpenAILLMClient()

    agent = AgenticRAGService(
        retriever=hybrid_retriever,
        llm_client=llm_client,
        top_k=top_k,
        max_attempts=max_attempts,
    )

    return agent, len(corpus)


def main():
    parser = argparse.ArgumentParser(
        description="Run the bounded Agentic RAG workflow."
    )
    parser.add_argument(
        "--question",
        required=True,
        help="Question to ask the employee handbook.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=3,
        help="Number of hybrid retrieval results per attempt.",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=2,
        help="Maximum retrieval attempts, including the first attempt.",
    )

    args = parser.parse_args()

    if args.top_k <= 0:
        parser.error("--top-k must be greater than zero")

    if args.max_attempts <= 0:
        parser.error("--max-attempts must be greater than zero")

    agent, corpus_size = build_agentic_service(
        top_k=args.top_k,
        max_attempts=args.max_attempts,
    )

    result = agent.run(args.question)

    print(f"Corpus chunks: {corpus_size}")
    print(f"Question: {result['question']}")
    print(f"Status: {result['status']}")
    print(f"Retrieval attempts: {result['retrieval_attempts']}")

    print("\nQueries:")
    for index, query in enumerate(result["queries"], start=1):
        print(f"  {index}. {query}")

    print("\nRetrieved context:")
    for index, document in enumerate(result["documents"], start=1):
        if isinstance(document, dict):
            metadata = document.get("metadata") or {}
            print(
                f"  {index}. source={metadata.get('source')}, "
                f"chunk={metadata.get('chunk_index')}"
            )

    print("\nAnswer:")
    print(result["answer"])


if __name__ == "__main__":
    main()
