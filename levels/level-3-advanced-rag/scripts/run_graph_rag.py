"""Run Graph RAG using the stored handbook knowledge graph."""

import argparse
import importlib.util
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parents[3]
LEVEL2 = ROOT / "levels" / "level-2-practical-rag"
LEVEL3 = ROOT / "levels" / "level-3-advanced-rag"

sys.path.insert(0, str(LEVEL3))

from services.graph_rag_service import GraphRAGService
from services.graph_retrieval import GraphRetriever


def load_module(module_name, file_path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)

    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module: {file_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def build_graph_rag_service(top_k=5, max_hops=1):
    """Connect to Neo4j and compose graph retrieval with grounded answering."""
    load_dotenv(dotenv_path=ROOT / ".env")

    uri = os.getenv("NEO4J_URI")
    username = os.getenv("NEO4J_USERNAME")
    password = os.getenv("NEO4J_PASSWORD")

    if not all([uri, username, password]):
        raise RuntimeError(
            "Missing NEO4J_URI, NEO4J_USERNAME, or NEO4J_PASSWORD in .env"
        )

    llm_module = load_module(
        "level2_graph_rag_llm_client",
        LEVEL2 / "services" / "llm_client.py",
    )

    driver = GraphDatabase.driver(
        uri,
        auth=(username, password),
    )

    try:
        driver.verify_connectivity()

        llm_client = llm_module.OpenAILLMClient()
        graph_retriever = GraphRetriever(driver)

        service = GraphRAGService(
            graph_retriever=graph_retriever,
            llm_client=llm_client,
            top_k=top_k,
            max_hops=max_hops,
        )
    except Exception:
        driver.close()
        raise

    return service, driver


def main():
    parser = argparse.ArgumentParser(
        description="Answer a question using the Neo4j knowledge graph."
    )
    parser.add_argument(
        "--question",
        required=True,
        help="Question to ask the knowledge graph.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Maximum number of graph evidence records.",
    )
    parser.add_argument(
        "--max-hops",
        type=int,
        choices=[1, 2, 3],
        default=1,
        help="Maximum relationship hops used during graph retrieval.",
    )

    args = parser.parse_args()

    if args.top_k <= 0:
        parser.error("--top-k must be greater than zero")

    service, driver = build_graph_rag_service(
        top_k=args.top_k,
        max_hops=args.max_hops,
    )

    try:
        result = service.run(args.question)

        print(f"Question: {result['question']}")
        print(f"Status: {result['status']}")

        print("\nRetrieved graph evidence:")
        for index, item in enumerate(result["evidence"], start=1):
            print(
                f"{index}. {item['source_entity']} "
                f"--{item['relationship']}--> "
                f"{item['target_entity']}"
            )
            print(f"   Source: {item['source']}")
            print(f"   Section: {item['section_path']}")
            print(f"   Page: {item['start_page']}")
            print(f"   Evidence: {item['evidence']}")

        print("\nAnswer:")
        print(result["answer"])
    finally:
        driver.close()


if __name__ == "__main__":
    main()
