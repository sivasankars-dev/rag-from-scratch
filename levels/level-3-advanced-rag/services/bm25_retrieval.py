
from rank_bm25 import BM25Okapi

import re


def tokenize(text: str) -> list[str]:
    """Convert text into lowercase word tokens."""
    return re.findall(r"\b\w+\b", text.lower())


class BM25Retriever:
    """Retrieve document chunks using BM25 keyword scoring."""

    def __init__(self, chunks: list[dict]):
        self.chunks = chunks
        self.tokenized_documents = [
            tokenize(chunk["document"]) for chunk in chunks
        ]

        # BM25Okapi expects a non-empty corpus.
        self.bm25 = (
            BM25Okapi(self.tokenized_documents)
            if self.tokenized_documents
            else None
        )

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        if not self.chunks or self.bm25 is None or top_k <= 0:
            return []

        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        scores = self.bm25.get_scores(query_tokens)
        results = []

        for chunk, score in zip(self.chunks, scores):
            # Exclude documents with no positive BM25 relevance score.
            if score <= 0:
                continue

            results.append({
                "document": chunk["document"],
                "metadata": chunk["metadata"],
                "score": float(score),
            })

        results.sort(key=lambda result: result["score"], reverse=True)
        return results[:top_k]
