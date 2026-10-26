
"""Answer questions using retrieved documents and a bounded context."""

class LongContextRAGService:
    """Coordinate embedding, retrieval, context building, and generation."""

    def __init__(
        self,
        embedding_service,
        retrieval_adapter,
        context_builder,
        llm_service,
        top_k=5,
        metadata_filter=None,
    ):
        if top_k <= 0:
            raise ValueError("top_k must be greater than zero")

        self.embedding_service = embedding_service
        self.retrieval_adapter = retrieval_adapter
        self.context_builder = context_builder
        self.llm_service = llm_service
        self.top_k = top_k
        self.metadata_filter = metadata_filter

    def answer(self, question):
        """Return an answer, citations, and context-building statistics."""
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question must not be empty")

        query_embedding = self.embedding_service.embed_text(question)

        documents = self.retrieval_adapter.retrieve(
            query_embedding=query_embedding,
            top_k=self.top_k,
            metadata_filter=self.metadata_filter,
        )

        build_result = self.context_builder.build(documents)

        if not build_result.context.strip():
            return {
                "answer": (
                    "I don't have enough information to answer that question."
                ),
                "citations": [],
                "retrieved_documents": len(documents),
                "included_documents": 0,
                "skipped_documents": build_result.skipped_documents,
                "estimated_tokens": build_result.estimated_tokens,
            }

        prompt = self._build_prompt(
            question=question,
            context=build_result.context,
        )
        answer = self.llm_service.generate(prompt)

        citations = self._build_citations(
            documents=documents,
            context=build_result.context,
        )

        return {
            "answer": answer,
            "citations": citations,
            "retrieved_documents": len(documents),
            "included_documents": build_result.included_documents,
            "skipped_documents": build_result.skipped_documents,
            "estimated_tokens": build_result.estimated_tokens,
        }

    @staticmethod
    def _build_prompt(question, context):
        return f"""Answer the question using only the provided context.

If the context does not contain enough information to answer,
clearly say "not enough information" when the context is insufficient.
Do not invent facts or use unsupported information.

CONTEXT:
{context}

QUESTION:
{question}"""

    @staticmethod
    def _build_citations(documents, context):
        """Return citations only for documents included in the context."""
        citations = []
        seen = set()

        for item in documents:
            document = item.get("document", "")
            metadata = item.get("metadata") or {}

            if not isinstance(metadata, dict):
                metadata = {}

            if not isinstance(document, str) or not document.strip():
                continue

            source = metadata.get("source", "Unknown source")
            page = metadata.get("page_number")

            citation = f"Source: {source}"
            if page is not None:
                citation += f", Page: {page}"

            section = f"[{citation}]\n{document.strip()}"

            if section not in context:
                continue

            citation_key = (source, page)
            if citation_key in seen:
                continue

            seen.add(citation_key)
            citations.append({
                "source": source,
                "page_number": page,
            })

        return citations
