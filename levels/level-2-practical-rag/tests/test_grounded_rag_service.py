from services.context_builder import ContextBuilder
from services.grounded_rag_service import GroundedRAGService

import pytest


@pytest.mark.parametrize(
    "results",
    [
        {"documents": [[]]},
        {"documents": [["", "   \n"]]},
    ],
)
def test_empty_built_context_returns_fallback_without_calling_llm(results):
    class FakeLLM:
        def generate(self, prompt):
            raise AssertionError("LLM should not be called")

    service = GroundedRAGService(
        context_builder=ContextBuilder(),
        llm_service=FakeLLM(),
    )

    answer = service.answer(
        question="What is the bonus policy?",
        results=results,
    )

    assert answer == {
        "answer": "I don't have enough information to answer that question.",
        "citations": [],
    }


def test_empty_context_returns_fallback_without_calling_llm():
    class FakeLLM:
        def generate(self, prompt):
            raise AssertionError("LLM should not be called")

    class FakeContextBuilder:
        def build(self, results):
            return ""

    service = GroundedRAGService(
        context_builder=FakeContextBuilder(),
        llm_service=FakeLLM(),
    )

    answer = service.answer(
        question="What is the bonus policy?",
        results={"documents": [[]]},
    )

    assert answer == {
        "answer": "I don't have enough information to answer that question.",
        "citations": [],
    }


def test_available_context_is_sent_to_llm():
    class FakeLLM:
        def generate(self, prompt):
            assert "20 days of annual leave" in prompt
            assert "What is the annual leave allowance?" in prompt
            return "Employees receive 20 days of annual leave."

    class FakeContextBuilder:
        def build(self, results):
            return "Employees receive 20 days of annual leave."

    service = GroundedRAGService(
        context_builder=FakeContextBuilder(),
        llm_service=FakeLLM(),
    )

    answer = service.answer(
        question="What is the annual leave allowance?",
        results={
            "documents": [["unused test document"]],
            "metadatas": [
                [
                    {
                        "source": "employee_handbook.pdf",
                        "page_number": 2,
                        "chunk_index": 3,
                    }
                ]
            ],
        },
    )

    assert answer == {
        "answer": "Employees receive 20 days of annual leave.",
        "citations": ["Source: employee_handbook.pdf, Page: 2, Chunk: 3"],
    }


def test_whitespace_only_context_returns_fallback_without_calling_llm():
    class FakeLLM:
        def generate(self, prompt):
            raise AssertionError("LLM should not be called")

    class FakeContextBuilder:
        def build(self, results):
            return "   \n  "

    service = GroundedRAGService(
        context_builder=FakeContextBuilder(),
        llm_service=FakeLLM(),
    )

    answer = service.answer(
        question="What is the bonus policy?",
        results={"documents": [[]]},
    )
    assert answer == {
        "answer": "I don't have enough information to answer that question.",
        "citations": [],
    }


def test_answer_returns_answer_and_citations():
    class FakeLLM:
        def generate(self, prompt):
            return "Employees receive 20 days of annual leave."

    class FakeContextBuilder:
        def build(self, results):
            return "Employees receive 20 days of annual leave."

    service = GroundedRAGService(
        context_builder=FakeContextBuilder(),
        llm_service=FakeLLM(),
    )

    results = {
        "documents": [["Employees receive 20 days of annual leave."]],
        "metadatas": [
            [
                {
                    "source": "employee_handbook.pdf",
                    "page_number": 2,
                    "chunk_index": 3,
                }
            ]
        ],
    }

    response = service.answer(
        question="What is the annual leave allowance?",
        results=results,
    )

    assert response == {
        "answer": "Employees receive 20 days of annual leave.",
        "citations": ["Source: employee_handbook.pdf, Page: 2, Chunk: 3"],
    }


def test_answer_returns_multiple_citations():
    class FakeLLM:
        def generate(self, prompt):
            return "Employees receive annual leave and sick leave."

    class FakeContextBuilder:
        def build(self, results):
            return (
                "Employees receive 20 days of annual leave.\n"
                "Employees receive 10 days of sick leave."
            )

    service = GroundedRAGService(
        context_builder=FakeContextBuilder(),
        llm_service=FakeLLM(),
    )

    results = {
        "documents": [
            [
                "Employees receive 20 days of annual leave.",
                "Employees receive 10 days of sick leave.",
            ]
        ],
        "metadatas": [
            [
                {
                    "source": "employee_handbook.pdf",
                    "page_number": 2,
                    "chunk_index": 3,
                },
                {
                    "source": "leave_policy.pdf",
                    "page_number": 5,
                    "chunk_index": 7,
                },
            ]
        ],
    }

    response = service.answer(
        question="Explain the leave policies.",
        results=results,
    )

    assert response == {
        "answer": "Employees receive annual leave and sick leave.",
        "citations": [
            "Source: employee_handbook.pdf, Page: 2, Chunk: 3",
            "Source: leave_policy.pdf, Page: 5, Chunk: 7",
        ],
    }
