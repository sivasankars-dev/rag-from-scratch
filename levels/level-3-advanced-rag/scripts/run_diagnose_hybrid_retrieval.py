def main():
    # Reuse the evaluation script's setup by running its main setup
    # separately below after extracting the retrieval construction.
    print(
        "Diagnostic setup needs to reuse the vector store, "
        "embedding service, BM25 retriever, and HybridRetriever "
        "from run_evaluate_hybrid_retrieval.py."
    )


if __name__ == "__main__":
    main()
