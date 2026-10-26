"""Build a bounded context from retrieved documents."""

from dataclasses import dataclass
from functools import lru_cache
from typing import Callable

import tiktoken


@dataclass(frozen=True)
class ContextBuildResult:
    context: str
    included_documents: int
    skipped_documents: int
    estimated_words: int
    estimated_tokens: int


class LongContextBuilder:
    """Select retrieved documents within a token budget."""

    def __init__(
        self,
        max_tokens: int = 4000,
        token_counter: Callable[[str], int] | None = None,
    ):
        if max_tokens <= 0:
            raise ValueError("max_tokens must be greater than zero")

        self.max_tokens = max_tokens
        self.token_counter = token_counter or self._count_tokens

    @staticmethod
    @lru_cache(maxsize=1)
    def _get_encoding():
        return tiktoken.encoding_for_model("gpt-5-mini")

    @classmethod
    def _count_tokens(cls, text: str) -> int:
        encoding = cls._get_encoding()
        return len(encoding.encode(text))

    def build(self, documents: list[dict]) -> ContextBuildResult:
        """Build context while keeping the rendered context within budget."""
        sections = []
        seen_documents = set()
        estimated_words = 0
        estimated_tokens = 0
        included_documents = 0
        skipped_documents = 0

        for item in documents:
            document = item.get("document", "")
            metadata = item.get("metadata") or {}
            if not isinstance(metadata, dict):
                metadata = {}

            if not isinstance(document, str) or not document.strip():
                skipped_documents += 1
                continue

            normalized_document = document.strip()

            if normalized_document in seen_documents:
                skipped_documents += 1
                continue

            source = metadata.get("source", "Unknown source")
            page = metadata.get("page_number")

            citation = f"Source: {source}"
            if page is not None:
                citation += f", Page: {page}"

            section = f"[{citation}]\n{normalized_document}"
            candidate_context = "\n\n".join([*sections, section])
            candidate_tokens = self.token_counter(candidate_context)

            if candidate_tokens > self.max_tokens:
                skipped_documents += 1
                continue

            sections.append(section)
            seen_documents.add(normalized_document)
            estimated_words += len(normalized_document.split())
            estimated_tokens = candidate_tokens
            included_documents += 1

        return ContextBuildResult(
            context="\n\n".join(sections),
            included_documents=included_documents,
            skipped_documents=skipped_documents,
            estimated_words=estimated_words,
            estimated_tokens=estimated_tokens,
        )