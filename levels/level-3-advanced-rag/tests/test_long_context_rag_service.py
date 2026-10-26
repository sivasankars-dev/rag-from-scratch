

import pytest

from services.long_context_builder import LongContextBuilder
from services.long_context_rag_service import LongContextRAGService


def fake_token_counter(text: str) -> int:
    return len(text.split())


class FakeEmbeddingService:
    def __init__(self):
        self.questions = []

    def embed_text(self, text):
        self.questions.append(text)
        return [0.1, 0.2, 0.3]


class FakeRetrievalAdapter:
    def __init__(self, documents):
        self.documents = documents
        self.calls = []

    def retrieve(self, **kwargs):
        self.calls.append(kwargs)
        return self.documents


class FakeLLMService:
    def __init__(self):
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        return "Remote work requires manager approval."


def make_service(documents, max_tokens=100):
    embedding_service = FakeEmbeddingService()
    retrieval_adapter = FakeRetrievalAdapter(documents)
    llm_service = FakeLLMService()

    service = LongContextRAGService(
        embedding_service=embedding_service,
        retrieval_adapter=retrieval_adapter,
        context_builder=LongContextBuilder(
            max_tokens=max_tokens,
            token_counter=fake_token_counter,
        ),
        llm_service=llm_service,
        top_k=5,
        metadata_filter={"department": "engineering"},
    )

    return service, embedding_service, retrieval_adapter, llm_service


def test_answer_returns_generated_answer_and_citations():
    documents = [
        {
            "document": "Remote work requires manager approval.",
            "metadata": {
                "source": "handbook.pdf",
                "page_number": 4,
            },
            "distance": 0.1,
        },
        {
            "document": "Employees can request flexible hours.",
            "metadata": {
                "source": "handbook.pdf",
                "page_number": 5,
            },
            "distance": 0.2,
        },
    ]

    service, embedding, retrieval, llm = make_service(documents)

    result = service.answer("What is the remote work policy?")

    assert result["answer"] == (
        "Remote work requires manager approval."
    )
    assert result["retrieved_documents"] == 2
    assert result["included_documents"] == 2
    assert result["skipped_documents"] == 0
    assert result["estimated_tokens"] > 0
    assert result["citations"] == [
        {"source": "handbook.pdf", "page_number": 4},
        {"source": "handbook.pdf", "page_number": 5},
    ]

    assert embedding.questions == ["What is the remote work policy?"]
    assert retrieval.calls[0]["query_embedding"] == [0.1, 0.2, 0.3]
    assert retrieval.calls[0]["top_k"] == 5
    assert retrieval.calls[0]["metadata_filter"] == {
        "department": "engineering"
    }
    assert len(llm.prompts) == 1
    assert "CONTEXT:" in llm.prompts[0]
    assert "QUESTION:" in llm.prompts[0]


def test_answer_only_cites_documents_included_in_context():
    documents = [
        {
            "document": "This document has six words total",
            "metadata": {"source": "large.pdf"},
        },
        {
            "document": "Small document fits",
            "metadata": {"source": "small.pdf"},
        },
    ]

    service, _, _, _ = make_service(documents, max_tokens=7)

    result = service.answer("Summarize the documents.")

    assert result["included_documents"] == 1
    assert result["skipped_documents"] == 1
    assert result["citations"] == [
        {"source": "small.pdf", "page_number": None}
    ]


def test_answer_does_not_call_llm_when_no_documents_are_available():
    service, _, _, llm = make_service([])

    result = service.answer("What is the policy?")

    assert result["answer"] == (
        "I don't have enough information to answer that question."
    )
    assert result["citations"] == []
    assert result["retrieved_documents"] == 0
    assert result["included_documents"] == 0
    assert result["skipped_documents"] == 0
    assert result["estimated_tokens"] == 0
    assert llm.prompts == []


@pytest.mark.parametrize("question", ["", "   ", None, 123])
def test_answer_rejects_empty_or_invalid_question(question):
    service, embedding, retrieval, llm = make_service([])

    with pytest.raises(ValueError, match="question"):
        service.answer(question)

    assert embedding.questions == []
    assert retrieval.calls == []
    assert llm.prompts == []


@pytest.mark.parametrize("top_k", [0, -1])
def test_service_rejects_invalid_top_k(top_k):
    with pytest.raises(ValueError, match="top_k"):
        LongContextRAGService(
            embedding_service=FakeEmbeddingService(),
            retrieval_adapter=FakeRetrievalAdapter([]),
            context_builder=LongContextBuilder(),
            llm_service=FakeLLMService(),
            top_k=top_k,
        )


def test_answer_skips_llm_when_documents_contain_no_usable_text():
    documents = [
        {"document": "", "metadata": {"source": "empty.pdf"}},
        {"document": "   ", "metadata": {"source": "blank.pdf"}},
    ]

    service, _, _, llm = make_service(documents)

    result = service.answer("What does the document say?")

    assert result["included_documents"] == 0
    assert result["skipped_documents"] == 2
    assert result["citations"] == []
    assert llm.prompts == []

def test_answer_deduplicates_identical_documents_from_different_sources():
    documents = [
        {
            "document": "Remote work policy applies to employees.",
            "metadata": {"source": "handbook-a.pdf", "page_number": 2},
        },
        {
            "document": "Remote work policy applies to employees.",
            "metadata": {"source": "handbook-b.pdf", "page_number": 7},
        },
    ]

    service, _, _, llm = make_service(documents)

    result = service.answer("What is the remote work policy?")

    assert result["included_documents"] == 1
    assert result["skipped_documents"] == 1
    assert result["citations"] == [
        {"source": "handbook-a.pdf", "page_number": 2}
    ]
    assert len(llm.prompts) == 1

def test_answer_handles_invalid_metadata():
    documents = [
        {
            "document": "Remote work policy applies to employees.",
            "metadata": ["invalid"],
        }
    ]

    service, _, _, _ = make_service(documents)

    result = service.answer("What is the remote work policy?")

    assert result["included_documents"] == 1
    assert result["citations"] == [
        {"source": "Unknown source", "page_number": None}
    ]